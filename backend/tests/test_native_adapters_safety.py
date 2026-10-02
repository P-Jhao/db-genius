"""Native sequence/locking guards and dispatch/commit evidence."""

from __future__ import annotations

import threading
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.dialects.oracle.base import OracleDialect
from sqlalchemy.exc import DBAPIError
from sqlalchemy.sql.elements import quoted_name

from app.adapters.cancellation import DatabaseExecutionInterrupted, DatabaseWriteOutcomeUnknown
from app.adapters.oracle import OracleAdapter
from app.adapters.safety import UnsafeStatement
from app.adapters.sqlserver import SqlServerAdapter
from app.adapters.types import DbConnectionConfig


def config(db_type: str) -> DbConnectionConfig:
    return DbConnectionConfig(db_type, "localhost", 1521 if db_type == "oracle" else 1433,
                              "TESTDB", "scott", "protocol-only-secret")


@pytest.mark.parametrize("adapter,statement", [
    (OracleAdapter(), "SELECT seq.NEXTVAL FROM DUAL"),
    (OracleAdapter(), 'SELECT seq."NEXTVAL" FROM DUAL'),
    (OracleAdapter(), "SELECT * FROM items FOR UPDATE"),
    (SqlServerAdapter(), "SELECT NEXT VALUE FOR dbo.seq"),
    (SqlServerAdapter(), "SELECT * FROM dbo.items WITH (UPDLOCK)"),
    (SqlServerAdapter(), "SELECT * FROM dbo.items WITH (XLOCK)"),
    (SqlServerAdapter(), "WITH c AS (DELETE FROM items OUTPUT deleted.id) SELECT * FROM c"),
    (SqlServerAdapter(), "SELECT id INTO dbo.new_items FROM dbo.items"),
])
def test_trial_and_comparison_reject_native_side_effects(adapter: object, statement: str) -> None:
    assert adapter.is_read_only(statement) is False
    with pytest.raises(UnsafeStatement):
        adapter.execute(config(adapter.db_type), statement, trial_mode=True)


@pytest.mark.parametrize("adapter,statement", [
    (OracleAdapter(), 'SELECT "NEXTVAL" FROM "seq"'),
    (OracleAdapter(), "SELECT seq.CURRVAL FROM DUAL"),
    (SqlServerAdapter(), "SELECT * FROM dbo.items WITH (NOLOCK)"),
    (SqlServerAdapter(), "SELECT TOP 2 [中文] FROM dbo.items"),
])
def test_pure_native_reads_remain_supported(adapter: object, statement: str) -> None:
    assert adapter.is_read_only(statement) is True


@pytest.mark.parametrize("adapter", [OracleAdapter(), SqlServerAdapter()])
def test_native_commands_do_not_bypass_parser(adapter: object) -> None:
    for sql in ("SHOW TABLES", "DESC items", "EXPLAIN SELECT 1", "EXEC sp_who", "SELECT 1; DELETE FROM items"):
        with pytest.raises(UnsafeStatement):
            adapter.execute(config(adapter.db_type), sql)


@pytest.mark.parametrize("name,expected", [
    ("items", "items"), (quoted_name("items", True), '"items"'),
    ("Order Lines", '"Order Lines"'), ("MixedCase", '"MixedCase"'),
])
def test_oracle_normalized_and_quoted_names_stay_distinct(name: str, expected: str) -> None:
    connection = Mock(dialect=OracleDialect())
    assert OracleAdapter()._qualified_name(connection, name) == expected


@pytest.mark.parametrize("adapter,sql", [
    (OracleAdapter(), "SELECT seq.NEXTVAL FROM DUAL"),
    (OracleAdapter(), 'SELECT seq."NEXTVAL" FROM DUAL'),
    (SqlServerAdapter(), "SELECT NEXT VALUE FOR dbo.seq"),
])
def test_sequence_pre_dispatch_cancel_has_no_unknown_write(adapter: object, sql: str) -> None:
    signal = threading.Event()
    signal.set()
    with pytest.raises(DatabaseExecutionInterrupted) as captured:
        adapter.execute(config(adapter.db_type), sql, cancel_event=signal)
    assert captured.value.write_outcome_unknown is False
    assert captured.value.cancel_request_sent is False


