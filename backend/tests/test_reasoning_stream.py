"""Provider reasoning visibility is independent of decision body visibility."""

import json
import threading

import pytest
from langchain_core.messages import HumanMessage
from test_model_protocol import Provider, frame, model

from app.agent.cancellation import RunAborted
from app.agent.streaming import ModelStream
from app.agent.types import Usage

pytest_plugins = ["test_model_protocol"]


def fragments(content: str = "decision") -> list[bytes]:
    return [frame({"usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6}}),
            frame({"choices": [{"delta": {"reasoning_content": "think "}}]}),
            frame({"choices": [{"delta": {"reasoning_content": "again", "content": content}}]}),
            frame("[DONE]")]


@pytest.mark.parametrize(("event", "visible", "expected"), [
    (None, True, ["reasoning", "reasoning"]),
    (None, None, []), ("content", False, ["content"]),
    ("content", None, ["reasoning", "reasoning", "content"]),
])
@pytest.mark.asyncio
async def test_visibility_compatibility_and_fragment_aggregation(
    provider: Provider, event: str | None, visible: bool | None, expected: list[str],
) -> None:
    provider.replies = [fragments()]
    emitted: list[tuple[str, object, int]] = []

    async def emit(kind: str, value: object, step: int) -> None:
        emitted.append((kind, value, step))

    usage = Usage()
    stream = ModelStream(model(provider), emit, usage)
    response = await stream.call([HumanMessage(content="plan")], step=2,
                                 event=event, emit_reasoning=visible)
    assert [kind for kind, _, _ in emitted] == expected
    assert all(step == 2 for _, _, step in emitted)
    assert response.content == "decision" and response.additional_kwargs["reasoning_content"] == "think again"
    assert usage.callCount == stream.call_id == 1 and usage.totalTokens == 6
    assert provider.requests[0]["temperature"] == 0.7 and "thinking" not in provider.requests[0]


@pytest.mark.parametrize("contract", ["classification", "task_goal"])
@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.asyncio
async def test_internal_contracts_never_emit_or_return_private_reasoning(
    provider: Provider, contract: str, enabled: bool,
) -> None:
    wire = json.dumps({"reasoning": "internal decision", "text": "<｜DSML｜invoke>"})
    provider.replies = [fragments(wire)]
    emitted: list[str] = []

    async def emit(kind: str, _value: object, _step: int) -> None:
        emitted.append(kind)

    stream = ModelStream(model(provider), emit, Usage(), chat_json_object=enabled)
    if contract == "classification":
        response = await stream.call([], classification=True, emit_reasoning=True)
    else:
        response = await stream.call([], json_contract="task_goal", emit_reasoning=True)
    assert emitted == [] and stream.reasoning == ""
    assert response.content == wire and "reasoning_content" not in response.additional_kwargs
    payload = provider.requests[0]
    assert payload["thinking"] == {"type": "disabled"} and "temperature" not in payload
    assert ("response_format" in payload) == enabled
    assert "tools" not in payload


@pytest.mark.asyncio
async def test_invalid_contract_and_precancel_do_not_call_or_charge(provider: Provider) -> None:
    async def emit(_kind: str, _value: object, _step: int) -> None:
        raise AssertionError("No event is expected")

    cancel = threading.Event()
    usage = Usage()
    stream = ModelStream(model(provider), emit, usage, cancel)
    with pytest.raises(ValueError):
        await stream.call([], classification=True, json_contract="task_goal")
    cancel.set()
    with pytest.raises(RunAborted):
        await stream.call([], event=None, emit_reasoning=True)
    assert provider.requests == [] and usage.callCount == stream.call_id == 0


@pytest.mark.asyncio
async def test_cancel_after_visible_reasoning_preserves_received_usage(provider: Provider) -> None:
    provider.replies = [fragments()]
    cancel = threading.Event()
    emitted: list[str] = []

    async def emit(kind: str, value: object, _step: int) -> None:
        assert kind == "reasoning" and isinstance(value, str)
        emitted.append(value)
        cancel.set()

    usage = Usage()
    stream = ModelStream(model(provider), emit, usage, cancel)
    with pytest.raises(RunAborted):
        await stream.call([], event=None, emit_reasoning=True)
    assert emitted == ["think "] and stream.reasoning == "think "
    assert usage.callCount == 1 and usage.totalTokens == 6


@pytest.mark.asyncio
async def test_internal_goal_rejects_unsolicited_tools_without_emitting(provider: Provider) -> None:
    provider.replies = [[
        frame({"usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6}}),
        frame({"choices": [{"delta": {"content": "{}", "reasoning_content": "private",
            "tool_calls": [{"index": 0, "id": "forbidden", "function": {
                "name": "executeSql", "arguments": "{}"}}]}}]}), frame("[DONE]"),
    ]]

    async def emit(_kind: str, _value: object, _step: int) -> None:
        raise AssertionError("Internal goal output cannot be emitted")

    usage = Usage()
    with pytest.raises(ValueError, match="Internal JSON analysis cannot return tool calls"):
        await ModelStream(model(provider), emit, usage).call([], json_contract="task_goal")
    assert usage.callCount == 1 and usage.totalTokens == 6
