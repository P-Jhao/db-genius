"""Original structured calls win; recovered text never grants extra capabilities."""

import json
import threading

import pytest
from langchain_core.messages import HumanMessage, ToolMessage
from test_dsml import _invoke, _parameter, _reply, _sql_text, _tools, _wrapper
from test_model_protocol import Provider, frame, model

from app.agent.cancellation import RunAborted
from app.agent.dsml import AllowedTool, StructuredCall, reconcile, strip
from app.agent.streaming import ModelStream
from app.agent.types import Usage

pytest_plugins = ["test_model_protocol"]

ALLOWED = {"executeSql": AllowedTool(frozenset({"db_id", "statement"}),
                                     frozenset({"db_id", "statement"}))}


def test_original_valid_structured_arguments_win_and_ids_are_not_duplicated() -> None:
    clean, calls = reconcile(_sql_text(), [StructuredCall("executeSql", json.dumps({
        "db_id": 12, "statement": "SELECT 2",
    }), "original")], ALLOWED)
    assert clean == "" and calls is not None
    assert calls[0]["args"] == {"db_id": 12, "statement": "SELECT 2"}
    double = _wrapper(_invoke("executeSql", _parameter("db_id", "12")
                               + _parameter("statement", "SELECT 1", string=True)) * 2)
    with pytest.raises(ValueError, match="Duplicate tool-call IDs"):
        reconcile(double, [StructuredCall("executeSql", "", "same")] * 2, ALLOWED)


@pytest.mark.parametrize("arguments", ["[]", "null", "true", '"text"'])
def test_valid_non_object_json_is_not_silently_repaired(arguments: str) -> None:
    with pytest.raises(TypeError, match="JSON object"):
        reconcile(_sql_text(), [StructuredCall("executeSql", arguments, "id")], ALLOWED)


@pytest.mark.parametrize("number", ["NaN", "Infinity", "-inf", "1e999"])
def test_non_finite_numbers_and_missing_fields_fail_explicitly(number: str) -> None:
    content = _wrapper(_invoke("executeSql", _parameter("db_id", number)
                               + _parameter("statement", "SELECT 1", string=True)))
    with pytest.raises(ValueError, match="Non-finite"):
        reconcile(content, [], ALLOWED)


def test_original_invoke_only_and_residual_prose_are_supported() -> None:
    text = _invoke("executeSql", _parameter("db_id", "12")
                    + _parameter("statement", "SELECT 1", string=True))
    clean, calls = reconcile(text, [], ALLOWED)
    assert clean == "" and calls is not None
    args = calls[0]["args"]
    assert isinstance(args, dict) and args["statement"] == "SELECT 1"
    assert strip("Conclusion\n<｜｜DSML｜｜tool_calls>\nunfinished prose") == "Conclusion\n\nunfinished prose"
    assert strip("x < y and trailing <") == "x < y and trailing <"
    with pytest.raises(ValueError, match="missing required"):
        reconcile(_wrapper(_invoke("executeSql", _parameter("db_id", "12"))), [], ALLOWED)


@pytest.mark.asyncio
async def test_fragmented_ids_names_invalid_json_recovery_and_reasoning_roundtrip(provider: Provider) -> None:
    provider.replies = [[
        frame({"choices": [{"delta": {"content": _sql_text()[:40], "reasoning_content": "read ",
            "tool_calls": [{"index": 0, "id": "call_", "function": {
                "name": "execute", "arguments": "{invalid"}}]}}]}),
        frame({"choices": [{"delta": {"content": _sql_text()[40:], "reasoning_content": "schema",
            "tool_calls": [{"index": 0, "id": "fragment", "function": {
                "name": "Sql", "arguments": " json"}}]}}]}),
        frame({"usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6}}),
        frame({"usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6}}),
        frame("[DONE]"),
    ], _reply("Verified")]

    async def emit(_kind: str, _text: object, _step: int) -> None:
        pass

    usage = Usage()
    stream = ModelStream(model(provider), emit, usage)
    result = await stream.call([HumanMessage(content="query")], tools=_tools(), event=None)
    assert result.tool_calls[0]["id"] == "call_fragment"
    assert result.tool_calls[0]["name"] == "executeSql"
    assert result.additional_kwargs["reasoning_content"] == "read schema"
    assert usage.callCount == 1 and usage.totalTokens == 6
    await stream.call([result, ToolMessage(content="one row", tool_call_id="call_fragment")])
    sent = provider.requests[1]["messages"]
    assert isinstance(sent, list)
    assert sent[0]["reasoning_content"] == "read schema"
    assert sent[0]["tool_calls"][0]["id"] == sent[1]["tool_call_id"] == "call_fragment"
    assert provider.requests[0]["temperature"] == 0.7


@pytest.mark.asyncio
async def test_plain_code_remains_text_and_summary_cancellation_never_emits_protocol(provider: Provider) -> None:
    example = f"Example only:\n```xml\n{_sql_text()}\n```"
    provider.replies = [_reply(example), [
        frame({"usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6}}),
        frame({"choices": [{"delta": {"content": "Verified <"}}]}),
        frame({"choices": [{"delta": {"content": _sql_text()[1:]}}]}), frame("[DONE]"),
    ]]
    cancellation = threading.Event()
    events: list[str] = []

    async def emit(kind: str, value: object, _step: int) -> None:
        assert isinstance(value, str)
        events.append(value)
        if kind == "summary_delta":
            cancellation.set()

    usage = Usage()
    stream = ModelStream(model(provider), emit, usage, cancellation)
    answer = await stream.call([HumanMessage(content="explain")], event="content")
    assert answer.content == example and not answer.tool_calls
    events.clear()
    with pytest.raises(RunAborted):
        await stream.call([HumanMessage(content="summarize")], event="summary_delta")
    assert events == ["Verified "] and stream.partial == "Verified "
    assert usage.callCount == 2 and usage.totalTokens == 13


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [{"index": True}, {"index": -1}, {"index": 0, "id": 4}])
async def test_invalid_tool_identity_is_explicit_failure(provider: Provider, bad: dict[str, object]) -> None:
    provider.replies = [[frame({"choices": [{"delta": {"tool_calls": [bad]}}]}), frame("[DONE]")]]

    async def emit(_kind: str, _text: object, _step: int) -> None:
        pass

    with pytest.raises((ValueError, TypeError)):
        await ModelStream(model(provider), emit, Usage()).call([HumanMessage(content="query")], tools=_tools())
