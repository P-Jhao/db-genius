"""Per-call Oracle schema identity and process-wide FreeTDS timeout isolation."""

from __future__ import annotations

import threading
from contextlib import contextmanager, nullcontext
from unittest.mock import Mock

import oracledb
import pytest
from sqlalchemy.dialects.oracle import NUMBER, VARCHAR2
from sqlalchemy.dialects.oracle.base import OracleDialect
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.sql.elements import quoted_name

from app.adapters.native_relational import NativeRelationalAdapter
from app.adapters.oracle import OracleAdapter
from app.adapters.sqlserver import SqlServerAdapter
from app.adapters.types import DbConnectionConfig


def config(db_type: str) -> DbConnectionConfig:
    return DbConnectionConfig(db_type, "localhost", 1521 if db_type == "oracle" else 1433,
                              "TESTDB", "MixedLogin", "protocol@:/secret")


@pytest.mark.parametrize("actual_user", ["SCOTT", "MixedLogin", "lower"])
def test_oracle_metadata_uses_actual_session_user_and_quoted_names(
    monkeypatch: pytest.MonkeyPatch, actual_user: str,
) -> None:
    adapter = OracleAdapter()
    driver = Mock(spec=oracledb.Connection)
    connection = Mock(dialect=OracleDialect())
    connection.connection.driver_connection = driver
    connection.begin_nested.return_value = nullcontext()
    user = Mock()
    user.scalar_one.return_value = actual_user
    count = Mock()
    count.scalar_one.return_value = 3
    observed: list[str] = []
    def query(sql: str) -> Mock:
        observed.append(sql)
        return user if "SESSION_USER" in sql else count
    connection.exec_driver_sql.side_effect = query
    @contextmanager
    def connected(*_args: object):
        yield connection
    monkeypatch.setattr(adapter, "_connection", connected)
    inspector = Mock()
    inspector.get_table_names.return_value = ["items", quoted_name("items", True), "MixedCase"]
    inspector.get_columns.return_value = [
        {"name": "Name", "type": NUMBER(12, 4), "nullable": False},
        {"name": quoted_name("name", True), "type": VARCHAR2(10), "nullable": True},
    ]
    inspector.get_pk_constraint.return_value = {"name": "pk", "constrained_columns": ["Name"]}
    inspector.get_indexes.return_value = []
    inspector.get_table_comment.return_value = {"text": None}
    monkeypatch.setattr("app.adapters.relational.inspect", lambda _c: inspector)
    metadata = adapter.extract_metadata(config("oracle"))
    inspector.get_table_names.assert_called_once_with(schema=quoted_name(actual_user, True))
    assert observed == [
        "SELECT SYS_CONTEXT('USERENV', 'SESSION_USER') FROM DUAL", "SET TRANSACTION READ ONLY",
        f'SELECT COUNT(*) FROM "{actual_user}".items',
        f'SELECT COUNT(*) FROM "{actual_user}"."items"',
        f'SELECT COUNT(*) FROM "{actual_user}"."MixedCase"',
    ]
    assert connection.rollback.call_count == 2
    assert adapter.metadata_schema is None
    assert metadata["schemaName"] == actual_user
    assert [table["name"] for table in metadata["tables"]] == ["ITEMS", "items", "MixedCase"]
    assert metadata["incomplete"] is False
    assert metadata["tables"][0]["columns"][0]["name"] == "Name"
    assert metadata["tables"][0]["columns"][1]["name"] == "name"
    assert metadata["tables"][0]["columns"][0]["primaryKey"] is True


def test_oracle_partial_diagnostic_is_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = OracleAdapter()
    connection = Mock()
    connection.connection.driver_connection = Mock(spec=oracledb.Connection)
    connection.exec_driver_sql.return_value.scalar_one.return_value = "SCOTT"
    connection.begin_nested.return_value = nullcontext()
    @contextmanager
    def connected(*_args: object):
        yield connection
    monkeypatch.setattr(adapter, "_connection", connected)
    inspector = Mock()
    inspector.get_table_names.return_value = ["restricted"]
    inspector.get_columns.side_effect = SQLAlchemyError("login protocol@:/secret rejected")
    monkeypatch.setattr("app.adapters.relational.inspect", lambda _c: inspector)
    result = adapter.extract_metadata(config("oracle"))
    assert result["incomplete"] is True
    assert result["errorMessage"] == "restricted: login [REDACTED] rejected"


