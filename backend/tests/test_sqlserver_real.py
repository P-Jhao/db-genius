"""Actual pymssql/SQL Server connection, metadata, data and execution limits."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import uuid4

import pytest
from native_database_fixtures import sqlserver_target as sqlserver_fixture
from sqlalchemy.engine import Engine

from app.adapters.cancellation import DatabaseExecutionInterrupted
from app.adapters.safety import UnsafeStatement
from app.adapters.sqlserver import SqlServerAdapter
from app.adapters.types import DbConnectionConfig

sqlserver_target = sqlserver_fixture


def test_sqlserver_real_unicode_decimal_lob_and_dbo_metadata(
    sqlserver_target: tuple[DbConnectionConfig, Engine],
) -> None:
    config, engine = sqlserver_target
    adapter = SqlServerAdapter()
    assert adapter.test_connection(config)
    table = "native Order " + uuid4().hex[:8]
    quoted = f"[dbo].[{table}]"
    try:
        adapter.execute(config, f"CREATE TABLE {quoted} ([id] INT PRIMARY KEY, [文本] NVARCHAR(MAX), "
            "[amount] DECIMAL(38,12) NOT NULL, [cash] MONEY, [payload] VARBINARY(MAX), [created] DATETIME2(6))")
        adapter.execute(config, f"INSERT INTO {quoted} VALUES (1,N'中文🙂',"
            "12345678901234567890.123456789012,1.25,0x010203,'2026-10-01T02:03:04.123456')")
        with engine.begin() as connection:
            connection.exec_driver_sql(f"CREATE INDEX [ix_cash] ON {quoted} ([cash])")
            connection.exec_driver_sql("EXEC sys.sp_addextendedproperty @name=N'MS_Description',"
                "@value=N'真实 Unicode 表', @level0type=N'SCHEMA',@level0name=N'dbo',"
                f"@level1type=N'TABLE',@level1name=N'{table}'")
        output = adapter.execute(config, f"SELECT * FROM {quoted}", trial_mode=True)
        assert output["data"] == [{"id": 1, "文本": "中文🙂", "amount": "12345678901234567890.123456789012",
            "cash": "1.2500", "payload": "AQID", "created": "2026-10-01T02:03:04.123456"}]
        metadata = adapter.extract_metadata(config)
        assert metadata["incomplete"] is False, metadata["errorMessage"]
        actual = next(value for value in metadata["tables"] if value["name"] == table)
        columns = {value["name"]: value for value in actual["columns"]}
        assert columns["id"]["primaryKey"] is True
        assert columns["amount"]["nullable"] is False and "DECIMAL(38, 12)" == columns["amount"]["type"]
        assert actual["rowCount"] == 1 and actual["comment"] == "真实 Unicode 表"
        assert any(index["columns"] == ["cash"] for index in actual["indexes"])
        assert "真实 Unicode 表" in adapter.generate_document(config)
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f"DROP TABLE IF EXISTS {quoted}")


def test_sqlserver_real_allowed_writes_trial_and_row_limit(
    sqlserver_target: tuple[DbConnectionConfig, Engine],
) -> None:
    config, engine = sqlserver_target
    adapter = SqlServerAdapter()
    table = "native_" + uuid4().hex[:12]
    quoted = f"[dbo].[{table}]"
    try:
        adapter.execute(config, f"CREATE TABLE {quoted} (id INT PRIMARY KEY, value INT)")
        with engine.begin() as connection:
            connection.exec_driver_sql(f"INSERT INTO {quoted} (id,value) VALUES (%s,%s)",
                                       [(number, number) for number in range(201)])
        output = adapter.execute(config, f"SELECT TOP 200 id,value FROM {quoted} ORDER BY id", trial_mode=True)
        assert output["rowCount"] == 100 and output["truncated"] is True
        assert adapter.execute(config, f"UPDATE {quoted} SET value=2 WHERE id=1")["affectedRows"] == 1
        assert adapter.execute(config, f"DELETE FROM {quoted} WHERE id=200")["affectedRows"] == 1
        for sql in (f"DROP TABLE {quoted}", f"TRUNCATE TABLE {quoted}", f"ALTER TABLE {quoted} DROP COLUMN value",
                    f"SELECT * INTO dbo.unwanted FROM {quoted}", f"UPDATE {quoted} SET value=3",
                    f"WITH c AS (SELECT * FROM {quoted}) DELETE FROM c"):
            with pytest.raises(UnsafeStatement):
                adapter.execute(config, sql, trial_mode=True)
        assert adapter.execute(config, f"SELECT COUNT(*) AS total FROM {quoted}")["data"] == [{"total": 200}]
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f"DROP TABLE IF EXISTS {quoted}")


@contextmanager
def blocked_table(config: DbConnectionConfig, engine: Engine) -> Iterator[str]:
    table = "[dbo].[blocked_" + uuid4().hex[:12] + "]"
    with engine.begin() as connection:
        connection.exec_driver_sql(f"CREATE TABLE {table} (id INT PRIMARY KEY, value INT)")
        connection.exec_driver_sql(f"INSERT INTO {table} VALUES (1,0)")
    blocker = engine.connect()
    transaction = blocker.begin()
    try:
        blocker.exec_driver_sql(f"UPDATE {table} SET value=1 WHERE id=1")
        yield table
    finally:
        transaction.rollback()
        blocker.close()
        with engine.begin() as connection:
            connection.exec_driver_sql(f"DROP TABLE {table}")



def test_sqlserver_real_query_timeout_does_not_claim_server_cancel(
    sqlserver_target: tuple[DbConnectionConfig, Engine],
) -> None:
    config, engine = sqlserver_target
    adapter = SqlServerAdapter()
    with blocked_table(config, engine) as table:
        started = time.monotonic()
        with pytest.raises(DatabaseExecutionInterrupted) as captured:
            adapter.execute(config, f"SELECT * FROM {table} WITH (READCOMMITTEDLOCK)", timeout_seconds=1)
        assert time.monotonic() - started < 10
        assert captured.value.reason == "timeout"
        assert captured.value.server_termination_confirmed is False
        assert captured.value.cancel_request_sent is False
        assert captured.value.write_outcome_unknown is False


def test_sqlserver_real_cancel_is_pending_until_driver_returns(
    sqlserver_target: tuple[DbConnectionConfig, Engine],
) -> None:
    config, engine = sqlserver_target
    adapter = SqlServerAdapter()
    signal = threading.Event()
    with blocked_table(config, engine) as table:
        timer = threading.Timer(0.4, signal.set)
        timer.start()
        try:
            with pytest.raises(DatabaseExecutionInterrupted) as captured:
                adapter.execute(config, f"SELECT * FROM {table} WITH (READCOMMITTEDLOCK)",
                                timeout_seconds=2, cancel_event=signal)
            assert captured.value.reason == "cancelled"
            assert captured.value.cancel_request_sent is False
            assert captured.value.server_termination_confirmed is False
            assert captured.value.write_outcome_unknown is False
            assert isinstance(captured.value.cancel_error, RuntimeError)
        finally:
            timer.cancel()


def test_sqlserver_real_interrupted_write_has_unknown_outcome(
    sqlserver_target: tuple[DbConnectionConfig, Engine],
) -> None:
    config, engine = sqlserver_target
    with blocked_table(config, engine) as table:
        with pytest.raises(DatabaseExecutionInterrupted) as captured:
            SqlServerAdapter().execute(config, f"UPDATE {table} SET value=9 WHERE id=1", timeout_seconds=1)
        assert captured.value.reason == "timeout"
        assert captured.value.cancel_request_sent is False
        assert captured.value.server_termination_confirmed is False
        assert captured.value.write_outcome_unknown is True
