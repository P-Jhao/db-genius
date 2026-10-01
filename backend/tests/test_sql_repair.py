"""Repairable driver failures reach the model without hiding unsafe failures."""

import json
import sqlite3
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError, OperationalError
from test_model_protocol import Provider, frame, model

from app.adapters.cancellation import DatabaseWriteOutcomeUnknown
from app.adapters.safety import UnsafeStatement
from app.agent.cancellation import RunAborted
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


def call(statement: str, call_id: str) -> list[bytes]:
    return [frame({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": call_id,
             "function": {"name": "executeSql", "arguments": json.dumps({
                 "db_id": 12, "statement": statement})}}]}}]}), frame("[DONE]")]


def request() -> ChatRequest:
    return ChatRequest.model_validate({"message": "Fix the SQL and show the real result",
                                       "dbConfigIds": [12], "confirmedIntent": "sql_query"})


def sqlite_service(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    from app.services import database_tools

    target = tmp_path / "repair.sqlite"
    engine = create_engine(f"sqlite:///{target}")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE records (id INTEGER PRIMARY KEY, name TEXT)")
        connection.exec_driver_sql("INSERT INTO records VALUES (1, 'Ada')")

    monkeypatch.setattr(database_tools, "get_schema", lambda user_id, db_id: {
        "dbType": "sqlite", "tables": [{"name": "records", "columns": ["id", "name"]}]
    } if (user_id, db_id) == (7, 12) else None)

    def execute(user_id: int, db_id: int, statement: str) -> dict[str, object]:
        assert (user_id, db_id) == (7, 12)
        with engine.begin() as connection:
            result = connection.exec_driver_sql(statement)
            if result.returns_rows:
                rows = [dict(row._mapping) for row in result]
                return {"success": True, "rowCount": len(rows), "data": rows}
            return {"success": True, "affectedRows": result.rowcount}

    monkeypatch.setattr(database_tools, "execute_statement", execute)
    return target


async def run(provider: Provider) -> tuple[str, RunTools, list[tuple[str, object]]]:
    events: list[tuple[str, object]] = []

    async def emit(kind: str, content: object, _step: int) -> None:
        events.append((kind, content))

    chat_request = request()
    tools = RunTools(7, chat_request)
    context = RunContext(chat_request, [], "en", ModelStream(model(provider), emit, Usage()),
                         tools, emit)
    result = await run_graph(context)
    return result["answer"], tools, events


@pytest.mark.asyncio
async def test_model_repairs_missing_table_and_reads_actual_rows(
    provider: Provider, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    sqlite_service(monkeypatch, tmp_path)
    provider.replies = [call("SELECT name FROM recrods", "bad"),
                        call("SELECT name FROM records", "fixed"),
                        answer("Ada is present.")]
    result, tools, events = await run(provider)
    assert result == "Ada is present."
    assert tools.statements_executed == 1
    messages = provider.requests[1]["messages"]
    assert isinstance(messages, list)
    observations = [json.loads(message["content"]) for message in messages
                    if isinstance(message, dict) and message.get("role") == "tool" and
                    isinstance(message.get("content"), str)]
    assert any(observation.get("success") is False and
               "no such table: recrods" in observation.get("error", "")
               for observation in observations)
    assert any(kind == "step" and "no such table" in str(content) for kind, content in events)


@pytest.mark.asyncio
async def test_model_repairs_write_target_without_repeating_successful_write(
    provider: Provider, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    target = sqlite_service(monkeypatch, tmp_path)
    provider.replies = [call("INSERT INTO recrods VALUES (2, 'Eve')", "bad_write"),
                        call("INSERT INTO records VALUES (2, 'Eve')", "fixed_write"),
                        call("SELECT id, name FROM records WHERE id = 2", "verify"),
                        answer("Eve was inserted and verified.")]
    result, tools, _ = await run(provider)
    assert result == "Eve was inserted and verified."
    assert tools.statements_executed == 2
    assert tools.completed_write_count == 1
    with sqlite3.connect(target) as connection:
        assert connection.execute("SELECT id, name FROM records WHERE id = 2").fetchall() == [(2, "Eve")]
    with pytest.raises(BusinessError, match="already executed"):
        await tools.execute(12, "INSERT INTO records VALUES (2, 'Eve')")


@pytest.mark.asyncio
async def test_permissions_safety_and_system_errors_are_not_repairable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import database_tools

    tools = RunTools(7, request())
    with pytest.raises(BusinessError, match="not selected"):
        await tools.execute(99, "SELECT 1")
    monkeypatch.setattr(database_tools, "execute_statement", lambda *_args, **_kwargs:
                        (_ for _ in ()).throw(UnsafeStatement("DROP is forbidden")))
    with pytest.raises(UnsafeStatement):
        await tools.execute(12, "DROP TABLE records")
    monkeypatch.setattr(database_tools, "execute_statement", lambda *_args, **_kwargs:
                        (_ for _ in ()).throw(RuntimeError("driver initialization failed")))
    with pytest.raises(RuntimeError, match="driver initialization failed"):
        await tools.execute(12, "SELECT 1")
    assert tools.statements_executed == 0


@pytest.mark.asyncio
async def test_connection_loss_integrity_and_unknown_write_still_abort(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from app.services import database_tools

    target = sqlite_service(monkeypatch, tmp_path)
    tools = RunTools(7, request())
    with pytest.raises(IntegrityError):
        await tools.execute(12, "INSERT INTO records VALUES (1, 'duplicate')")
    assert tools.statements_executed == 0
    with sqlite3.connect(target) as connection:
        assert connection.execute("SELECT COUNT(*) FROM records").fetchone() == (1,)

    def connection_lost(_user_id: int, _db_id: int, _statement: str) -> dict[str, object]:
        original = sqlite3.OperationalError("no such table: records")
        raise OperationalError("SELECT * FROM records", {}, original, connection_invalidated=True)

    monkeypatch.setattr(database_tools, "execute_statement", connection_lost)
    with pytest.raises(OperationalError):
        await tools.execute(12, "SELECT * FROM records")

    def system_database_error(_user_id: int, _db_id: int, _statement: str) -> dict[str, object]:
        original = sqlite3.OperationalError("no such table: db_configs")
        raise OperationalError("SELECT * FROM db_configs", {}, original)

    monkeypatch.setattr(database_tools, "execute_statement", system_database_error)
    with pytest.raises(OperationalError):
        await tools.execute(12, "SELECT * FROM records")
    monkeypatch.setattr(database_tools, "execute_statement", lambda *_args, **_kwargs:
                        (_ for _ in ()).throw(DatabaseWriteOutcomeUnknown("commit uncertain")))
    with pytest.raises(RunAborted, match="write_outcome_unknown"):
        await tools.execute(12, "INSERT INTO records VALUES (2, 'Eve')")
