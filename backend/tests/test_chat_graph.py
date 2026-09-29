"""S07 graph behavior against the real HTTP model adapter."""

import json
import threading
from collections.abc import Iterator

import pytest
from test_model_protocol import Provider, frame, model

from app.agent.graph import RunContext, run_graph
from app.agent.streaming import ModelStream
from app.agent.tools import RunTools
from app.agent.types import ChatRequest, Usage
from app.core.errors import BusinessError


@pytest.fixture
def provider() -> Iterator[Provider]:
    service = Provider([])
    thread = threading.Thread(target=service.serve_forever, daemon=True)
    thread.start()
    yield service
    service.shutdown()
    service.server_close()
    thread.join(timeout=2)


def response(content: str) -> list[bytes]:
    return [frame({"choices": [{"delta": {"content": content}}]}),
            frame({"usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6}}),
            frame("[DONE]")]


@pytest.mark.asyncio
async def test_classification_and_simple_chat(provider: Provider) -> None:
    provider.replies = [
        response(json.dumps({"intent": "simple_chat", "confidence": 0.96,
                             "reasoning": "general", "needsClarification": False})),
        response("The answer is 42."),
    ]
    events: list[tuple[str, object, int]] = []

    async def emit(kind: str, content: object, step: int) -> None:
        events.append((kind, content, step))

    request = ChatRequest(message="What is 42?")
    usage = Usage()
    context = RunContext(request, [], "en", ModelStream(model(provider), emit, usage),
                         RunTools(7, request), emit)
    result = await run_graph(context)
    assert result["intent"] == "simple_chat"
    assert result["answer"] == "The answer is 42."
    assert [event[0] for event in events] == ["classifying", "classified", "routing", "thinking", "content"]
    assert usage.callCount == 2
    assert usage.totalTokens == 12


@pytest.mark.asyncio
async def test_low_confidence_clarifies_without_executing(provider: Provider) -> None:
    provider.replies = [response(json.dumps({"intent": "sql_query", "confidence": 0.4,
                                              "reasoning": "ambiguous", "needsClarification": False}))]
    events: list[str] = []

    async def emit(kind: str, _content: object, _step: int) -> None:
        events.append(kind)

    request = ChatRequest(message="Maybe query")
    context = RunContext(request, [], "en", ModelStream(model(provider), emit, Usage()),
                         RunTools(7, request), emit)
    result = await run_graph(context)
    assert result["clarification"] is not None
    assert events == ["classifying", "classified", "clarify"]
    assert len(provider.requests) == 1


@pytest.mark.asyncio
async def test_invalid_classification_does_not_route(provider: Provider) -> None:
    provider.replies = [response('{"intent":"execute_everything"}')]

    async def emit(_kind: str, _content: object, _step: int) -> None:
        pass

    request = ChatRequest(message="query")
    context = RunContext(request, [], "en", ModelStream(model(provider), emit, Usage()),
                         RunTools(7, request), emit)
    with pytest.raises(ValueError, match="Invalid intent classification"):
        await run_graph(context)


@pytest.mark.asyncio
async def test_confirmed_sql_reads_schema_then_executes(provider: Provider,
                                                        monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import database_tools

    calls: list[str] = []

    def schema(user_id: int, db_id: int) -> dict[str, object]:
        assert (user_id, db_id) == (7, 12)
        calls.append("schema")
        return {"tables": [{"name": "orders", "columns": [{"name": "id"}]}], "incomplete": False}

    def execute(user_id: int, db_id: int, statement: str) -> dict[str, object]:
        assert (user_id, db_id, statement) == (7, 12, "SELECT COUNT(*) FROM orders")
        calls.append("execute")
        return {"success": True, "rowCount": 1, "data": [{"count": 3}]}

    monkeypatch.setattr(database_tools, "get_schema", schema)
    monkeypatch.setattr(database_tools, "execute_statement", execute)
    provider.replies = [
        [frame({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_1",
             "function": {"name": "executeSql", "arguments": json.dumps({"db_id": 12,
                                                                      "statement": "SELECT COUNT(*) FROM orders"})}}]}}]}),
         frame("[DONE]")],
        response("There are 3 orders."),
    ]
    events: list[tuple[str, object]] = []

    async def emit(kind: str, content: object, _step: int) -> None:
        events.append((kind, content))

    request = ChatRequest(message="Count orders", dbConfigIds=[12], confirmedIntent="sql_query")
    context = RunContext(request, [], "en", ModelStream(model(provider), emit, Usage()),
                         RunTools(7, request), emit)
    result = await run_graph(context)
    assert calls == ["schema", "execute"]
    assert result["answer"] == "There are 3 orders."
    assert [event[0] for event in events] == ["routing", "step", "thinking", "step", "thinking", "summary"]
    first_messages = provider.requests[0]["messages"]
    assert isinstance(first_messages, list)
    assert "orders" in json.dumps(first_messages)
    next_messages = provider.requests[1]["messages"]
    assert isinstance(next_messages, list)
    assert any(message["role"] == "tool" and "count" in message["content"] for message in next_messages)


