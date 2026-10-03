"""S11 compare graph with HTTP model replies and deterministic schema diffs."""

import json
import sqlite3
import threading
from collections.abc import Iterator
from pathlib import Path

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


def answer(content: str) -> list[bytes]:
    return [frame({"choices": [{"delta": {"content": content}}]}), frame("[DONE]")]


def call(name: str, arguments: dict[str, object], call_id: str) -> list[bytes]:
    return [frame({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": call_id,
             "function": {"name": name, "arguments": json.dumps(arguments)}}]}}]}), frame("[DONE]")]


def request(*, classified: bool = False) -> ChatRequest:
    return ChatRequest.model_validate({"message": "Compare pre and test", "preDbConfigId": 12,
                                       "testDbConfigId": 13, "confirmedIntent": None if classified else "db_compare"})


def sqlite_schemas(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                   *, partial: bool = False, cross_type: bool = False) -> None:
    from app.services import database_tools

    pre = tmp_path / "pre.sqlite"
    test = tmp_path / "test.sqlite"
    with sqlite3.connect(pre) as connection:
        connection.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
        connection.execute("CREATE TABLE retired (id INTEGER)")
    with sqlite3.connect(test) as connection:
        connection.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name VARCHAR(100), email TEXT)")
        connection.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY)")

    def schema(user_id: int, db_id: int) -> dict[str, object]:
        assert user_id == 7
        if db_id not in (12, 13):
            raise AssertionError("Unexpected database ID")
        path = pre if db_id == 12 else test
        tables: list[dict[str, object]] = []
        with sqlite3.connect(path) as connection:
            names = [row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
            for name in names:
                columns = [{"name": column[1], "type": column[2],
                            "nullable": not bool(column[3]), "primaryKey": bool(column[5]),
                            "comment": None}
                           for column in connection.execute(f"PRAGMA table_info({name})")]
                tables.append({"name": name, "comment": None, "rowCount": None,
                               "columns": columns, "indexes": []})
        return {"dbType": ("mysql" if db_id == 12 else "postgresql") if cross_type else "sqlite",
                "databaseName": "pre" if db_id == 12 else "test", "host": "local", "port": 0,
                "tables": tables, "incomplete": partial and db_id == 12,
                "errorMessage": "One pre table could not be read" if partial and db_id == 12 else None}

    monkeypatch.setattr(database_tools, "get_schema", schema)


async def run(provider: Provider, chat_request: ChatRequest) -> tuple[str, list[tuple[str, object]]]:
    events: list[tuple[str, object]] = []

    async def emit(kind: str, content: object, _step: int) -> None:
        events.append((kind, content))

    context = RunContext(chat_request, [], "en", ModelStream(model(provider), emit, Usage()),
                         RunTools(7, chat_request), emit)
    result = await run_graph(context)
    return result["answer"], events


@pytest.mark.asyncio
@pytest.mark.parametrize("classified", [False, True])
async def test_compare_pre_to_test_with_real_diff(
    provider: Provider, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, classified: bool,
) -> None:
    sqlite_schemas(monkeypatch, tmp_path)
    provider.replies = [call("doTerminate", {"reason": "report ready"}, "terminate"),
                        answer(json.dumps({"report": "pre→test: create orders, remove retired, add users.email.",
                                           "complete": True}))]
    if classified:
        provider.replies.insert(0, answer(json.dumps({"intent": "db_compare", "confidence": 0.99,
                                                      "reasoning": "schemas", "needsClarification": False})))
    result, events = await run(provider, request(classified=classified))
    assert result == "pre→test: create orders, remove retired, add users.email."
    steps = [content for kind, content in events if kind == "step"]
    assert any("\"newTables\"" in str(content) and "orders" in str(content) for content in steps)
    assert any("retired" in str(content) and "ADD_COLUMN" in str(content) for content in steps)
    assert any("MODIFY_COLUMN" in str(content) and "MODIFY_NULLABLE" in str(content)
               for content in steps)
    assert "Pre: 12" in json.dumps(provider.requests[1 if classified else 0])


@pytest.mark.asyncio
async def test_reversed_direction_is_rejected(
    provider: Provider, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    sqlite_schemas(monkeypatch, tmp_path)
    provider.replies = [call("compareDatabases", {"pre_id": 13, "test_id": 12}, "reversed")]
    with pytest.raises(BusinessError, match="direction differs"):
        await run(provider, request())


@pytest.mark.asyncio
async def test_first_answer_without_tool_receives_completed_diff(
    provider: Provider, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    sqlite_schemas(monkeypatch, tmp_path)
    provider.replies = [answer("pre→test: orders is new and retired is absent.")]
    result, _ = await run(provider, request())
    assert result == "pre→test: orders is new and retired is absent."
    assert len(provider.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("partial,cross_type,expected", [
    (True, False, "comparison is incomplete"),
    (False, True, "Cross-engine comparison"),
])
async def test_limited_compare_uses_factual_safe_summary(
    provider: Provider, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    partial: bool, cross_type: bool, expected: str,
) -> None:
    sqlite_schemas(monkeypatch, tmp_path, partial=partial, cross_type=cross_type)
    provider.replies = [call("compareDatabases", {"pre_id": 12, "test_id": 13}, "compare")]
    result, events = await run(provider, request())
    assert expected in result
    assert "No directly executable migration SQL" in result
    assert "orders" in result
    assert not any(kind == "summary_delta" for kind, _ in events)
    assert len(provider.requests) == 0


@pytest.mark.asyncio
async def test_comparison_never_executes_migration_write(provider: Provider,
                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    from test_compare_risk_guidance import report

    from app.models import DbConfig
    from app.services import database_tools, schema_diff

    monkeypatch.setattr(schema_diff, "compare_databases", lambda *_args: report())
    monkeypatch.setattr(database_tools, "_ready_config", lambda _user, _db: DbConfig(db_type="postgresql"))
    monkeypatch.setattr(database_tools, "execute_statement", lambda *_args, **_kwargs:
                        pytest.fail("Comparison write reached database service"))
    provider.replies = [call("executeSql", {"db_id": 12,
                                           "statement": "CREATE TABLE unwanted (id INTEGER)"}, "write")]
    with pytest.raises(BusinessError, match="cannot execute migration writes"):
        await run(provider, request())
