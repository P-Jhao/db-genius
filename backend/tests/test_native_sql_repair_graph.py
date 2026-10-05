"""Controlled HTTP native feedback, followed by repair or a terminal interruption."""

import json

import pytest
from test_model_protocol import Provider
from test_native_sql_repair_policy import native_error
from test_sql_repair import answer, call, run
from test_sql_repair import provider as provider_fixture

from app.adapters.cancellation import DatabaseExecutionInterrupted, DatabaseWriteOutcomeUnknown
from app.agent.cancellation import RunAborted
from app.services import database_tools

provider = provider_fixture


def schema(db_type: str) -> dict[str, object]:
    return {"dbType": db_type, "tables": [{"name": "records", "columns": ["id", "name"]}]}


@pytest.mark.asyncio
@pytest.mark.parametrize("db_type,code,bad", [
    ("oracle", 904, "SELECT missing FROM records"), ("oracle", 942, "SELECT name FROM recrods"),
    ("oracle", 933, "SELECT name FROM records LIMIT 1"),
    ("sqlserver", 207, "SELECT missing FROM records"), ("sqlserver", 208, "SELECT name FROM recrods"),
    ("sqlserver", 102, "SELECT name FROM records LIMIT 1"),
])
async def test_native_known_parse_failure_reaches_http_model_and_is_corrected(
    provider: Provider, monkeypatch: pytest.MonkeyPatch, db_type: str, code: int, bad: str,
) -> None:
    monkeypatch.setattr(database_tools, "get_schema", lambda *_: schema(db_type))
    executed: list[str] = []
    def execute(user_id: int, db_id: int, statement: str) -> dict[str, object]:
        assert (user_id, db_id) == (7, 12)
        executed.append(statement)
        if statement == bad:
            raise native_error(db_type, code, statement)
        assert statement == "SELECT name FROM records"
        return {"success": True, "rowCount": 1, "data": [{"name": "Ada"}]}
    monkeypatch.setattr(database_tools, "execute_statement", execute)
    provider.replies = [call(bad, "bad"), call("SELECT name FROM records", "fixed"), answer("Ada is present.")]
    result, tools, events = await run(provider)
    assert result == "Ada is present." and len(provider.requests) == 4
    assert executed == [bad, "SELECT name FROM records"]
    assert tools.statements_executed == 1 and tools.completed_write_count == 0
    observations = [json.loads(message["content"]) for message in provider.requests[2]["messages"]
                    if message.get("role") == "tool"]
    assert any(value.get("success") is False and value.get("errorCode") == code for value in observations)
    assert any(kind == "step" and '"success": false' in str(value) for kind, value in events)


@pytest.mark.asyncio
@pytest.mark.parametrize("db_type,code", [("oracle", 942), ("sqlserver", 208)])
@pytest.mark.parametrize("condition", ["invalidated", "rollback_failed", "failed_dml"])
async def test_native_unsafe_driver_diagnostic_stops_before_another_model_call(
    provider: Provider, monkeypatch: pytest.MonkeyPatch, db_type: str, code: int, condition: str,
) -> None:
    monkeypatch.setattr(database_tools, "get_schema", lambda *_: schema(db_type))
    statement = "INSERT INTO records VALUES (1,'Ada')" if condition == "failed_dml" else "SELECT name FROM records"
    error = native_error(db_type, code, statement)
    if condition == "invalidated":
        error.connection_invalidated = True
    if condition == "rollback_failed":
        error.add_note("Rollback also failed: simulated connection loss")
    executions: list[str] = []
    def execute(_user: int, _db: int, sql: str) -> dict[str, object]:
        executions.append(sql)
        raise error
    monkeypatch.setattr(database_tools, "execute_statement", execute)
    provider.replies = [call(statement, "uncertain"), call(statement, "must_not_repeat")]
    with pytest.raises(type(error)):
        await run(provider)
    assert len(provider.requests) == 2 and executions == [statement]


@pytest.mark.asyncio
@pytest.mark.parametrize("condition", ["write", "sequence", "cancel", "timeout"])
async def test_native_unknown_side_effect_or_interruption_never_replays(
    provider: Provider, monkeypatch: pytest.MonkeyPatch, condition: str,
) -> None:
    monkeypatch.setattr(database_tools, "get_schema", lambda *_: schema("oracle"))
    statement = 'SELECT seq."NEXTVAL" FROM DUAL' if condition == "sequence" else "INSERT INTO records VALUES (1,'Ada')"
    side_effects: list[str] = []
    def execute(_user: int, _db: int, sql: str) -> dict[str, object]:
        side_effects.append(sql)
        if condition in {"write", "sequence"}:
            raise DatabaseWriteOutcomeUnknown("simulated commit/sequence result unknown")
        raise DatabaseExecutionInterrupted("cancelled" if condition == "cancel" else "timeout",
                                           cancel_request_sent=False, server_termination_confirmed=False,
                                           write_outcome_unknown=True)
    monkeypatch.setattr(database_tools, "execute_statement", execute)
    provider.replies = [call(statement, "first"), call(statement, "must_not_repeat")]
    with pytest.raises(RunAborted):
        await run(provider)
    assert len(provider.requests) == 2 and side_effects == [statement]
