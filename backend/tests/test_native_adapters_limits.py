"""Timeout, partial metadata and Oracle LOB protocol boundaries."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from unittest.mock import Mock

import oracledb
import pytest
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from app.adapters.cancellation import DatabaseExecutionInterrupted
from app.adapters.oracle import OracleAdapter
from app.adapters.sqlserver import SqlServerAdapter
from app.adapters.types import DbConnectionConfig


def config(db_type: str) -> DbConnectionConfig:
    return DbConnectionConfig(db_type, "localhost", 1521 if db_type == "oracle" else 1433,
                              "TESTDB", "scott", "secret")


def connected(monkeypatch: pytest.MonkeyPatch, adapter: object, connection: Mock) -> None:
    @contextmanager
    def open_connection(_config: DbConnectionConfig, _timeout: int) -> Iterator[Mock]:
        yield connection

    monkeypatch.setattr(adapter, "_connection", open_connection)


@pytest.mark.parametrize("db_type", ["oracle", "sqlserver"])
def test_driver_timeout_never_claims_unconfirmed_server_stop(
    monkeypatch: pytest.MonkeyPatch, db_type: str,
) -> None:
    adapter = (OracleAdapter() if db_type == "oracle" else SqlServerAdapter())
    connection = Mock()
    cancelled = threading.Event()
    if db_type == "oracle":
        driver = Mock(spec=oracledb.Connection)
        driver.cancel.side_effect = cancelled.set
        connection.connection.driver_connection = driver

        def execute(_statement: str) -> Mock:
            assert cancelled.wait(3)
            detail = Mock(code=1013)
            raise DBAPIError("UPDATE items SET amount=1", {}, Exception(detail))
    else:
        def execute(_statement: str) -> Mock:
            time.sleep(1.1)
            raise DBAPIError("UPDATE dbo.items SET amount=1", {}, Exception(20003))

    connection.execution_options.return_value.exec_driver_sql.side_effect = execute
    connected(monkeypatch, adapter, connection)
    if db_type == "sqlserver":
        monkeypatch.setattr(adapter, "_set_timeout", lambda *_args: None)
    with pytest.raises(DatabaseExecutionInterrupted) as captured:
        adapter.execute(config(db_type), "UPDATE items SET amount=1", timeout_seconds=1)
    interrupted = captured.value
    assert interrupted.reason == "timeout"
    assert interrupted.write_outcome_unknown is True
    assert interrupted.server_termination_confirmed is (db_type == "oracle")
    assert interrupted.cancel_request_sent is (db_type == "oracle")
    connection.commit.assert_not_called()


@pytest.mark.parametrize("db_type", ["oracle", "sqlserver"])
def test_metadata_table_failure_is_marked_incomplete(
    monkeypatch: pytest.MonkeyPatch, db_type: str,
) -> None:
    adapter = (OracleAdapter() if db_type == "oracle" else SqlServerAdapter())
    connection = Mock()
    connection.begin_nested.return_value = nullcontext()
    connected(monkeypatch, adapter, connection)
    monkeypatch.setattr(adapter, "_set_timeout", lambda *_args: None)
    connection.exec_driver_sql.return_value.scalar_one.return_value = "SCOTT"
    inspector = Mock()
    inspector.get_table_names.return_value = ["restricted"]
    inspector.get_columns.side_effect = SQLAlchemyError("metadata permission denied")
    monkeypatch.setattr("app.adapters.relational.inspect", lambda _connection: inspector)
    metadata = adapter.extract_metadata(config(db_type))
    assert metadata["tables"] == []
    assert metadata["incomplete"] is True
    assert "restricted: metadata permission denied" in (metadata["errorMessage"] or "")


def test_oracle_lob_is_normalized_before_result_close(monkeypatch: pytest.MonkeyPatch) -> None:
    class Lob:
        def read(self) -> str:
            return "Unicode 文本"

    monkeypatch.setattr("app.adapters.oracle.oracledb.LOB", Lob)
    assert OracleAdapter()._json_value(Lob()) == "Unicode 文本"


@pytest.mark.parametrize("db_type,original", [
    ("oracle", Exception(Mock(full_code="DPY-4024"))),
    ("sqlserver", Exception(20003, b"Adaptive Server connection timed out")),
])
def test_driver_timeout_before_watchdog_tick_is_explicit(
    monkeypatch: pytest.MonkeyPatch, db_type: str, original: Exception,
) -> None:
    adapter = (OracleAdapter() if db_type == "oracle" else SqlServerAdapter())
    connection = Mock()
    if db_type == "oracle":
        connection.connection.driver_connection = Mock(spec=oracledb.Connection)
    connection.execution_options.return_value.exec_driver_sql.side_effect = DBAPIError(
        "UPDATE items SET amount=1", {}, original
    )
    connected(monkeypatch, adapter, connection)
    if db_type == "sqlserver":
        monkeypatch.setattr(adapter, "_set_timeout", lambda *_args: None)
    with pytest.raises(DatabaseExecutionInterrupted) as captured:
        adapter.execute(config(db_type), "UPDATE items SET amount=1", timeout_seconds=30)
    assert captured.value.reason == "timeout"
    assert captured.value.server_termination_confirmed is False
    assert captured.value.write_outcome_unknown is True
