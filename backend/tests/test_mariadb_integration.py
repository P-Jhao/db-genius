"""Real MariaDB acceptance against an explicitly configured isolated target."""

from __future__ import annotations

import os
import threading
from collections.abc import Iterator
from time import monotonic, sleep
from uuid import uuid4

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.adapters import DatabaseExecutionInterrupted, DbConnectionConfig
from app.adapters.mysql_family import MariaDbAdapter
from app.adapters.safety import UnsafeStatement


def _config() -> DbConnectionConfig:
    fields = {key: os.environ.get(f"SQLCHAT_TEST_MARIA_{key}")
              for key in ("HOST", "PORT", "DB", "USER", "PASSWORD")}
    if any(value is None for value in fields.values()):
        pytest.skip("real MariaDB isolated test credentials are not configured")
    host, port, name, user, password = (fields[key] for key in ("HOST", "PORT", "DB", "USER", "PASSWORD"))
    assert host is not None and port is not None and name is not None
    assert user is not None and password is not None
    if host not in {"localhost", "127.0.0.1"} or int(port) != 13307:
        raise ValueError("real MariaDB tests require the dedicated loopback target on port 13307")
    return DbConnectionConfig("mariadb", host, int(port), name, user, password)


@pytest.fixture
def maria_table() -> Iterator[tuple[MariaDbAdapter, DbConnectionConfig, str, str]]:
    adapter, config = MariaDbAdapter(), _config()
    table = f"s12 order`items {uuid4().hex}"
    with adapter._connection(config, 10) as connection:
        quoted = adapter._qualified_name(connection, table)
        connection.exec_driver_sql(
            f"CREATE TABLE {quoted} (id INT PRIMARY KEY COMMENT 'primary identifier', "
            "`label value` VARCHAR(80) NULL COMMENT '中文字段', amount DECIMAL(8,2) NOT NULL, "
            "INDEX label_idx (`label value`)) ENGINE=InnoDB COMMENT='验收订单'"
        )
        connection.commit()
    try:
        yield adapter, config, table, quoted
    finally:
        with adapter._connection(config, 10) as connection:
            connection.exec_driver_sql(f"DROP TABLE IF EXISTS {quoted}")
            connection.commit()
            assert connection.exec_driver_sql(
                "SELECT COUNT(*) FROM information_schema.TABLES "
                "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s", (config.db_name, table)
            ).scalar_one() == 0


def test_real_mariadb_connection_read_write_metadata_and_limits(
    maria_table: tuple[MariaDbAdapter, DbConnectionConfig, str, str],
) -> None:
    adapter, config, table, quoted = maria_table
    assert adapter.test_connection(config) is True
    values = ",".join(f"({number}, '中文{number}', {number}.50)" for number in range(1, 126))
    assert adapter.execute(config, f"INSERT INTO {quoted} VALUES {values}")["affectedRows"] == 125
    assert adapter.execute(config, f"UPDATE {quoted} SET `label value` = NULL WHERE id = 1")["affectedRows"] == 1
    row = adapter.execute(config, f"SELECT * FROM {quoted} WHERE id = 1", trial_mode=True)
    assert row["data"] == [{"id": 1, "label value": None, "amount": "1.50"}]
    limited = adapter.execute(config, f"SELECT id FROM {quoted} ORDER BY id")
    assert limited["rowCount"] == 100 and limited["truncated"] is True
    assert limited["data"] == [{"id": number} for number in range(1, 101)]
    bounded = adapter.execute(config, f"SELECT id FROM {quoted} ORDER BY id", max_rows=3)
    assert bounded["data"] == [{"id": 1}, {"id": 2}, {"id": 3}] and bounded["truncated"] is True
    metadata = adapter.extract_metadata(config)
    assert metadata["dbType"] == "mariadb" and metadata["incomplete"] is False
    entry = next(item for item in metadata["tables"] if item["name"] == table)
    assert entry["rowCount"] == 125 and entry["comment"] == "验收订单"
    columns = {column["name"]: column for column in entry["columns"]}
    assert columns["id"]["primaryKey"] is True and columns["id"]["nullable"] is False
    assert columns["id"]["comment"] == "primary identifier"
    assert columns["label value"]["comment"] == "中文字段" and columns["label value"]["nullable"] is True
    assert columns["amount"]["type"] == "DECIMAL(8, 2)"
    assert any(index["columns"] == ["label value"] for index in entry["indexes"])
    assert f"## Table: {table}" in adapter.generate_document(config)
    assert adapter.execute(config, f"DELETE FROM {quoted} WHERE id = 125")["affectedRows"] == 1
    with adapter._connection(config, 5) as independent:
        assert independent.exec_driver_sql(f"SELECT COUNT(*) FROM {quoted}").scalar_one() == 124
        assert independent.exec_driver_sql(
            f"SELECT `label value` FROM {quoted} WHERE id = 1"
        ).scalar_one() is None


