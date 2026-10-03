"""Final-report framing, escaping and cancellation over the actual adapter."""

import json
import threading

import pytest
from langchain_core.messages import HumanMessage
from test_model_protocol import Provider, frame, model

from app.agent.cancellation import RunAborted
from app.agent.final_report import REPORT_CONTRACT, ReportDecoder
from app.agent.streaming import ModelStream
from app.agent.types import Usage

pytest_plugins = ["test_model_protocol"]


def envelope(text: str) -> str:
    return json.dumps({"report": text, "complete": True}, ensure_ascii=True)


@pytest.mark.parametrize("text", [
    "OK", 'Quoted "value", backslash \\, tab\t and line\nnext.',
    "中文报告、emoji 😀、日本語、한국어", "```sql\nSELECT 1 WHERE 1 < 2;\n```",
    "普通 DSML 词语和 <html> 标签保持原样。",
])
def test_every_escape_boundary_decodes_only_markdown(text: str) -> None:
    wire = envelope(text)
    for split in range(len(wire) + 1):
        decoder = ReportDecoder()
        streamed = decoder.push(wire[:split]) + decoder.push(wire[split:])
        completed = decoder.finish("stop", 0)
        assert streamed == text == completed.content
        assert completed.error is None
        assert completed.observation["framingVerified"] is True
    decoder = ReportDecoder()
    assert "".join(decoder.push(character) for character in wire) == text


@pytest.mark.parametrize("wire", [
    '{"report":"unfinished', '{"report":"closed", "complete":false}',
    '{"report":"closed", "complete":true, "extra":1}',
    '{"report":"bad\\q", "complete":true}',
    '{"report":"closed", "complete":false, "complete":true}',
    '{"report":"closed", "report":"closed", "complete":true}',
])
def test_incomplete_or_invalid_envelope_is_not_completed(wire: str) -> None:
    decoder = ReportDecoder()
    decoder.push(wire)
    result = decoder.finish(None, 0)
    assert result.error is not None and result.observation["framingVerified"] is False


def test_protocol_removal_and_unclosed_protocol_are_distinct() -> None:
    block = ('<｜DSML｜tool_calls><｜DSML｜invoke name="doTerminate">'
             '<｜DSML｜parameter name="reason" string="true">done</｜DSML｜parameter>'
             '</｜DSML｜invoke></｜DSML｜tool_calls>')
    decoder = ReportDecoder()
    decoder.push(envelope("Before " + block + " after"))
    complete = decoder.finish("stop", 0)
    assert complete.content == "Before  after" and complete.error == "unexpected_summary_protocol"
    assert complete.observation["protocolCleanup"] == "removed"
    assert complete.observation["envelopeComplete"] is True and complete.observation["framingVerified"] is False
    decoder = ReportDecoder()
    decoder.push(envelope('Before <｜DSML｜invoke name="executeSql">unclosed'))
    incomplete = decoder.finish("stop", 0)
    assert incomplete.error == "incomplete_protocol"


@pytest.mark.asyncio
async def test_seven_languages_stream_markdown_and_preserve_parameters(provider: Provider) -> None:
    texts = ["已确认写入。", "已確認寫入。", "Verified result.", "Resultado confirmado.",
             "Résultat confirmé.", "確認済み。", "Keputusan disahkan."]
    provider.replies = []
    for text in texts:
        wire = envelope(text)
        provider.replies.append([
            *[frame({"choices": [{"delta": {"content": wire[i:i + 3]}}]})
              for i in range(0, len(wire), 3)],
            frame({"choices": [{"delta": {}, "finish_reason": "stop"}]}),
            frame({"usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6}}),
            frame("[DONE]"),
        ])
    usage = Usage()
    for text in texts:
        emitted: list[str] = []

        async def emit(kind: str, value: object, _step: int, captured: list[str] = emitted) -> None:
            if kind == "summary_delta":
                assert isinstance(value, str)
                captured.append(value)

        result = await ModelStream(model(provider), emit, usage).call(
            [HumanMessage(content="Report verified observations")], event="summary_delta", final_report=True,
        )
        assert "".join(emitted) == result.content == text
        assert "complete" not in "".join(emitted)
        assert result.response_metadata["summary_observation"]["framingVerified"] is True
    assert usage.callCount == 7 and usage.totalTokens == 42
    for request in provider.requests:
        assert request["temperature"] == 0.7 and "tools" not in request
        assert request["stream_options"] == {"include_usage": True}
        assert request["messages"][-1]["content"] == REPORT_CONTRACT
        assert "response_format" not in request


@pytest.mark.asyncio
async def test_cancellation_preserves_readable_partial_and_usage(provider: Provider) -> None:
    wire = envelope("Verified rows. Remaining explanation.")
    split = wire.index("Remaining")
    provider.replies = [[
        frame({"usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8}}),
        frame({"choices": [{"delta": {"content": wire[:split]}}]}),
        frame({"choices": [{"delta": {"content": wire[split:]}}]}), frame("[DONE]"),
    ]]
    cancellation = threading.Event()
    events: list[tuple[str, object]] = []

    async def emit(kind: str, value: object, _step: int) -> None:
        events.append((kind, value))
        if kind == "summary_delta":
            cancellation.set()

    usage = Usage()
    stream = ModelStream(model(provider), emit, usage, cancellation)
    with pytest.raises(RunAborted):
        await stream.call([HumanMessage(content="report")], event="summary_delta", final_report=True)
    assert stream.partial == "Verified rows. "
    assert events == [("summary_delta", "Verified rows. ")]
    assert usage.callCount == 1 and usage.totalTokens == 8
