"""Controlled HTTP models cannot turn doTerminate into a fictitious SQL success."""

import json

import pytest
from test_model_protocol import Provider, frame, model

from app.agent.graph import RunContext, run_graph
from app.agent.streaming import ModelStream
from app.agent.tools import RunTools
from app.agent.types import ChatRequest, Usage
from app.services import database_tools

pytest_plugins = ["test_chat_api"]


def tool_reply(name: str, arguments: dict[str, object]) -> list[bytes]:
    return [frame({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": name,
              "function": {"name": name, "arguments": json.dumps(arguments)}}]}}]}), frame("[DONE]")]


@pytest.mark.parametrize("failed_statement", [False, True])
@pytest.mark.asyncio
async def test_termination_without_success_has_authoritative_unfinished_report(
    failed_statement: bool, provider: Provider, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(database_tools, "get_schema", lambda _user, _db: {"tables": []})
    executions: list[str] = []

    def execute(_user: int, _db: int, statement: str) -> dict[str, object]:
        executions.append(statement)
        return {"success": False, "error": "Unknown table missing_orders"}

    monkeypatch.setattr(database_tools, "execute_statement", execute)
    provider.replies = ([tool_reply("executeSql", {"db_id": 12, "statement": "SELECT * FROM missing_orders"})]
                        if failed_statement else [])
    provider.replies.append(tool_reply("doTerminate", {"reason": "All requested work completed"}))
    events: list[tuple[str, object]] = []

    async def emit(kind: str, content: object, _step: int) -> None:
        events.append((kind, content))

    request = ChatRequest(message="Query orders", dbConfigIds=[12], confirmedIntent="sql_query")
    usage = Usage()
    tools = RunTools(1, request)
    result = await run_graph(RunContext(request, [], "en", ModelStream(model(provider), emit, usage), tools, emit))
    assert "No database statement was successfully executed" in result["answer"]
    assert "was not completed" in result["answer"]
    assert "All requested work completed" not in result["answer"]
    assert len(provider.requests) == (2 if failed_statement else 1)
    assert len(executions) == (1 if failed_statement else 0)
    assert tools.statements_executed == 0
    assert events[-1] == ("summary", result["answer"])
    if failed_statement:
        assert "Unknown table missing_orders" in result["answer"]
