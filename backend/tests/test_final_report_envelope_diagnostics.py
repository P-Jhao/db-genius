"""Bounded envelope diagnostics preserve rejection and public report behavior."""

import json
import logging
from collections.abc import AsyncIterator
from typing import cast

import pytest
from langchain_core.messages import AIMessageChunk, BaseMessage, HumanMessage
from real_model_observations import ProviderTextObserver, safe_observation

from app.agent.final_report import IncompleteFinalReport, ReportCompletion, ReportDecoder
from app.agent.model import CompatibleChatModel
from app.agent.streaming import ModelStream
from app.agent.types import Usage

PRIVATE = "SYNTHETIC_ENVELOPE_PRIVATE_TOKEN"


def decode(wire: str, reason: str | None = "stop", calls: int = 0) -> ReportCompletion:
    decoder = ReportDecoder()
    for character in wire:
        decoder.push(character)
    return decoder.finish(reason, calls)


@pytest.mark.parametrize(("wire", "issue", "content"), [
    pytest.param('{"report":"unfinished', "invalid_json", "unfinished", id="truncated-json"),
    pytest.param('{"report":"prefix\\q","complete":true}', "invalid_json", "prefix", id="invalid-escape"),
    pytest.param('{"report":"OK","complete":false,"complete":true}',
                 "duplicate_field", "OK", id="duplicate-completion"),
    pytest.param('{"report":"OK","complete":true,"extra":{"n":1,"n":2}}',
                 "duplicate_field", "OK", id="nested-duplicate-rejected"),
    pytest.param('[]', "not_object", "", id="non-object"),
    pytest.param(json.dumps({"report": "OK", "complete": True, PRIVATE: PRIVATE}),
                 "field_set", "OK", id="extra-private-field"),
    pytest.param('{"report":7,"complete":true}', "report_not_text", "", id="non-text-report"),
    pytest.param('{"report":"OK","complete":false}', "completion_not_true", "OK", id="not-complete"),
    pytest.param('{"complete":true,"report":"OK"}', "report_not_closed", "", id="unstreamed-report-order"),
])
def test_invalid_envelopes_keep_original_error_and_partial_content(
    wire: str, issue: str, content: str,
) -> None:
    result = decode(wire)
    assert result.content == content and result.error == "invalid_report_envelope"
    assert result.observation["envelopeIssue"] == issue
    assert result.observation["errorCode"] == result.error
    assert result.observation["envelopeComplete"] is False
    assert result.observation["framingVerified"] is False
    assert PRIVATE not in json.dumps(result.observation)


@pytest.mark.parametrize("completion", [None, 1, "true"])
def test_legal_json_completion_requires_the_boolean_true(completion: object) -> None:
    wire = json.dumps({"report": "OK", "complete": completion})
    result = decode(wire)
    assert result.content == "OK" and result.error == "invalid_report_envelope"
    assert result.observation["envelopeIssue"] == "completion_not_true"


def test_report_state_mismatch_remains_a_rejection() -> None:
    decoder = ReportDecoder()
    decoder.push('{"report":"verified","complete":true}')
    decoder.text = "different internal report"
    result = decoder.finish("stop", 0)
    assert result.content == decoder.text and result.error == "invalid_report_envelope"
    assert result.observation["envelopeIssue"] == "report_mismatch"


@pytest.mark.parametrize("ascii_only", [False, True])
def test_valid_unicode_report_survives_every_fragment_boundary(ascii_only: bool) -> None:
    text = '中文 😀 "quoted" \\ slash\n```sql\nSELECT 1 < 2;\n```'
    wire = json.dumps({"report": text, "complete": True}, ensure_ascii=ascii_only)
    for split in range(len(wire) + 1):
        decoder = ReportDecoder()
        streamed = decoder.push(wire[:split]) + decoder.push(wire[split:])
        result = decoder.finish("stop", 0)
        assert streamed == result.content == text and result.error is None
        assert result.observation["envelopeIssue"] is None
        assert result.observation["envelopeComplete"] is True
        assert result.observation["framingVerified"] is True
        assert safe_observation(result.observation) == result.observation


@pytest.mark.parametrize(("reason", "calls", "error"), [
    ("stop", 0, "unexpected_summary_protocol"),
    ("length", 0, "provider_length"),
    ("content_filter", 0, "provider_content_filter"),
    ("length", 1, "unexpected_summary_tool_call"),
    ("function_call", 0, "unexpected_summary_tool_call"),
    (PRIVATE, 0, "provider_other_finish"),
], ids=["dsml", "length", "filter", "tool-priority", "tool-finish", "unknown-finish"])
def test_provider_tool_and_dsml_priority_keeps_secondary_envelope_issue(
    reason: str, calls: int, error: str,
) -> None:
    text = ('Before <｜DSML｜tool_calls><｜DSML｜invoke name="doTerminate">'
            '</｜DSML｜invoke></｜DSML｜tool_calls> after')
    result = decode(json.dumps({"report": text, "complete": False}), reason, calls)
    assert result.content == "Before  after" and result.error == error
    assert result.observation["errorCode"] == error
    assert result.observation["protocolCleanup"] == "removed"
    assert result.observation["envelopeIssue"] == "completion_not_true"
    assert PRIVATE not in json.dumps(result.observation)