@pytest.mark.parametrize("adapter,sql", [
    (OracleAdapter(), "SELECT seq.NEXTVAL FROM DUAL"),
    (OracleAdapter(), 'SELECT seq."NEXTVAL" FROM DUAL'),
    (SqlServerAdapter(), "SELECT NEXT VALUE FOR dbo.seq"),
])
def test_sequence_failure_after_actual_dispatch_is_unknown(
    monkeypatch: pytest.MonkeyPatch, adapter: object, sql: str,
) -> None:
    engine = create_engine("sqlite://")
    monkeypatch.setattr(adapter, "_engine", lambda *_args: engine)
    monkeypatch.setattr(adapter, "_set_timeout", lambda *_args: None)
    observed: list[str] = []
    event.listen(engine, "before_cursor_execute", lambda _c, _u, s, _p, _x, _m: observed.append(s))
    with pytest.raises(DatabaseWriteOutcomeUnknown):
        adapter.execute(config(adapter.db_type), sql)
    assert observed == [sql]


@pytest.mark.parametrize("adapter", [OracleAdapter(), SqlServerAdapter()])
def test_connection_failure_before_sequence_dispatch_is_not_a_write(
    monkeypatch: pytest.MonkeyPatch, adapter: object,
) -> None:
    @contextmanager
    def unavailable(*_args: object):
        raise DBAPIError("connect", {}, Exception("login denied"))
        yield  # pragma: no cover
    monkeypatch.setattr(adapter, "_connection", unavailable)
    sql = "SELECT seq.NEXTVAL FROM DUAL" if adapter.db_type == "oracle" else "SELECT NEXT VALUE FOR dbo.seq"
    with pytest.raises(DBAPIError):
        adapter.execute(config(adapter.db_type), sql)


@pytest.mark.parametrize("adapter", [OracleAdapter(), SqlServerAdapter()])
def test_commit_failure_of_allowed_write_is_unknown(monkeypatch: pytest.MonkeyPatch, adapter: object) -> None:
    connection = Mock()
    connection.execution_options.return_value.exec_driver_sql.return_value = Mock(returns_rows=False, rowcount=1)
    connection.commit.side_effect = DBAPIError("COMMIT", {}, Exception("connection lost"))
    @contextmanager
    def connected(*_args: object):
        yield connection
    monkeypatch.setattr(adapter, "_connection", connected)
    monkeypatch.setattr(adapter, "_set_timeout", lambda *_args: None)
    with pytest.raises(DatabaseWriteOutcomeUnknown):
        adapter.execute(config(adapter.db_type), "UPDATE items SET name='中文'")
    connection.execution_options.return_value.exec_driver_sql.assert_called_once()


def test_sqlserver_timeout_requires_driver_code() -> None:
    adapter = SqlServerAdapter()
    assert adapter._driver_timeout(DBAPIError("SELECT 1", {}, Exception(20003, b"timeout"))) is True
    assert adapter._driver_timeout(DBAPIError("SELECT 1", {}, Exception("column timeout missing"))) is False
    assert adapter._server_confirmed_interrupt(DBAPIError("SELECT 1", {}, Exception(20003))) is False


def test_oracle_thick_mode_is_not_silently_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.adapters.oracle.oracledb.is_thin_mode", lambda: False)
    with pytest.raises(RuntimeError, match="Thin mode"):
        OracleAdapter()._engine(config("oracle"), 30)


def test_oracle_trial_starts_read_only_and_sets_round_trip_timeout() -> None:
    import oracledb
    driver = Mock(spec=oracledb.Connection)
    connection = Mock(connection=SimpleNamespace(driver_connection=driver))
    OracleAdapter()._set_timeout(connection, 2, True)
    assert driver.call_timeout == 2000
    connection.exec_driver_sql.assert_called_once_with("SET TRANSACTION READ ONLY")
