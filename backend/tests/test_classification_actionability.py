"""Classifier input and routing through the real graph and a controlled HTTP model."""

import json
import threading
from collections.abc import Iterator

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from test_model_protocol import Provider, frame, model

from app.agent.final_report import REPORT_CONTRACT
from app.agent.graph import RunContext, run_graph
from app.agent.report_rules import SQL_EVIDENCE_RULE
from app.agent.streaming import ModelStream
from app.agent.tools import RunTools
from app.agent.types import ChatRequest, Usage
from app.core.errors import BusinessError
from app.services import database_tools


@pytest.fixture
def provider() -> Iterator[Provider]:
    service = Provider([])
    thread = threading.Thread(target=service.serve_forever, daemon=True)
    thread.start()
    yield service
    service.shutdown()
    service.server_close()
    thread.join(timeout=2)


def answer(content: str) -> list[bytes]:
    return [frame({"choices": [{"delta": {"content": content}}]}), frame("[DONE]")]


def classify(intent: str, clarify: bool) -> list[bytes]:
    return answer(json.dumps({"intent": intent, "confidence": 0.98,
                              "reasoning": "Task details reviewed", "needsClarification": clarify}))


def call(name: str, args: dict[str, object]) -> list[bytes]:
    return [frame({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": name,
             "function": {"name": name, "arguments": json.dumps(args)}}]}}]}), frame("[DONE]")]


async def run(provider: Provider, request: ChatRequest, locale: str,
              history: list[HumanMessage | AIMessage | SystemMessage] | None = None,
              ) -> tuple[dict[str, object], list[tuple[str, object]], RunTools]:
    events: list[tuple[str, object]] = []

    async def emit(kind: str, content: object, _step: int) -> None:
        events.append((kind, content))

    tools = RunTools(7, request)
    result = await run_graph(RunContext(request, history or [], locale,
                                        ModelStream(model(provider), emit, Usage()), tools, emit))
    return result, events, tools


@pytest.mark.parametrize(("locale", "message", "empty_marker", "actionability"), [
    ("en", "Handle this data", "(no conversation history)", "concrete operation"),
    ("zh-CN", "处理一下这份数据。", "（无历史对话）", "具体操作"),
])
@pytest.mark.asyncio
async def test_unresolved_task_clarifies_without_tools(
    provider: Provider, locale: str, message: str, empty_marker: str, actionability: str,
) -> None:
    provider.replies = [classify("workflow", True)]
    request = ChatRequest.model_validate({"message": message, "dbConfigIds": [12]})
    result, events, tools = await run(provider, request, locale)
    assert result["clarification"] is not None
    assert [kind for kind, _ in events] == ["classifying", "classified", "clarify"]
    assert set(events[1][1]) == {"intent", "confidence", "reasoning", "needsClarification"}
    assert tools.statements_attempted == 0 and len(provider.requests) == 1
    messages = provider.requests[0]["messages"]
    assert isinstance(messages, list) and [item["role"] for item in messages] == ["system", "user"]
    assert actionability in str(messages[0]["content"])
    assert str(messages[1]["content"]).count(empty_marker) == 1
    assert str(messages[1]["content"]).count(message) == 1


