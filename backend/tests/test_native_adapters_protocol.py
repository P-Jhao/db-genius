"""Oracle and SQL Server driver, dialect, metadata and execution protocol tests."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch

import oracledb
import pytest
from sqlalchemy.dialects.oracle import NUMBER, NVARCHAR2
from sqlalchemy.dialects.oracle.base import OracleDialect
from sqlalchemy.exc import DBAPIError

from app.adapters.cancellation import DatabaseExecutionInterrupted
from app.adapters.oracle import OracleAdapter
from app.adapters.safety import UnsafeStatement
from app.adapters.sqlserver import SqlServerAdapter
from app.adapters.types import DbConnectionConfig


def config(db_type: str) -> DbConnectionConfig:
    port = 1521 if db_type == "oracle" else 1433
    return DbConnectionConfig(db_type, "db.example", port, "TESTDB", "scott", "p@:/#word")


def connected(monkeypatch: pytest.MonkeyPatch, adapter: object, connection: object) -> None:
    @contextmanager
    def open_connection(_config: DbConnectionConfig, _timeout: int) -> Iterator[object]:
        yield connection

    monkeypatch.setattr(adapter, "_connection", open_connection)


def test_oracle_service_name_thin_driver_and_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = OracleAdapter()
    with patch("app.adapters.oracle.create_engine") as create:
        adapter._engine(config("oracle"), 30)
    url = create.call_args.args[0]
    assert (url.drivername, url.database, url.query["service_name"]) == (
        "oracle+oracledb", None, "TESTDB"
    )
    assert url.password == "p@:/#word"
    driver = Mock(spec=oracledb.Connection)
    with patch("app.adapters.oracle.oracledb.connect", return_value=driver) as connect:
        assert create.call_args.kwargs["creator"]() is driver
    assert connect.call_args.kwargs == {"user": "scott", "password": "p@:/#word", "host": "db.example",
                                       "port": 1521, "service_name": "TESTDB", "tcp_connect_timeout": 10.0}
    assert driver.call_timeout == 30000
    connection = Mock()
    connection.exec_driver_sql.return_value.scalar_one.return_value = 1
    connection.connection.driver_connection = Mock(spec=oracledb.Connection)
    connected(monkeypatch, adapter, connection)
    assert adapter.test_connection(config("oracle")) is True
    assert connection.exec_driver_sql.call_args.args == ("SELECT 1 FROM DUAL",)
    assert adapter.metadata_schema is None


def test_sqlserver_driver_unicode_datetime_and_dbo() -> None:
    adapter = SqlServerAdapter()
    with patch("app.adapters.sqlserver.create_engine") as create:
        adapter._engine(config("sqlserver"), 30)
    url = create.call_args.args[0]
    assert (url.drivername, url.database, url.port, url.password) == (
        "mssql+pymssql", "TESTDB", 1433, "p@:/#word"
    )
    assert create.call_args.kwargs["connect_args"] == {
        "timeout": 30, "login_timeout": 10, "charset": "UTF-8",
        "use_datetime2": True, "encryption": "require",
    }
    assert adapter.metadata_schema == "dbo"


@pytest.mark.parametrize("db_type", ["oracle", "sqlserver"])
def test_required_credentials_and_timeout_validation(db_type: str) -> None:
    adapter = (OracleAdapter() if db_type == "oracle" else SqlServerAdapter())
    valid = config(db_type)
    adapter.validate_config(valid)
    with pytest.raises(ValueError):
        adapter.validate_config(DbConnectionConfig(db_type, valid.host, valid.port,
                                                   valid.db_name, valid.username, ""))
    with pytest.raises(ValueError):
        adapter._engine(valid, 0)


@pytest.mark.parametrize("db_type,select", [
    ("oracle", 'WITH x AS (SELECT 1 FROM DUAL) SELECT * FROM x'),
    ("sqlserver", "SELECT TOP 10 [name] FROM [dbo].[items]"),
])
def test_dialect_safety_and_trial(db_type: str, select: str) -> None:
    adapter = (OracleAdapter() if db_type == "oracle" else SqlServerAdapter())
    assert adapter.is_read_only(select) is True
    assert adapter.is_read_only("UPDATE items SET name = '中文'") is False
    for statement in ("DROP TABLE items", "TRUNCATE TABLE items", "ALTER TABLE items DROP COLUMN name",
                      "SELECT 1; DELETE FROM items"):
        with pytest.raises(UnsafeStatement):
            adapter.execute(config(db_type), statement)
    with pytest.raises(UnsafeStatement):
        adapter.execute(config(db_type), "UPDATE items SET name = 'x'", trial_mode=True)
    if db_type == "sqlserver":
        with pytest.raises(UnsafeStatement):
            adapter.execute(config(db_type), "EXEC sp_who")
        assert adapter.is_read_only("SELECT name INTO new_items FROM items") is False
        with pytest.raises(UnsafeStatement):
            adapter.execute(config(db_type), "SELECT name INTO new_items FROM items", trial_mode=True)


@pytest.mark.parametrize("db_type,table,expected", [
    ("oracle", 'Order"Lines', '"SCOTT"."Order""Lines"'),
    ("sqlserver", "Order]Lines", "[dbo].[Order]]Lines]"),
])
def test_metadata_uses_schema_quote_and_preserves_types(
    db_type: str, table: str, expected: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = (OracleAdapter() if db_type == "oracle" else SqlServerAdapter())
    def quote(value: str) -> str:
        if db_type == "oracle":
            return '"' + value.replace('"', '""') + '"'
        return "[" + value.replace("]", "]]") + "]"
    connection = Mock()
    connection.begin_nested.return_value = nullcontext()
    if db_type == "oracle":
        connection.dialect = OracleDialect()
    else:
        connection.dialect.identifier_preparer.quote_identifier = quote
        connection.dialect.identifier_preparer.quote = quote
    connection.exec_driver_sql.return_value.scalar_one.return_value = 7
    if db_type == "oracle":
        connection.exec_driver_sql.return_value.scalar_one.side_effect = ["SCOTT", 7]
    connected(monkeypatch, adapter, connection)
    monkeypatch.setattr(adapter, "_set_timeout", lambda *_args: None)
    inspector = Mock()
    inspector.get_table_names.return_value = [table]
    inspector.get_columns.return_value = [
        {"name": "id", "type": NUMBER(10) if db_type == "oracle" else "INTEGER",
         "nullable": False, "comment": None},
        {"name": "title", "type": NVARCHAR2(30) if db_type == "oracle" else "NVARCHAR(30)", "nullable": True, "comment": "Unicode"},
    ]
    inspector.get_pk_constraint.return_value = {"constrained_columns": ["id"], "name": "pk_items"}
    inspector.get_indexes.return_value = [{"name": "ix_title", "column_names": ["title"]}]
    inspector.get_table_comment.return_value = {"text": "items"}
    monkeypatch.setattr("app.adapters.relational.inspect", lambda _connection: inspector)
    metadata = adapter.extract_metadata(config(db_type))
    schema = "SCOTT" if db_type == "oracle" else "dbo"
    inspector.get_table_names.assert_called_once_with(schema=schema)
    inspector.get_columns.assert_called_once_with(table, schema=schema)
    assert connection.exec_driver_sql.call_args.args == (f"SELECT COUNT(*) FROM {expected}",)
    assert metadata["incomplete"] is False
    assert metadata["tables"][0]["rowCount"] == 7
    assert metadata["tables"][0]["columns"][1]["type"] == ("NVARCHAR2(30)" if db_type == "oracle" else "NVARCHAR(30)")
    expected_indexes = [{"name": "pk_items", "columns": ["id"]}, {"name": "ix_title", "columns": ["title"]}]
    if db_type == "oracle":
        expected_indexes = [{"name": "PK_ITEMS", "columns": ["ID"]}, {"name": "IX_TITLE", "columns": ["TITLE"]}]
    assert metadata["tables"][0]["indexes"] == expected_indexes


@pytest.mark.parametrize("db_type,statement", [
    ("oracle", "SELECT 1 AS value FROM DUAL"),
    ("sqlserver", "SELECT TOP 200 name FROM dbo.items"),
])
def test_read_result_limited_to_100_and_normalized(
    db_type: str, statement: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = (OracleAdapter() if db_type == "oracle" else SqlServerAdapter())
    rows = [SimpleNamespace(_mapping={"name": "中文", "created": datetime(2026, 9, 29, tzinfo=UTC),
                                    "amount": Decimal("1.2300")}) for _ in range(101)]
    result = Mock(returns_rows=True)
    result.fetchmany.return_value = rows
    connection = Mock()
    connection.execution_options.return_value.exec_driver_sql.return_value = result
    connected(monkeypatch, adapter, connection)
    monkeypatch.setattr(adapter, "_set_timeout", lambda *_args: None)
    output = adapter.execute(config(db_type), statement)
    assert output["rowCount"] == 100 and output["truncated"] is True
    assert output["data"][0] == {"name": "中文", "created": "2026-09-29T00:00:00+00:00",
                                 "amount": "1.2300"}
    result.fetchmany.assert_called_once_with(101)
    connection.commit.assert_called_once()


@pytest.mark.parametrize("db_type,statement", [
    ("oracle", "UPDATE items SET amount = 2"),
    ("sqlserver", "UPDATE dbo.items SET amount = 2"),
])
def test_write_result_and_commit(db_type: str, statement: str, monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = (OracleAdapter() if db_type == "oracle" else SqlServerAdapter())
    result = Mock(returns_rows=False, rowcount=2)
    connection = Mock()
    connection.execution_options.return_value.exec_driver_sql.return_value = result
    connected(monkeypatch, adapter, connection)
    monkeypatch.setattr(adapter, "_set_timeout", lambda *_args: None)
    output = adapter.execute(config(db_type), statement)
    assert output["affectedRows"] == 2
    connection.commit.assert_called_once()


def test_sqlserver_cancel_not_reported_as_server_stopped(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = SqlServerAdapter()
    signal = threading.Event()
    entered = threading.Event()
    release = threading.Event()
    connection = Mock()
    result = Mock(returns_rows=False, rowcount=1)

    def run_statement(_statement: str) -> Mock:
        entered.set()
        assert release.wait(3)
        return result

    connection.execution_options.return_value.exec_driver_sql.side_effect = run_statement
    connected(monkeypatch, adapter, connection)
    captured: list[DatabaseExecutionInterrupted] = []

    def run() -> None:
        try:
            adapter.execute(config("sqlserver"), "UPDATE dbo.items SET amount = 2",
                            cancel_event=signal)
        except DatabaseExecutionInterrupted as exc:
            captured.append(exc)

    worker = threading.Thread(target=run)
    worker.start()
    assert entered.wait(3)
    signal.set()
    threading.Event().wait(0.1)
    release.set()
    worker.join(4)
    assert not worker.is_alive() and len(captured) == 1
    assert captured[0].reason == "cancelled"
    assert captured[0].cancel_request_sent is False
    assert captured[0].server_termination_confirmed is False
    assert captured[0].write_outcome_unknown is True
    assert isinstance(captured[0].cancel_error, RuntimeError)
    connection.commit.assert_not_called()


def test_oracle_cancel_confirmation_requires_driver_error(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = OracleAdapter()
    signal = threading.Event()
    entered = threading.Event()
    cancelled = threading.Event()
    driver = Mock(spec=oracledb.Connection)
    driver.cancel.side_effect = cancelled.set
    connection = Mock()
    connection.connection.driver_connection = driver

    def run_statement(_statement: str) -> Mock:
        entered.set()
        assert cancelled.wait(3)
        reason = SimpleNamespace(code=1013)
        raise DBAPIError("UPDATE items SET amount = 2", {}, Exception(reason))

    connection.execution_options.return_value.exec_driver_sql.side_effect = run_statement
    connected(monkeypatch, adapter, connection)
    captured: list[DatabaseExecutionInterrupted] = []

    def run() -> None:
        try:
            adapter.execute(config("oracle"), "UPDATE items SET amount = 2", cancel_event=signal)
        except DatabaseExecutionInterrupted as exc:
            captured.append(exc)

    worker = threading.Thread(target=run)
    worker.start()
    assert entered.wait(3)
    signal.set()
    worker.join(4)
    assert not worker.is_alive() and len(captured) == 1
    assert captured[0].cancel_request_sent is True
    assert captured[0].server_termination_confirmed is True
    assert captured[0].write_outcome_unknown is True
    connection.commit.assert_not_called()
