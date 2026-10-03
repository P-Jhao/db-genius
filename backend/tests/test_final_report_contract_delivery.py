"""The actual adapter receives a scoped strict final-report contract."""

import json
import logging

import pytest
from langchain_core.messages import HumanMessage, SystemMessage
from test_final_report_api import final_reply
from test_model_parameters import assert_parameters
from test_model_protocol import Provider, frame, model

from app.agent.final_report import REPORT_CONTRACT, IncompleteFinalReport
from app.agent.streaming import ModelStream
from app.agent.types import Usage

pytest_plugins = ["test_model_protocol"]


@pytest.mark.parametrize("ascii_only", [False, True])
@pytest.mark.asyncio
async def test_contract_is_final_only_and_every_character_fragment_decodes(
    provider: Provider, ascii_only: bool,
) -> None:
    text = '已验证 😀 "quoted" \\ path\n```sql\n-- Review only\n```\nUnfinished work remains.'
    wire = json.dumps({"report": text, "complete": True}, ensure_ascii=ascii_only)
    provider.replies = [final_reply("Ordinary Markdown."), final_reply('{"intent":"simple_chat"}'), [
        frame({"usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6}}),
        *[frame({"choices": [{"delta": {"content": character}}]}) for character in wire],
        frame({"choices": [{"delta": {}, "finish_reason": "stop"}]}), frame("[DONE]"),
    ]]
    emitted: list[tuple[str, object]] = []

    async def emit(kind: str, value: object, _step: int) -> None:
        emitted.append((kind, value))

    usage = Usage()
    stream = ModelStream(model(provider), emit, usage)
    messages = [SystemMessage(content="Use supplied evidence."), HumanMessage(content="Report results")]
    ordinary = await stream.call(messages)
    classified = await stream.call(messages, classification=True, event=None)
    emitted.clear()
    final = await stream.call(messages, event="summary_delta", final_report=True)
    assert ordinary.content == "Ordinary Markdown."
    assert classified.content == '{"intent":"simple_chat"}'
    assert final.content == stream.partial == text
    assert "".join(str(value) for kind, value in emitted if kind == "summary_delta") == text
    assert all(kind == "summary_delta" for kind, _value in emitted)
    assert final.response_metadata["summary_observation"]["framingVerified"] is True
    assert len(messages) == 2 and usage.callCount == 3 and usage.totalTokens == 18
    for index, payload in enumerate(provider.requests):
        assert_parameters(payload, classification=index == 1)
        assert "tools" not in payload
        sent = payload["messages"]
        assert isinstance(sent, list)
        assert [item["content"] for item in sent] == (
            [message.content for message in messages] + ([REPORT_CONTRACT] if index == 2 else [])
        )
    example = REPORT_CONTRACT.split("Formatting-only example: ", 1)[1].split(". Replace", 1)[0]
    assert json.loads(example) == {"report": "A short Markdown report.\nNext paragraph.", "complete": True}


@pytest.mark.parametrize(("value", "partial"), [
    ({"report": "Verified result.", "complete": True, "status": "done"}, "Verified result."),
    ({"report": "Verified result."}, "Verified result."),
    ({"complete": True}, ""),
    ({"answer": "Verified result.", "complete": True}, ""),
    ({"result": {"report": "Verified result.", "complete": True}}, ""),
])
@pytest.mark.asyncio
async def test_field_set_rejection_over_http_is_once_and_private(
    provider: Provider, caplog: pytest.LogCaptureFixture, value: dict[str, object], partial: str,
) -> None:
    provider.replies = [final_reply(json.dumps(value))]
    events: list[tuple[str, object]] = []

    async def emit(kind: str, content: object, _step: int) -> None:
        events.append((kind, content))

    usage = Usage()
    stream = ModelStream(model(provider), emit, usage)
    with caplog.at_level(logging.INFO, logger="app.agent.streaming"), pytest.raises(IncompleteFinalReport) as error:
        await stream.call([HumanMessage(content="Report")], event="summary_delta", final_report=True)
    assert error.value.code == "invalid_report_envelope"
    assert '"envelopeIssue": "field_set"' in caplog.text
    assert stream.partial == "".join(str(content) for _kind, content in events) == partial
    assert len(provider.requests) == usage.callCount == 1 and usage.totalTokens == 6
    assert all(kind == "summary_delta" for kind, _content in events)
    assert "envelopeIssue" not in json.dumps(events) and "field_set" not in str(error.value)


@pytest.mark.parametrize(("reason", "structured", "expected"), [
    ("length", False, "provider_length"),
    ("content_filter", False, "provider_content_filter"),
    ("function_call", False, "unexpected_summary_tool_call"),
    ("length", True, "unexpected_summary_tool_call"),
])
@pytest.mark.asyncio
async def test_bad_field_set_does_not_change_provider_and_tool_priority(
    provider: Provider, reason: str, structured: bool, expected: str,
) -> None:
    reply = final_reply('{"report":"Result.","complete":true,"status":"done"}', reason)
    if structured:
        reply.insert(2, frame({"choices": [{"delta": {"tool_calls": [{
            "index": 0, "id": "unexpected", "function": {"name": "executeSql", "arguments": "{}"},
        }]}}]}))
    provider.replies = [reply]

    async def emit(_kind: str, _content: object, _step: int) -> None:
        pass

    usage = Usage()
    with pytest.raises(IncompleteFinalReport) as error:
        await ModelStream(model(provider), emit, usage).call(
            [HumanMessage(content="Report")], event="summary_delta", final_report=True,
        )
    assert error.value.code == expected
    assert len(provider.requests) == usage.callCount == 1 and usage.totalTokens == 6