@pytest.mark.asyncio
async def test_explicit_sql_without_confirmation_routes_and_executes(
    provider: Provider, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(database_tools, "get_schema", lambda _user, _db: {
        "dbType": "sqlite", "databaseName": "test", "tables": [],
    })
    statements: list[str] = []

    def execute(_user: int, _db: int, statement: str) -> dict[str, object]:
        statements.append(statement)
        return {"success": True, "rowCount": 1, "data": [{"n": 3}]}

    monkeypatch.setattr(database_tools, "execute_statement", execute)
    provider.replies = [classify("sql_query", False),
                        call("executeSql", {"db_id": 12, "statement": "SELECT 3 AS n"}),
                        answer("The result is 3.")]
    request = ChatRequest.model_validate({"message": "Run SELECT 3 AS n", "dbConfigIds": [12]})
    result, events, tools = await run(provider, request, "en")
    assert result["answer"] == "The result is 3."
    assert result["clarification"] is None and statements == ["SELECT 3 AS n"]
    assert tools.statements_executed == 1 and len(provider.requests) == 3
    assert any(kind == "classified" for kind, _ in events)
    final_messages = provider.requests[-1]["messages"]
    assert isinstance(final_messages, list)
    assert any(item["role"] == "system" and item["content"] == SQL_EVIDENCE_RULE
               for item in final_messages)
    observations = [json.loads(item["content"]) for item in final_messages
                    if item["role"] == "tool" and item["tool_call_id"] == "executeSql"]
    assert observations == [{"success": True, "rowCount": 1, "data": [{"n": 3}]}]
    assert all(item["content"] != REPORT_CONTRACT for item in final_messages)
    assert "tools" in provider.requests[-1]
    assert events[-1] == ("summary", "The result is 3.")
    assert not any(kind == "summary_delta" for kind, _ in events)


@pytest.mark.asyncio
async def test_history_and_summary_are_sent_once_and_ground_followup(
    provider: Provider, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(database_tools, "get_schema", lambda _user, _db: {"tables": []})
    monkeypatch.setattr(database_tools, "execute_statement", lambda _user, _db, _sql:
                        {"success": True, "rowCount": 1, "data": [{"n": 2}]})
    provider.replies = [classify("sql_query", False),
                        call("executeSql", {"db_id": 12, "statement": "SELECT 2 AS n"}),
                        answer("Two paid orders remain.")]
    history = [SystemMessage(content="Previous conversation summary:\nUse the orders table."),
               HumanMessage(content="Count paid orders in orders."),
               AIMessage(content="Three paid orders were found.")]
    request = ChatRequest.model_validate({"message": "Now use the same filter", "dbConfigIds": [12]})
    result, _, tools = await run(provider, request, "en", history)
    messages = provider.requests[0]["messages"]
    assert isinstance(messages, list) and len(messages) == 2
    user = str(messages[1]["content"])
    for text in ("Previous conversation summary:", "Count paid orders in orders.",
                 "Three paid orders were found.", "Now use the same filter"):
        assert user.count(text) == 1
    assert "summary:" in user and "user:" in user and "assistant:" in user
    assert result["answer"] == "Two paid orders remain." and tools.statements_executed == 1


@pytest.mark.asyncio
async def test_explicit_workflow_without_attachment_remains_available(
    provider: Provider, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(database_tools, "get_schema", lambda _user, _db: {
        "dbType": "sqlite", "databaseName": "test", "tables": [],
    })
    monkeypatch.setattr(database_tools, "execute_statement", lambda _user, _db, _sql:
                        {"success": True, "rowCount": 1, "data": [{"n": 1}]})
    provider.replies = [classify("workflow", False),
                        call("executeSql", {"db_id": 12, "statement": "SELECT 1 AS n"}),
                        answer("The two-step database review is complete.")]
    request = ChatRequest.model_validate({"message": "Inspect the orders table, then count its rows",
                                          "dbConfigIds": [12]})
    result, events, tools = await run(provider, request, "en")
    assert result["intent"] == "workflow" and result["clarification"] is None
    assert tools.statements_executed == 1 and len(provider.requests) == 3
    assert "routing" in [kind for kind, _ in events]


@pytest.mark.asyncio
async def test_attachment_alone_does_not_supply_goal(provider: Provider) -> None:
    provider.replies = [classify("workflow", True)]
    request = ChatRequest.model_validate({"message": "Please work on the attached data",
                                          "dbConfigIds": [12], "fileIds": [30]})
    result, events, tools = await run(provider, request, "en")
    assert result["clarification"] is not None and tools.statements_attempted == 0
    assert [kind for kind, _ in events] == ["classifying", "classified", "clarify"]


@pytest.mark.asyncio
async def test_simple_chat_without_confirmation_uses_chat_branch(provider: Provider) -> None:
    provider.replies = [classify("simple_chat", False), answer("Hello.")]
    request = ChatRequest.model_validate({"message": "Hello"})
    result, events, tools = await run(provider, request, "en")
    assert result["answer"] == "Hello." and result["intent"] == "simple_chat"
    assert tools.statements_attempted == 0 and len(provider.requests) == 2
    assert "content" in [kind for kind, _ in events]


@pytest.mark.asyncio
async def test_confirmed_intent_still_enforces_selected_database(
    provider: Provider, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(database_tools, "get_schema", lambda _user, _db: {"tables": []})
    provider.replies = [call("executeSql", {"db_id": 99, "statement": "SELECT 1"})]
    request = ChatRequest.model_validate({"message": "Read the selected database", "dbConfigIds": [12],
                                          "confirmedIntent": "sql_query"})
    with pytest.raises(BusinessError, match="not selected"):
        await run(provider, request, "en")
    assert len(provider.requests) == 1
