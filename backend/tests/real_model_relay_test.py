"""Relay protocol contract; the local upstream here is explicitly not effect evidence."""

from __future__ import annotations

import gzip
import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from time import monotonic

import httpx
import pytest
from pydantic import SecretStr
from real_model_relay import RealProviderRelay, consume_frames, generation_parameters

PACKETS = (
    {"choices": [{"delta": {"reasoning_content": "private-reasoning"}}]},
    {"choices": [{"delta": {"content": "杭州"}}]},
    {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call", "function": {
        "name": "executeSql", "arguments": '{"name":"深圳"}',
    }}]}}]},
    {"choices": [{"delta": {}, "finish_reason": "stop"}],
     "usage": {"prompt_tokens": 17, "completion_tokens": 9, "total_tokens": 26}},
)
WIRE = b"".join(("data: " + json.dumps(packet, ensure_ascii=False) + "\r\n\r\n").encode()
                for packet in PACKETS) + b"data: [DONE]\r\n\r\n"


class Upstream(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, wire: bytes = WIRE, encoding: str | None = None) -> None:
        self.requests: list[bytes] = []
        self.wire = wire
        self.encoding = encoding
        super().__init__(("127.0.0.1", 0), Handler)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self) -> None:
        server = self.server
        assert isinstance(server, Upstream)
        assert self.headers["Authorization"] == "Bearer relay-contract-upstream"
        server.requests.append(self.rfile.read(int(self.headers["Content-Length"])))
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        if server.encoding is not None:
            self.send_header("Content-Encoding", server.encoding)
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        # Every byte is its own HTTP chunk, including Unicode and CR/LF boundaries.
        for byte in server.wire:
            self.wfile.write(b"1\r\n" + bytes([byte]) + b"\r\n")
        self.wfile.write(b"0\r\n\r\n")
        self.wfile.flush()

    def log_message(self, format: str, *args: object) -> None:
        pass


@contextmanager
def services(wire: bytes = WIRE, encoding: str | None = None) -> Iterator[tuple[RealProviderRelay, Upstream]]:
    upstream = Upstream(wire, encoding)
    relay = RealProviderRelay(SecretStr("relay-contract-upstream"),
                             f"http://127.0.0.1:{upstream.server_port}")
    threads = []
    for service in (upstream, relay):
        thread = threading.Thread(target=service.serve_forever, daemon=True)
        thread.start()
        threads.append(thread)
    try:
        yield relay, upstream
    finally:
        for service in (relay, upstream):
            service.shutdown()
            service.server_close()
        for thread in threads:
            thread.join(3)


def test_every_unicode_crlf_boundary_preserves_usage_and_done_evidence() -> None:
    report: dict[str, object] = {"usage": None, "providerDone": False, "firstDeltaSeconds": None}
    pending = b""
    for byte in WIRE:
        pending = consume_frames(pending, bytes([byte]), report, monotonic())
    assert pending == b""
    assert report["usage"] == {"prompt_tokens": 17, "completion_tokens": 9, "total_tokens": 26}
    assert report["providerDone"] is True and isinstance(report["firstDeltaSeconds"], float)
    assert "evidenceError" not in report
    assert "private-reasoning" not in json.dumps(report)


@pytest.mark.parametrize("variant", ["python", "java"])
def test_request_parameters_and_response_bytes_are_transparent(variant: str) -> None:
    with services() as (relay, upstream):
        payload = json.dumps({
            "model": "deepseek-flash", "temperature": 0.7, "top_p": 1,
            "thinking": {"type": "enabled"}, "stream": True,
            "messages": [{"role": "user", "content": "synthetic-prompt"}],
            "tools": [{"type": "function", "function": {"name": "executeSql"}}],
        }, separators=(",", ":")).encode()
        response = httpx.post(f"http://127.0.0.1:{relay.server_port}/{variant}/v1/chat/completions",
                              content=payload, headers={"Authorization": "Bearer " + relay.access_key.get_secret_value()})
        assert response.status_code == 200 and response.content == WIRE
        assert upstream.requests == [payload]
        report = relay.evidence(0)[0]
        assert report["parameters"] == {
            "model": "deepseek-flash", "temperature": 0.7, "top_p": 1, "max_tokens": None,
            "max_completion_tokens": None, "thinking": {"type": "enabled"}, "reasoning_effort": None,
            "frequency_penalty": None, "presence_penalty": None, "seed": None, "response_format": None,
        }
        assert report["providerDone"] is True and report["evidenceError"] is None
        assert report["transportError"] is None and report["usage"] is not None
        assert "private-reasoning" not in json.dumps(report) and "synthetic-prompt" not in json.dumps(report)


