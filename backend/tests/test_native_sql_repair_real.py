"""Actual native diagnostics/rollback and terminal result-loss injection through HTTP."""

import json
import threading
from uuid import uuid4

import pytest
from native_database_fixtures import oracle_target as oracle_fixture
from native_database_fixtures import sqlserver_target as sqlserver_fixture
from native_database_fixtures import wait_oracle_ddl
from sqlalchemy import event
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import DBAPIError
from test_model_protocol import Provider, model
from test_native_sql_repair_policy import native_error
from test_native_workflow_real import fixture_target
from test_sql_repair import answer
from test_sql_repair import provider as provider_fixture
from test_workflow_integration import DB_ID, USER_ID, install_target, tool_reply

from app.adapters import get_adapter
from app.adapters.cancellation import DatabaseWriteOutcomeUnknown
from app.adapters.types import QueryResult
from app.agent.cancellation import RunAborted
from app.agent.graph import RunContext, run_graph
from app.agent.streaming import ModelStream
from app.agent.tools import RunTools
from app.agent.types import ChatRequest, Usage
from app.services import database_tools

oracle_target = oracle_fixture
sqlserver_target = sqlserver_fixture
provider = provider_fixture


def call(statement: str, call_id: str) -> list[bytes]:
    return tool_reply("executeSql", {"db_id": DB_ID, "statement": statement}, call_id)


async def run(provider: Provider) -> tuple[str, RunTools, list[tuple[str, object]]]:
    events: list[tuple[str, object]] = []
    async def emit(kind: str, content: object, _step: int) -> None:
        events.append((kind, content))
    request = ChatRequest.model_validate({"message": "Fix the SQL and show the actual result",
                                          "dbConfigIds": [DB_ID], "confirmedIntent": "sql_query"})
    tools = RunTools(USER_ID, request)
    context = RunContext(request, [], "en", ModelStream(model(provider), emit, Usage()), tools, emit)
    result = await run_graph(context)
    return result["answer"], tools, events