def test_unclosed_dsml_still_overrides_invalid_envelope() -> None:
    result = decode(json.dumps({"report": 'Before <｜DSML｜invoke name="doTerminate">', "complete": False}))
    assert result.error == "incomplete_protocol"
    assert result.observation["envelopeIssue"] == "completion_not_true"


def test_empty_report_is_not_an_envelope_structure_failure() -> None:
    result = decode('{"report":" ","complete":true}')
    assert result.error == "empty_report" and result.observation["envelopeComplete"] is True
    assert result.observation["envelopeIssue"] is None


def test_allowlist_rejects_unknown_diagnostics_and_discards_private_details() -> None:
    observation = decode(json.dumps({"report": "OK", "complete": True, PRIVATE: PRIVATE})).observation
    raw = {**observation, "rawWire": PRIVATE, "fieldNames": [PRIVATE], "jsonPosition": 42,
           "prompt": PRIVATE, "sql": PRIVATE, "errorBody": PRIVATE, "traceback": PRIVATE}
    safe = safe_observation(raw)
    assert safe == observation and safe["envelopeIssue"] == "field_set"
    assert PRIVATE not in json.dumps(safe)
    for invalid in (PRIVATE, "", True, 0, [], {}):
        with pytest.raises(ValueError, match="^Unknown summary envelope issue$") as rejected:
            safe_observation({"envelopeIssue": invalid})
        assert PRIVATE not in str(rejected.value)


@pytest.mark.parametrize("provider_done", [False, True])
def test_provider_observer_keeps_envelope_issue_when_stream_error_has_priority(provider_done: bool) -> None:
    from app.agent.final_report import REPORT_CONTRACT

    observer = ProviderTextObserver({"messages": [{"role": "system", "content": REPORT_CONTRACT}]})
    observer.consume({"delta": {"content": '{"report":"OK","complete":false}'}, "finish_reason": "stop"})
    report: dict[str, object] = {"providerDone": provider_done, "transportError": None, "evidenceError": None}
    observer.finish(report)
    final = report["finalReport"]
    assert isinstance(final, dict)
    assert final["envelopeIssue"] == "completion_not_true" and final["framingVerified"] is False
    assert final["errorCode"] == ("invalid_report_envelope" if provider_done else "provider_stream_incomplete")


class SyntheticModel:
    def __init__(self, wire: str) -> None:
        self.wire = wire
        self.requests: list[tuple[list[BaseMessage], dict[str, object]]] = []

    async def astream(self, messages: list[BaseMessage], **options: object) -> AsyncIterator[AIMessageChunk]:
        self.requests.append((messages, options))
        for offset in range(0, len(self.wire), 3):
            yield AIMessageChunk(content=self.wire[offset:offset + 3])
        yield AIMessageChunk(content="", response_metadata={"finish_reason": "stop"},
                             usage_metadata={"input_tokens": 11, "output_tokens": 7, "total_tokens": 18})


@pytest.mark.asyncio
async def test_actual_stream_rejects_invalid_envelope_once_without_public_diagnostics(
    caplog: pytest.LogCaptureFixture,
) -> None:
    wire = json.dumps({"report": "OK", "complete": True, PRIVATE: PRIVATE})
    model = SyntheticModel(wire)
    events: list[tuple[str, object]] = []

    async def emit(kind: str, value: object, _step: int) -> None:
        events.append((kind, value))

    usage = Usage()
    stream = ModelStream(cast(CompatibleChatModel, model), emit, usage)
    with (
        caplog.at_level(logging.INFO, logger="app.agent.streaming"),
        pytest.raises(IncompleteFinalReport) as rejected,
    ):
        await stream.call([HumanMessage(content="Report saved results")], event="summary_delta", final_report=True)
    assert type(rejected.value) is IncompleteFinalReport and rejected.value.code == "invalid_report_envelope"
    assert PRIVATE not in str(rejected.value) and PRIVATE not in caplog.text
    assert '"envelopeIssue": "field_set"' in caplog.text
    assert usage.callCount == 1 and usage.totalTokens == 18 and len(model.requests) == 1
    assert "tools" not in model.requests[0][1] and stream.partial == "OK"
    assert all(kind == "summary_delta" for kind, _ in events)
    assert "".join(str(content) for _, content in events) == "OK"
    assert "envelopeIssue" not in json.dumps(events) and PRIVATE not in json.dumps(events)
