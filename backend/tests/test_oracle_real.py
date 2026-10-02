"""Actual python-oracledb Thin current-user metadata, types and cancellation."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import uuid4

import pytest
from native_database_fixtures import oracle_target as oracle_fixture
from native_database_fixtures import wait_oracle_ddl
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError

from app.adapters.cancellation import DatabaseExecutionInterrupted
from app.adapters.oracle import OracleAdapter
from app.adapters.safety import UnsafeStatement
from app.adapters.types import DbConnectionConfig

oracle_target = oracle_fixture


def test_oracle_real_current_user_names_decimal_unicode_lobs(oracle_target: tuple[DbConnectionConfig, Engine]) -> None:
    config, engine = oracle_target
    adapter = OracleAdapter()
    assert adapter.test_connection(config)
    table = "native_" + uuid4().hex[:12]
    created = False
    try:
        adapter.execute(config, f'CREATE TABLE {table} (id NUMBER(10) PRIMARY KEY, "id" NUMBER(10),'
            '"MixedName" NVARCHAR2(50), amount NUMBER(38,12) NOT NULL, content CLOB, payload BLOB, created TIMESTAMP(6))')
        created = True
        adapter.execute(config, f"INSERT INTO {table} VALUES (1,2,N'中文🙂',12345678901234567890.123456789012,"
            "TO_CLOB('Unicode 文本'),HEXTORAW('010203'),TIMESTAMP '2026-10-01 02:03:04.123456')")
        with engine.begin() as connection:
            connection.exec_driver_sql(f"COMMENT ON TABLE {table} IS '当前用户真实表'")
            connection.exec_driver_sql(f"CREATE INDEX ix_{table} ON {table} (amount)")
        wait_oracle_ddl(engine, [table.upper(), f"ix_{table}".upper()])
        result = adapter.execute(config, f"SELECT * FROM {table}", trial_mode=True)
        assert result["data"] == [{"ID": 1, "id": 2, "MixedName": "中文🙂", "AMOUNT": "12345678901234567890.123456789012",
                                  "CONTENT": "Unicode 文本", "PAYLOAD": "AQID", "CREATED": "2026-10-01T02:03:04.123456"}]
        metadata = adapter.extract_metadata(config)
        assert metadata["incomplete"] is False, metadata["errorMessage"]
        actual = next(value for value in metadata["tables"] if value["name"] == table.upper())
        assert actual["rowCount"] == 1 and actual["comment"] == "当前用户真实表"
        columns = {column["name"]: column for column in actual["columns"]}
        assert columns["ID"]["primaryKey"] is True and columns["id"]["primaryKey"] is False
        assert columns["AMOUNT"]["nullable"] is False and columns["AMOUNT"]["type"] == "NUMBER(38, 12)"
        assert metadata["schemaName"] and metadata["databaseName"] == config.db_name
        assert any(index["columns"] == ["AMOUNT"] for index in actual["indexes"])
        assert "当前用户真实表" in adapter.generate_document(config)
    finally:
        if created:
            with engine.begin() as connection:
                connection.exec_driver_sql(f"DROP TABLE {table} PURGE")


def test_oracle_real_allowed_writes_read_limit_and_trial(oracle_target: tuple[DbConnectionConfig, Engine]) -> None:
    config, engine = oracle_target
    adapter = OracleAdapter()
    table = "native_" + uuid4().hex[:12]
    sequence = "seq_" + uuid4().hex[:12]
    created = False
    sequence_created = False
    try:
        adapter.execute(config, f"CREATE TABLE {table} (id NUMBER(10), value NUMBER(10))")
        created = True
        with engine.begin() as connection:
            connection.exec_driver_sql(f"INSERT INTO {table} VALUES (:1,:2)", [(value, value) for value in range(201)])
            connection.exec_driver_sql(f"CREATE SEQUENCE {sequence}")
            sequence_created = True
        wait_oracle_ddl(engine, [table.upper(), sequence.upper()])
        limited = adapter.execute(config, f"SELECT * FROM {table} ORDER BY id", trial_mode=True)
        assert limited["rowCount"] == 100 and limited["truncated"] is True
        assert adapter.execute(config, f"UPDATE {table} SET value=9 WHERE id=1")["affectedRows"] == 1
        assert adapter.execute(config, f"DELETE FROM {table} WHERE id=200")["affectedRows"] == 1
        for sql in (f"DROP TABLE {table}", f"TRUNCATE TABLE {table}", f"ALTER TABLE {table} DROP COLUMN value",
                    f"SELECT * FROM {table} FOR UPDATE", f"SELECT {sequence}.NEXTVAL FROM DUAL"):
            with pytest.raises(UnsafeStatement):
                adapter.execute(config, sql, trial_mode=True)
        assert adapter.execute(config, f"SELECT {sequence}.NEXTVAL AS number_value FROM DUAL")["data"] == [{"NUMBER_VALUE": 1}]
        assert adapter.execute(config, f"WITH c AS (SELECT * FROM {table}) SELECT COUNT(*) AS total FROM c", trial_mode=True)["data"] == [{"TOTAL": 200}]
    finally:
        with engine.begin() as connection:
            if created:
                connection.exec_driver_sql(f"DROP TABLE {table} PURGE")
            if sequence_created:
                connection.exec_driver_sql(f"DROP SEQUENCE {sequence}")


@contextmanager
def blocked_table(engine: Engine) -> Iterator[str]:
    table = "blocked_" + uuid4().hex[:12]
    with engine.begin() as connection:
        connection.exec_driver_sql(f"CREATE TABLE {table} (id NUMBER(10), value NUMBER(10))")
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
            connection.exec_driver_sql(f"DROP TABLE {table} PURGE")


def test_oracle_real_cancel_truth_and_unknown_write(oracle_target: tuple[DbConnectionConfig, Engine]) -> None:
    config, engine = oracle_target
    signal = threading.Event()
    with blocked_table(engine) as table:
        timer = threading.Timer(0.4, signal.set)
        timer.start()
        try:
            with pytest.raises(DatabaseExecutionInterrupted) as captured:
                OracleAdapter().execute(config, f"UPDATE {table} SET value=9 WHERE id=1", cancel_event=signal, timeout_seconds=5)
            assert captured.value.reason == "cancelled"
            assert captured.value.cancel_request_sent is True
            cause = captured.value.__cause__
            details = getattr(cause.orig, "args", ()) if isinstance(cause, DBAPIError) else ()
            info = {"cause_type": type(cause).__name__, "code": getattr(details[0], "code", None) if details else None,
                    "full_code": getattr(details[0], "full_code", None) if details else None}
            print("Oracle actual write cancellation:", info)
            assert captured.value.server_termination_confirmed is (info["code"] == 1013), info
            assert info["code"] == 1013 or info["full_code"] == "DPY-4011", info
            assert captured.value.write_outcome_unknown is True
            assert captured.value.cancel_error is None
        finally:
            timer.cancel()


def test_oracle_real_timeout_keeps_unknown_write(oracle_target: tuple[DbConnectionConfig, Engine]) -> None:
    config, engine = oracle_target
    with blocked_table(engine) as table:
        with pytest.raises(DatabaseExecutionInterrupted) as captured:
            OracleAdapter().execute(config, f"UPDATE {table} SET value=9 WHERE id=1", timeout_seconds=1)
        assert captured.value.reason == "timeout"
        assert captured.value.write_outcome_unknown is True


def test_oracle_real_read_cancel_reports_actual_driver_confirmation(
    oracle_target: tuple[DbConnectionConfig, Engine],
) -> None:
    config, engine = oracle_target
    function = "pause_" + uuid4().hex[:12]
    created = False
    signal = threading.Event()
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("BEGIN DBMS_SESSION.SLEEP(0); END;")
            connection.exec_driver_sql(f"CREATE FUNCTION {function} RETURN NUMBER IS BEGIN "
                                       "DBMS_SESSION.SLEEP(3); RETURN 1; END;")
        created = True
        timer = threading.Timer(0.4, signal.set)
        timer.start()
        try:
            with pytest.raises(DatabaseExecutionInterrupted) as captured:
                OracleAdapter().execute(config, f"SELECT {function}() AS result FROM DUAL",
                                        cancel_event=signal, timeout_seconds=5)
            cause = captured.value.__cause__
            details = getattr(cause.orig, "args", ()) if isinstance(cause, DBAPIError) else ()
            code = getattr(details[0], "code", None) if details else None
            full_code = getattr(details[0], "full_code", None) if details else None
            print("Oracle actual read cancellation:", {"code": code, "full_code": full_code})
            assert code == 1013 or full_code == "DPY-4011", {"code": code, "full_code": full_code}
            assert captured.value.cancel_request_sent is True
            assert captured.value.server_termination_confirmed is (code == 1013)
            assert captured.value.write_outcome_unknown is False
            assert captured.value.cancel_error is None
        finally:
            timer.cancel()
    finally:
        if created:
            with engine.begin() as connection:
                connection.exec_driver_sql(f"DROP FUNCTION {function}")