@pytest.mark.asyncio
async def test_confirmed_sql_still_requires_database(provider: Provider) -> None:
    events: list[str] = []

    async def emit(kind: str, _content: object, _step: int) -> None:
        events.append(kind)

    request = ChatRequest(message="Count orders", confirmedIntent="sql_query")
    context = RunContext(request, [], "en", ModelStream(model(provider), emit, Usage()),
                         RunTools(7, request), emit)
    result = await run_graph(context)
    assert result["clarification"] is not None
    assert events == ["clarify"]
    assert provider.requests == []


@pytest.mark.asyncio
async def test_successful_write_is_not_reexecuted(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import database_tools

    executions = 0

    def execute(_user_id: int, _db_id: int, _statement: str) -> dict[str, object]:
        nonlocal executions
        executions += 1
        return {"success": True, "affectedRows": 1, "message": "done"}

    monkeypatch.setattr(database_tools, "execute_statement", execute)
    tools = RunTools(7, ChatRequest(message="insert", dbConfigIds=[12]))
    assert "affectedRows" in await tools.execute(12, "INSERT INTO t VALUES (1)")
    with pytest.raises(BusinessError, match="already executed"):
        await tools.execute(12, "INSERT INTO t VALUES (1)")
    assert executions == 1


@pytest.mark.asyncio
async def test_sql_text_without_execution_is_rejected(provider: Provider,
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import database_tools

    monkeypatch.setattr(database_tools, "get_schema", lambda _user, _db: {"tables": []})
    provider.replies = [response("I think there are 100 rows.")]

    async def emit(_kind: str, _content: object, _step: int) -> None:
        pass

    request = ChatRequest(message="Count rows", dbConfigIds=[12], confirmedIntent="sql_query")
    context = RunContext(request, [], "en", ModelStream(model(provider), emit, Usage()),
                         RunTools(7, request), emit)
    with pytest.raises(RuntimeError, match="without executing"):
        await run_graph(context)


@pytest.mark.asyncio
async def test_terminate_summarizes_after_tool(provider: Provider,
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import database_tools

    monkeypatch.setattr(database_tools, "get_schema", lambda _user, _db: {"tables": []})
    monkeypatch.setattr(database_tools, "execute_statement", lambda _user, _db, _sql:
                        {"success": True, "rowCount": 1, "data": [{"value": 1}]})
    provider.replies = [
        [frame({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "query",
            "function": {"name": "executeSql", "arguments": '{"db_id":12,"statement":"SELECT 1"}'}}]}}]}),
         frame("[DONE]")],
        [frame({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "finish",
            "function": {"name": "doTerminate", "arguments": '{"reason":"Done"}'}}]}}]}),
         frame("[DONE]")],
        response("The value is 1."),
    ]
    events: list[tuple[str, object]] = []

    async def emit(kind: str, content: object, _step: int) -> None:
        events.append((kind, content))

    request = ChatRequest(message="Select one", dbConfigIds=[12], confirmedIntent="sql_query")
    context = RunContext(request, [], "en", ModelStream(model(provider), emit, Usage()),
                         RunTools(7, request), emit)
    result = await run_graph(context)
    assert result["answer"] == "The value is 1."
    assert [(kind, content) for kind, content in events if kind in ("summary_delta", "summary")] == [
        ("summary_delta", "The value is 1."), ("summary", "The value is 1."),
    ]
    assert len(provider.requests) == 3
