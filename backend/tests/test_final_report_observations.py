"""Observation fields retain completion evidence without message content."""

import hashlib
import json
import threading
from time import monotonic

import httpx
import pytest
from pydantic import SecretStr
from real_model_cases import MODEL
from real_model_observations import (
    ProviderTextObserver,
    record_finish_reason,
    safe_observation,
    summary_delivery,
)
from real_model_relay import RealProviderRelay, consume_frames
from test_model_protocol import Provider, frame

from app.agent.final_report import REPORT_CONTRACT


def test_relay_keeps_actual_terminal_reason_across_frame_splits() -> None:
    packet = b'data: {"choices":[{"delta":{},"finish_reason":"length"}]}\r\n\r\n'
    report: dict[str, object] = {"firstDeltaSeconds": None, "providerDone": False}
    pending = b""
    for part in packet:
        pending = consume_frames(pending, bytes([part]), report, monotonic())
    assert pending == b"" and report["finishReason"] == "length"


@pytest.mark.parametrize("choice", [
    {"finish_reason": "length"},
    {"delta": None, "finish_reason": "length"},
    {"delta": {}, "finish_reason": "length"},
])
def test_finish_reason_is_observed_with_missing_null_or_empty_delta(choice: dict[str, object]) -> None:
    observer = ProviderTextObserver({"messages": [{"role": "system", "content": REPORT_CONTRACT}]})
    observer.consume({"delta": {"content": '{"report":"OK","complete":true}'}})
    report: dict[str, object] = {"firstDeltaSeconds": None, "providerDone": False}
    pending = consume_frames(b"", frame({"choices": [choice]}), report, monotonic(), observer)
    assert pending == b"" and report["finishReason"] == "length" and report["finishReasonPresent"] is True
    observer.finish(report)
    final = report["finalReport"]
    assert isinstance(final, dict) and final["finishReason"] == "length" and final["framingVerified"] is False


def test_unknown_finish_reason_is_not_retained_as_plaintext() -> None:
    report: dict[str, object] = {}
    record_finish_reason({"finish_reason": "test-secret-value"}, report)
    assert report["finishReason"] == "other"
    assert "test-secret-value" not in json.dumps(report)


def test_summary_observation_uses_an_explicit_safe_field_allowlist() -> None:
    raw = {"wireCharacters": 20, "wireUtf8Sha256": "a" * 64,
           "rawReportCharacters": 2, "rawReportUtf8Sha256": "b" * 64,
           "cleanedReportCharacters": 2, "cleanedReportUtf8Sha256": "b" * 64,
           "finishReason": "stop", "structuredToolCallCount": 0, "protocolCleanup": "none",
           "envelopeComplete": True, "framingVerified": True, "errorCode": None,
           "rawContent": "test-secret-value", "authorization": "test-secret-value"}
    kept = safe_observation(raw)
    assert kept["wireCharacters"] == 20
    assert "test-secret-value" not in json.dumps(kept)
    with pytest.raises(TypeError, match="count"):
        safe_observation({"wireCharacters": True})


def test_provider_hashes_and_final_delivery_are_observed_without_raw_text() -> None:
    text = '中文 "test-secret-value" 😀\n```sql\nSELECT 1 < 2;\n```'
    wire = json.dumps({"report": text, "complete": True})
    observer = ProviderTextObserver({"messages": [{"role": "system", "content": REPORT_CONTRACT}]})
    report: dict[str, object] = {"firstDeltaSeconds": None, "providerDone": False,
                                "transportError": None, "evidenceError": None}
    packets = b"".join([frame({"choices": [{"delta": {"content": wire}}]}),
                        frame({"choices": [{"delta": {}, "finish_reason": "stop"}]}), frame("[DONE]")])
    pending = b""
    for character in packets:
        pending = consume_frames(pending, bytes([character]), report, monotonic(), observer)
    observer.finish(report)
    final = report["finalReport"]
    assert isinstance(final, dict) and final["framingVerified"] is True
    assert final["cleanedReportUtf8Sha256"] == hashlib.sha256(text.encode()).hexdigest()
    delivery = summary_delivery([{"type": "summary_delta", "content": text[:3]},
                                 {"type": "summary_delta", "content": text[3:]},
                                 {"type": "summary", "content": text}])
    assert delivery["streamedMatchesAuthoritative"] is True
    assert delivery["authoritativeUtf8Sha256"] == final["cleanedReportUtf8Sha256"]
    assert "test-secret-value" not in json.dumps({"provider": report, "delivery": delivery})


def test_missing_provider_terminal_is_never_completed_by_observer() -> None:
    observer = ProviderTextObserver({"messages": [{"role": "system", "content": REPORT_CONTRACT}]})
    observer.consume({"delta": {"content": '{"report":"OK","complete":true}'}})
    report: dict[str, object] = {"providerDone": False, "transportError": "BrokenPipeError"}
    observer.finish(report)
    final = report["finalReport"]
    assert isinstance(final, dict) and final["envelopeComplete"] is True
    assert final["streamComplete"] is False and final["framingVerified"] is False
    assert final["finishReason"] is None and final["errorCode"] == "provider_stream_incomplete"


def test_local_relay_forwards_exact_response_bytes_and_keeps_only_digests() -> None:
    wire = json.dumps({"report": "test-secret-value 中文", "complete": True})
    packets = [frame({"choices": [{"delta": {"content": wire}}]}),
               frame({"choices": [{"delta": {}, "finish_reason": "stop"}]}), frame("[DONE]")]
    upstream = Provider([packets])
    upstream_thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    upstream_thread.start()
    host, port = upstream.server_address
    relay = RealProviderRelay(SecretStr("test-upstream-key"), f"http://{host}:{port}")
    relay_thread = threading.Thread(target=relay.serve_forever, daemon=True)
    relay_thread.start()
    try:
        relay_port = relay.server_address[1]
        request = {"model": MODEL, "stream": True, "temperature": 0.7,
                   "messages": [{"role": "system", "content": REPORT_CONTRACT}]}
        with httpx.Client(trust_env=False) as client:
            response = client.post(f"http://127.0.0.1:{relay_port}/python/v1/chat/completions",
                                   headers={"Authorization": "Bearer " + relay.access_key.get_secret_value()},
                                   json=request)
        assert response.content == b"".join(packets)
        assert upstream.requests == [request]
        evidence = relay.evidence(0)
        assert len(evidence) == 1 and evidence[0]["finishReason"] == "stop"
        assert "test-secret-value" not in json.dumps(evidence)
    finally:
        relay.shutdown()
        relay.server_close()
        relay_thread.join(2)
        upstream.shutdown()
        upstream.server_close()
        upstream_thread.join(2)