def test_sqlserver_sessions_serialize_global_timeout_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    entered = threading.Event()
    release = threading.Event()
    observed: list[int] = []
    errors: list[Exception] = []
    @contextmanager
    def connected(_self: object, _config: object, timeout: int):
        observed.append(timeout)
        if timeout == 5:
            entered.set()
            assert release.wait(4)
        yield Mock()
    monkeypatch.setattr(NativeRelationalAdapter, "_connection", connected)
    def first() -> None:
        try:
            with SqlServerAdapter()._connection(config("sqlserver"), 5):
                pass
        except Exception as exc:  # noqa: BLE001 - collect worker assertion/connection failures
            errors.append(exc)
    worker = threading.Thread(target=first)
    worker.start()
    try:
        assert entered.wait(2)
        with pytest.raises(TimeoutError, match="before dispatch"), SqlServerAdapter()._connection(config("sqlserver"), 1):
            pytest.fail("Competing session changed process-wide timeout")
        assert observed == [5]
    finally:
        release.set()
        worker.join(4)
    assert not worker.is_alive() and errors == []
    with SqlServerAdapter()._connection(config("sqlserver"), 2):
        pass
    assert observed == [5, 2]


def test_sqlserver_lock_is_released_on_connect_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    @contextmanager
    def unavailable(*_args: object):
        raise SQLAlchemyError("login unavailable")
        yield  # pragma: no cover
    monkeypatch.setattr(NativeRelationalAdapter, "_connection", unavailable)
    for _attempt in range(2):
        with pytest.raises(SQLAlchemyError, match="login unavailable"), SqlServerAdapter()._connection(config("sqlserver"), 1):
            pass


def test_sqlserver_cancel_while_waiting_does_not_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.adapters import sqlserver
    from app.adapters.cancellation import DatabaseExecutionInterrupted
    lock = threading.Lock()
    lock.acquire()
    monkeypatch.setattr(sqlserver, "_DRIVER_LOCK", lock)
    signal = threading.Event()
    captured: list[DatabaseExecutionInterrupted] = []
    adapter = SqlServerAdapter()
    engine = Mock(side_effect=AssertionError("Cancelled queued work must not connect"))
    monkeypatch.setattr(adapter, "_engine", engine)
    def run() -> None:
        try:
            adapter.execute(config("sqlserver"), "UPDATE items SET value=1", cancel_event=signal)
        except DatabaseExecutionInterrupted as exc:
            captured.append(exc)
    worker = threading.Thread(target=run)
    worker.start()
    try:
        signal.set()
        worker.join(2)
        assert not worker.is_alive() and len(captured) == 1
        assert captured[0].write_outcome_unknown is False
        assert captured[0].cancel_request_sent is False
        assert captured[0].server_termination_confirmed is False
        engine.assert_not_called()
    finally:
        lock.release()
        worker.join(2)


def test_oracle_execution_keeps_actual_driver_column_names(monkeypatch: pytest.MonkeyPatch) -> None:
    from sqlalchemy import create_engine
    adapter = OracleAdapter()
    engine = create_engine("sqlite://")
    engine.dialect.requires_name_normalize = True
    engine.dialect.normalize_name = OracleDialect().normalize_name
    monkeypatch.setattr(adapter, "_engine", lambda *_args: engine)
    monkeypatch.setattr(adapter, "_set_timeout", lambda *_args: None)
    result = adapter.execute(config("oracle"), 'SELECT 1 AS ID, 2 AS "id", 3 AS "Mixed"')
    assert result["data"] == [{"ID": 1, "id": 2, "Mixed": 3}]