def test_unauthenticated_request_is_not_forwarded() -> None:
    with services() as (relay, upstream):
        response = httpx.post(f"http://127.0.0.1:{relay.server_port}/python/v1/chat/completions",
                              json={"model": "deepseek-flash"}, headers={"Authorization": "Bearer wrong"})
        assert response.status_code == 401
        assert not upstream.requests and not relay.evidence(0)


def test_complete_multiline_frame_joins_data_fields_before_json_parsing() -> None:
    report: dict[str, object] = {"usage": None, "providerDone": False, "firstDeltaSeconds": None}
    wire = (b': comment\r\nevent: message\r\ndata: {"choices": [],\r\n'
            b'data: "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}}\r\n\r\n'
            b'data: [DONE]\r\n\r\n')
    for boundary in range(len(wire) + 1):
        pending = consume_frames(b"", wire[:boundary], report, monotonic())
        pending = consume_frames(pending, wire[boundary:], report, monotonic())
        assert not pending and "evidenceError" not in report
    assert report["usage"] == {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}
    assert report["providerDone"] is True


def test_gzip_upstream_is_forwarded_as_raw_bytes_and_marked_unparsed() -> None:
    wire = gzip.compress(WIRE)
    with services(wire, "gzip") as (relay, _upstream):
        with httpx.stream("POST", f"http://127.0.0.1:{relay.server_port}/python/v1/chat/completions",
                          json={"model": "deepseek-flash", "stream": True},
                          headers={"Authorization": "Bearer " + relay.access_key.get_secret_value()}) as response:
            assert response.headers["content-encoding"] == "gzip"
            assert b"".join(response.iter_raw()) == wire
        report = relay.evidence(0)[0]
        assert report["evidenceError"] == "UnsupportedContentEncoding"
        assert report["transportError"] is None and report["usage"] is None


def test_malformed_evidence_never_interrupts_raw_provider_response() -> None:
    wire = b"data: invalid-json\r\n\r\n" + WIRE
    with services(wire) as (relay, _upstream):
        response = httpx.post(f"http://127.0.0.1:{relay.server_port}/java/v1/chat/completions",
                              json={"model": "deepseek-flash", "stream": True},
                              headers={"Authorization": "Bearer " + relay.access_key.get_secret_value()})
        assert response.content == wire
        report = relay.evidence(0)[0]
        assert report["evidenceError"] == "JSONDecodeError" and report["providerDone"] is True
        assert report["usage"] is not None and report["transportError"] is None


def test_unexpected_text_in_generation_controls_is_rejected_without_recording() -> None:
    with services() as (relay, upstream):
        response = httpx.post(f"http://127.0.0.1:{relay.server_port}/java/v1/chat/completions",
                              json={"model": "deepseek-flash", "temperature": "private-input"},
                              headers={"Authorization": "Bearer " + relay.access_key.get_secret_value()})
        assert response.status_code == 400 and not upstream.requests and not relay.evidence(0)


def test_spring_style_chunked_request_body_is_forwarded_unchanged() -> None:
    with services() as (relay, upstream):
        payload = json.dumps({"model": "deepseek-flash", "stream": True,
                              "messages": [{"role": "user", "content": "合成分类输入"}]}).encode()
        relay.begin("classification-contract")
        response = httpx.post(f"http://127.0.0.1:{relay.server_port}/java/v1/chat/completions",
                              content=iter([payload[:17], payload[17:]]),
                              headers={"Authorization": "Bearer " + relay.access_key.get_secret_value()})
        assert response.status_code == 200 and response.content == WIRE
        assert upstream.requests == [payload]
        request = relay.request_evidence("classification-contract", "java")[0]
        assert request["transferEncodingPresent"] is True and request["contentLengthPresent"] is False
        assert request["bodyBytes"] == len(payload) and request["httpStatus"] == 200
        assert "合成分类输入" not in json.dumps(request) and "Authorization" not in json.dumps(request)


def test_response_format_controls_affect_comparability_without_recording_schema_text() -> None:
    ordinary = generation_parameters({"model": "deepseek-flash"})
    classified = generation_parameters({"model": "deepseek-flash", "response_format": {"type": "json_object"}})
    assert ordinary["response_format"] is None and classified["response_format"] == {"type": "json_object"}
    schema = generation_parameters({"model": "deepseek-flash", "response_format": {
        "type": "json_schema", "json_schema": {"description": "private synthetic input", "type": "object"}}})
    assert "private synthetic input" not in json.dumps(schema)
    assert len(str(schema["response_format"])) > 64