def test_real_mariadb_failed_statement_rolls_back_and_guards_preserve_rows(
    maria_table: tuple[MariaDbAdapter, DbConnectionConfig, str, str],
) -> None:
    adapter, config, _table, quoted = maria_table
    adapter.execute(config, f"INSERT INTO {quoted} VALUES (1, 'original', 1.50)")
    with pytest.raises(SQLAlchemyError):
        adapter.execute(config, f"INSERT INTO {quoted} VALUES (2, 'partial', 2.50), (1, 'duplicate', 9.50)")
    for sql, trial in [(f"UPDATE {quoted} SET amount = 9", True),
                       (f"DELETE FROM {quoted}", True), (f"DROP TABLE {quoted}", False),
                       (f"TRUNCATE TABLE {quoted}", False),
                       (f"ALTER TABLE {quoted} DROP COLUMN amount", False),
                       (f"SELECT 1; DELETE FROM {quoted}", False)]:
        with pytest.raises(UnsafeStatement):
            adapter.execute(config, sql, trial_mode=trial)
    assert adapter.execute(config, "SELECT 'DROP TABLE t 50%' AS note", trial_mode=True)["data"] == [
        {"note": "DROP TABLE t 50%"},
    ]
    with adapter._connection(config, 5) as independent:
        assert [dict(row._mapping) for row in independent.exec_driver_sql(f"SELECT * FROM {quoted}")] == [
            {"id": 1, "label value": "original", "amount": pytest.approx(1.50)},
        ]


def test_real_mariadb_timeout_stops_server_query() -> None:
    config, adapter = _config(), MariaDbAdapter()
    marker = f"s12_timeout_{uuid4().hex}"
    started = monotonic()
    with pytest.raises(DatabaseExecutionInterrupted) as raised:
        adapter.execute(config, f"SELECT SLEEP(8) /* {marker} */", timeout_seconds=1)
    assert monotonic() - started < 5
    assert raised.value.reason == "timeout" and raised.value.write_outcome_unknown is False
    with adapter._connection(config, 5) as observer:
        assert observer.exec_driver_sql(
            "SELECT COUNT(*) FROM information_schema.PROCESSLIST WHERE ID <> CONNECTION_ID() "
            "AND INFO IS NOT NULL AND LOCATE(%s, INFO) > 0", (marker,)
        ).scalar_one() == 0


def test_real_mariadb_inflight_cancel_confirms_kill() -> None:
    config, adapter = _config(), MariaDbAdapter()
    marker = f"s12_cancel_{uuid4().hex}"
    signal = threading.Event()
    errors: list[Exception] = []

    def run() -> None:
        try:
            adapter.execute(config, f"SELECT SLEEP(12) /* {marker} */",
                            cancel_event=signal, timeout_seconds=20)
        except Exception as exc:  # noqa: BLE001 - asserted after the worker returns
            errors.append(exc)

    worker = threading.Thread(target=run)
    worker.start()
    try:
        with adapter._connection(config, 5) as observer:
            deadline = monotonic() + 5
            while observer.exec_driver_sql(
                "SELECT COUNT(*) FROM information_schema.PROCESSLIST WHERE ID <> CONNECTION_ID() "
                "AND INFO IS NOT NULL AND LOCATE(%s, INFO) > 0", (marker,)
            ).scalar_one() == 0:
                assert monotonic() < deadline, "MariaDB query never became visible"
                observer.rollback()
                sleep(0.05)
        signal.set()
        worker.join(6)
        assert not worker.is_alive(), "MariaDB driver did not return after KILL QUERY"
        assert len(errors) == 1 and isinstance(errors[0], DatabaseExecutionInterrupted)
        error = errors[0]
        assert error.reason == "cancelled" and error.cancel_request_sent is True
        assert error.server_termination_confirmed is True and error.write_outcome_unknown is False
        with adapter._connection(config, 5) as observer:
            assert observer.exec_driver_sql(
                "SELECT COUNT(*) FROM information_schema.PROCESSLIST WHERE ID <> CONNECTION_ID() "
                "AND INFO IS NOT NULL AND LOCATE(%s, INFO) > 0", (marker,)
            ).scalar_one() == 0
    finally:
        signal.set()
        worker.join(21)
