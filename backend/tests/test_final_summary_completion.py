"""Controlled replay of the observed partial report, without database execution."""

import pytest
from langchain_core.messages import HumanMessage, ToolMessage
from test_model_protocol import Provider, frame, model

from app.agent.graph import RunContext
from app.agent.graph_sql import SQLNodes
from app.agent.model import CompatibleChatModel
from app.agent.streaming import ModelStream
from app.agent.tools import RunTools
from app.agent.types import ChatRequest, Usage

pytest_plugins = ["test_model_protocol"]

PARTIAL = "## 已完成的工"


def reply(content: str, reason: str | None, calls: bool = False) -> list[bytes]:
    delta: dict[str, object] = {"content": content}
    if calls:
        delta["tool_calls"] = [{"index": 0, "id": "unexpected",
                                "function": {"name": "executeSql", "arguments":
                                             '{"db_id": 12, "statement": "INSERT INTO t VALUES (2)"}'}}]
    packets = [frame({"choices": [{"delta": delta}]})]
    if reason is not None:
        packets.append(frame({"choices": [{"delta": {}, "finish_reason": reason}]}))
    return [*packets, frame({"usage": {"prompt_tokens": 11, "completion_tokens": 7,
                                      "total_tokens": 18}}), frame("[DONE]")]


@pytest.mark.asyncio
@pytest.mark.parametrize(("content", "reason", "calls"), [
    (PARTIAL, None, False),
    ("The verified operation succeeded, but the report ends here", "length", False),
    ("", "tool_calls", True),
    (PARTIAL + '<｜DSML｜invoke name="doTerminate">unclosed', "stop", False),
])
async def test_invalid_final_report_is_not_marked_complete(
    provider: Provider, content: str, reason: str | None, calls: bool,
) -> None:
    provider.replies = [reply(content, reason, calls)]
    events: list[tuple[str, object]] = []

    async def emit(kind: str, value: object, _step: int) -> None:
        events.append((kind, value))

    request = ChatRequest(message="Report the already verified insert", dbConfigIds=[12],
                          confirmedIntent="sql_query")
    tools = RunTools(7, request)
    tools.statements_executed = 1
    tools.statements_attempted = 1
    tools.terminated = True
    usage = Usage()
    context = RunContext(request, [], "en", ModelStream(model(provider), emit, usage), tools, emit)
    state = {"intent": "sql_query", "step": 1, "messages": [
        HumanMessage(content=request.message),
        ToolMessage(content='{"success": true, "affectedRows": 1}', tool_call_id="prior-write"),
    ]}
    with pytest.raises(RuntimeError, match="(?i)report|summary|completion"):
        await SQLNodes(context, 20).summarize(state)
    assert not any(kind == "summary" for kind, _ in events)
    assert usage.callCount == 1 and usage.totalTokens == 18
    assert len(provider.requests) == 1 and "tools" not in provider.requests[0]
    assert tools.statements_executed == 1


def test_terminal_finish_reason_survives_empty_delta() -> None:
    chunks = CompatibleChatModel._parse_packet(
        '{"choices":[{"delta":{},"finish_reason":"length"}]}'
    )
    assert len(chunks) == 1
    assert chunks[0].message.response_metadata["finish_reason"] == "length"