@pytest.mark.asyncio
@pytest.mark.parametrize("db_type,error_kind,code", [
    ("oracle", "column", 904), ("oracle", "table", 942), ("oracle", "syntax", 3047),
    ("oracle", "comma", 936), ("oracle", "alias", 923), ("oracle", "order", 904),
    ("sqlserver", "column", 207), ("sqlserver", "table", 208), ("sqlserver", "syntax", 102),
])
async def test_actual_native_select_error_is_rolled_back_and_model_corrected(
    db_type: str, error_kind: str, code: int, request: pytest.FixtureRequest,
    provider: Provider, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, engine = fixture_target(request, db_type)
    table = "repair_" + uuid4().hex[:12]
    fixed = f'SELECT name AS "value" FROM {table} WHERE id=1'
    bad = {"column": f"SELECT missing FROM {table}", "table": f"SELECT name FROM absent_{table}",
           "syntax": f"SELECT name FROM {table} LIMIT 1", "comma": f"SELECT name, FROM {table}",
           "alias": f"SELECT name AS 'x' FROM {table}",
           "order": f"SELECT GROUP_CONCAT(name ORDER BY name) FROM {table}",
           "terminator": f"SELECT name FROM {table};"}[error_kind]
    executed: list[str] = []
    bad_connections: list[Connection] = []
    rollbacks: set[Connection] = set()
    observed: list[dict[str, object]] = []
    original_execute = database_tools.execute_statement
    def before(connection, _cursor, statement, _parameters, _context, _many):
        if statement == bad:
            bad_connections.append(connection)
    def rolled_back(connection: Connection) -> None:
        rollbacks.add(connection)
    def execute(user: int, db: int, statement: str, cancel_event: threading.Event | None = None) -> QueryResult:
        executed.append(statement)
        try:
            return original_execute(user, db, statement, cancel_event)
        except DBAPIError as error:
            assert error.statement == bad and not error.connection_invalidated
            assert not getattr(error, "__notes__", [])
            assert len(bad_connections) == 1 and bad_connections[0] in rollbacks
            detail = error.orig.args[0]
            actual_code = getattr(detail, "code", None) if db_type == "oracle" else detail
            assert actual_code == code
            observed.append({"driver_type": type(error.orig).__module__ + "." + type(error.orig).__name__,
                             "code": actual_code, "offset": getattr(detail, "offset", None),
                             "full_code": getattr(detail, "full_code", None), "rollback_event": True})
            raise
    event.listen(Engine, "before_cursor_execute", before)
    event.listen(Engine, "rollback", rolled_back)
    created = False
    try:
        text_type = "VARCHAR2(20)" if db_type == "oracle" else "VARCHAR(20)"
        with engine.begin() as connection:
            connection.exec_driver_sql(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY,name {text_type})")
            created = True
            connection.exec_driver_sql(f"INSERT INTO {table} VALUES (1,'Ada')")
        if db_type == "oracle":
            wait_oracle_ddl(engine, [table.upper()])
        install_target(monkeypatch, config)
        monkeypatch.setattr(database_tools, "execute_statement", execute)
        provider.replies = [call(bad, "bad"), call(fixed, "fixed"), answer("Ada is present.")]
        result, tools, _events = await run(provider)
        assert result == "Ada is present." and len(provider.requests) == 3
        assert executed == [bad, fixed] and len(observed) == 1
        assert tools.statements_executed == 1 and tools.completed_write_count == 0
        values = [json.loads(message["content"]) for message in provider.requests[1]["messages"]
                  if message.get("role") == "tool"]
        assert any(value.get("success") is False and value.get("errorCode") == code for value in values)
        assert any(message.get("role") == "tool" and '"value": "Ada"' in message.get("content", "")
                   for message in provider.requests[2]["messages"])
        with engine.connect() as connection:
            assert [tuple(row) for row in connection.exec_driver_sql(f"SELECT id,name FROM {table}")] == [(1, "Ada")]
        print("Actual native repair diagnostic:", observed[0])
    finally:
        event.remove(Engine, "before_cursor_execute", before)
        event.remove(Engine, "rollback", rolled_back)
        if created:
            with engine.begin() as connection:
                connection.exec_driver_sql(f"DROP TABLE {table}" + (" PURGE" if db_type == "oracle" else ""))


@pytest.mark.asyncio
@pytest.mark.parametrize("db_type", ["oracle", "sqlserver"])
async def test_actual_committed_write_with_injected_lost_result_is_not_replayed(
    db_type: str, request: pytest.FixtureRequest, provider: Provider, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, engine = fixture_target(request, db_type)
    table = "unknown_" + uuid4().hex[:12]
    statement = f"INSERT INTO {table} VALUES (1)"
    executions: list[str] = []
    original_execute = database_tools.execute_statement
    def execute(user: int, db: int, sql: str, cancel_event: threading.Event | None = None) -> QueryResult:
        executions.append(sql)
        assert original_execute(user, db, sql, cancel_event)["success"] is True
        raise DatabaseWriteOutcomeUnknown("Injected result loss after the actual committed write")
    created = False
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)")
        created = True
        install_target(monkeypatch, config)
        monkeypatch.setattr(database_tools, "execute_statement", execute)
        provider.replies = [call(statement, "write"), call(statement, "must_not_repeat")]
        with pytest.raises(RunAborted, match="write_outcome_unknown"):
            await run(provider)
        assert executions == [statement] and len(provider.requests) == 1
        with engine.connect() as connection:
            assert connection.exec_driver_sql(f"SELECT COUNT(*) FROM {table}").scalar_one() == 1
    finally:
        if created:
            with engine.begin() as connection:
                connection.exec_driver_sql(f"DROP TABLE {table}" + (" PURGE" if db_type == "oracle" else ""))


@pytest.mark.asyncio
async def test_actual_oracle_sequence_advance_then_known_error_cannot_reach_repair(
    oracle_target, provider: Provider, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, engine = oracle_target
    sequence = "unknown_seq_" + uuid4().hex[:12]
    statement = f'SELECT {sequence}."NEXTVAL" FROM DUAL'
    adapter = get_adapter("oracle")
    original_json = adapter._json_value
    converted: list[object] = []
    def fail_after_read(value: object) -> object:
        converted.append(value)
        raise native_error("oracle", 942, statement)
    created = False
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(f"CREATE SEQUENCE {sequence} NOCACHE")
        created = True
        install_target(monkeypatch, config)
        monkeypatch.setattr(adapter, "_json_value", fail_after_read)
        provider.replies = [call(statement, "advance"), call(statement, "must_not_repeat")]
        with pytest.raises(RunAborted, match="write_outcome_unknown"):
            await run(provider)
        assert converted == [1] and len(provider.requests) == 1
        monkeypatch.setattr(adapter, "_json_value", original_json)
        with engine.connect() as connection:
            assert connection.exec_driver_sql(
                "SELECT last_number FROM user_sequences WHERE sequence_name=:name",
                {"name": sequence.upper()},
            ).scalar_one() == 2
    finally:
        if created:
            with engine.begin() as connection:
                connection.exec_driver_sql(f"DROP SEQUENCE {sequence}")


@pytest.mark.asyncio
async def test_actual_oracle_function_missing_table_after_sequence_is_not_a_parse_retry(
    oracle_target, provider: Provider, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, engine = oracle_target
    suffix = uuid4().hex[:12]
    sequence, function = "hidden_seq_" + suffix, "hidden_fn_" + suffix
    statement = f"SELECT {function}() FROM DUAL"
    created: list[str] = []
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(f"CREATE SEQUENCE {sequence} NOCACHE")
            created.append("sequence")
            connection.exec_driver_sql(
                f"CREATE FUNCTION {function} RETURN NUMBER AS value NUMBER; BEGIN "
                f"SELECT {sequence}.NEXTVAL INTO value FROM DUAL; "
                f"EXECUTE IMMEDIATE 'SELECT COUNT(*) FROM absent_{suffix}' INTO value; RETURN value; END;"
            )
            created.append("function")
        install_target(monkeypatch, config)
        provider.replies = [call(statement, "function"), call(statement, "must_not_repeat")]
        with pytest.raises(DBAPIError) as caught:
            await run(provider)
        detail = caught.value.orig.args[0]
        assert getattr(detail, "code", None) == 942
        assert getattr(detail, "offset", None) > 0 and "ORA-06512:" in str(caught.value.orig)
        assert len(provider.requests) == 1
        with engine.connect() as connection:
            assert connection.exec_driver_sql(
                "SELECT last_number FROM user_sequences WHERE sequence_name=:name",
                {"name": sequence.upper()},
            ).scalar_one() == 2
        print("Actual Oracle function failure: code942/positive offset/stack; sequence advanced once; no model retry")
    finally:
        with engine.begin() as connection:
            if "function" in created:
                connection.exec_driver_sql(f"DROP FUNCTION {function}")
            if "sequence" in created:
                connection.exec_driver_sql(f"DROP SEQUENCE {sequence}")


@pytest.mark.asyncio
async def test_actual_oracle_semicolon_is_a_success_not_a_diagnostic(
    oracle_target, provider: Provider, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, _engine = oracle_target
    install_target(monkeypatch, config)
    provider.replies = [call("SELECT 1 AS value FROM DUAL;", "valid"), answer("One is present.")]
    result, tools, _events = await run(provider)
    assert result == "One is present." and len(provider.requests) == 2
    assert tools.statements_executed == 1 and tools.statement_errors == []
    observations = [json.loads(message["content"]) for message in provider.requests[1]["messages"]
                    if message.get("role") == "tool"]
    assert any(value.get("success") is True and value.get("data") == [{"VALUE": 1}] for value in observations)
