"""Runs only with credentials for the isolated migration test containers."""

import os
import threading
from time import monotonic, sleep
from uuid import uuid4

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.adapters import DatabaseExecutionInterrupted, DbConnectionConfig, get_adapter
from app.adapters.safety import UnsafeStatement


def _config(db_type: str) -> DbConnectionConfig:
    prefix = "SQLCHAT_TEST_PG" if db_type == "postgresql" else "SQLCHAT_TEST_MYSQL"
    fields = {key: os.environ.get(f"{prefix}_{key}") for key in ("HOST", "PORT", "DB", "USER", "PASSWORD")}
    if any(value is None for value in fields.values()):
        pytest.skip(f"{db_type} isolated test credentials are not configured")
    return DbConnectionConfig(db_type, fields["HOST"], int(fields["PORT"]),
                              fields["DB"], fields["USER"], fields["PASSWORD"])


@pytest.mark.parametrize("db_type", ["mysql", "postgresql"])
def test_real_read_write_metadata_limits_and_special_password(db_type: str) -> None:
    config = _config(db_type)
    adapter = get_adapter(db_type)
    suffix = uuid4().hex[:10]
    table = f"s04 {suffix}"
    user = f"s04_{suffix}"
    special_password = "p@:/#word"
    with adapter._connection(config, 30) as connection:
        qualified = adapter._qualified_name(connection, table)
        if db_type == "mysql":
            connection.exec_driver_sql(
                f"CREATE TABLE {qualified} (id INT PRIMARY KEY, label VARCHAR(40) NULL COMMENT 'label note', "
                "INDEX label_idx (label)) COMMENT='test table'"
            )
            connection.exec_driver_sql(f"CREATE USER '{user}'@'%%' IDENTIFIED BY '{special_password}'")
            connection.exec_driver_sql(f"GRANT SELECT ON `{config.db_name}`.* TO '{user}'@'%%'")
        else:
            connection.exec_driver_sql(f"CREATE TABLE {qualified} (id INT PRIMARY KEY, label VARCHAR(40))")
            connection.exec_driver_sql(f"COMMENT ON TABLE {qualified} IS 'test table'")
            connection.exec_driver_sql(f"COMMENT ON COLUMN {qualified}.label IS 'label note'")
            connection.exec_driver_sql(f"CREATE INDEX label_idx_{suffix} ON {qualified} (label)")
            connection.exec_driver_sql(f"CREATE ROLE {user} LOGIN PASSWORD '{special_password}'")
            connection.exec_driver_sql(f"GRANT USAGE ON SCHEMA public TO {user}")
            connection.exec_driver_sql(f"GRANT SELECT ON {qualified} TO {user}")
        connection.commit()
    try:
        assert adapter.test_connection(config)
        write = adapter.execute(config, f"INSERT INTO {qualified} VALUES (1, '中文')")
        assert write["affectedRows"] == 1
        assert adapter.execute(config, f"UPDATE {qualified} SET label = 'updated' WHERE id = 1")["affectedRows"] == 1
        result = adapter.execute(config, f"SELECT * FROM {qualified}", trial_mode=True)
        assert result["data"] == [{"id": 1, "label": "updated"}]
        assert result["truncated"] is False
        assert adapter.execute(config, "SELECT 'DROP TABLE t' AS note", trial_mode=True)["data"] == [
            {"note": "DROP TABLE t"}
        ]
        assert adapter.execute(config, "SELECT '50%' AS percent", trial_mode=True)["data"] == [
            {"percent": "50%"}
        ]
        assert adapter.execute(config, f"SELECT id FROM {qualified} WHERE label LIKE '%dat%'",
                               trial_mode=True)["data"] == [{"id": 1}]
        with pytest.raises(UnsafeStatement):
            adapter.execute(config, f"DROP TABLE {qualified}")
        with pytest.raises(UnsafeStatement):
            adapter.execute(config, f"UPDATE {qualified} SET label = 'x'", trial_mode=True)
        many = ",".join(f"({number}, 'value')" for number in range(2, 103))
        adapter.execute(config, f"INSERT INTO {qualified} VALUES {many}")
        result = adapter.execute(config, f"SELECT * FROM {qualified} ORDER BY id")
        assert result["rowCount"] == 100
        assert result["truncated"] is True
        schema = adapter.extract_metadata(config)
        assert schema["incomplete"] is False
        entry = next(item for item in schema["tables"] if item["name"] == table)
        assert entry["rowCount"] == 102
        assert entry["comment"] == "test table"
        assert next(column for column in entry["columns"] if column["name"] == "label")["comment"] == "label note"
        assert any("label" in index["columns"] for index in entry["indexes"])
        assert f"## Table: {table}" in adapter.generate_document(config)
        special = DbConnectionConfig(db_type, config.host, config.port, config.db_name, user, special_password)
        assert adapter.test_connection(special)
        assert adapter.execute(special, f"SELECT COUNT(*) AS n FROM {qualified}")["data"] == [{"n": 102}]
        slow = "SELECT SLEEP(2)" if db_type == "mysql" else "SELECT pg_sleep(2)"
        with pytest.raises((SQLAlchemyError, TimeoutError)):
            adapter.execute(config, slow, timeout_seconds=1)
        if db_type == "mysql":
            started = monotonic()
            with pytest.raises((SQLAlchemyError, TimeoutError)):
                adapter.execute(config, f"UPDATE {qualified} SET label = 'slow' "
                               "WHERE id = 1 AND SLEEP(2) = 0", timeout_seconds=1)
            assert monotonic() - started < 3
        assert adapter.execute(config, f"DELETE FROM {qualified} WHERE id = 1")["affectedRows"] == 1
    finally:
        with adapter._connection(config, 30) as connection:
            connection.exec_driver_sql(f"DROP TABLE IF EXISTS {qualified}")
            if db_type == "mysql":
                connection.exec_driver_sql(f"DROP USER IF EXISTS '{user}'@'%%'")
            else:
                connection.exec_driver_sql(f"REVOKE ALL ON SCHEMA public FROM {user}")
                connection.exec_driver_sql(f"DROP ROLE IF EXISTS {user}")
            connection.commit()


def test_postgresql_failed_count_does_not_poison_other_tables() -> None:
    config = _config("postgresql")
    adapter = get_adapter("postgresql")
    suffix = uuid4().hex[:10]
    denied = f"a_s04_denied_{suffix}"
    allowed = f"z_s04_allowed_{suffix}"
    user = f"s04_{suffix}"
    with adapter._connection(config, 30) as connection:
        for table in (denied, allowed):
            connection.exec_driver_sql(f"CREATE TABLE public.{table} (id INT PRIMARY KEY)")
        connection.exec_driver_sql(f"INSERT INTO public.{allowed} VALUES (1)")
        connection.exec_driver_sql(f"CREATE ROLE {user} LOGIN PASSWORD 'p@:/#word'")
        connection.exec_driver_sql(f"GRANT USAGE ON SCHEMA public TO {user}")
        connection.exec_driver_sql(f"GRANT SELECT ON public.{allowed} TO {user}")
        connection.commit()
    try:
        restricted = DbConnectionConfig("postgresql", config.host, config.port, config.db_name,
                                        user, "p@:/#word")
        schema = adapter.extract_metadata(restricted)
        assert schema["incomplete"] is True
        assert denied in (schema["errorMessage"] or "")
        assert next(item for item in schema["tables"] if item["name"] == denied)["rowCount"] is None
        assert next(item for item in schema["tables"] if item["name"] == allowed)["rowCount"] == 1
    finally:
        with adapter._connection(config, 30) as connection:
            connection.exec_driver_sql(f"DROP TABLE IF EXISTS public.{denied}, public.{allowed}")
            connection.exec_driver_sql(f"REVOKE ALL ON SCHEMA public FROM {user}")
            connection.exec_driver_sql(f"DROP ROLE IF EXISTS {user}")
            connection.commit()


@pytest.mark.parametrize("db_type", ["mysql", "postgresql"])
def test_real_running_slow_query_cancel(db_type: str) -> None:
    config = _config(db_type)
    adapter = get_adapter(db_type)
    marker = f"s08_{uuid4().hex}"
    statement = (f"SELECT COUNT(*) FROM information_schema.COLUMNS a "
                 f"CROSS JOIN information_schema.COLUMNS b "
                 f"CROSS JOIN information_schema.COLUMNS c "
                 f"CROSS JOIN information_schema.COLUMNS d /* {marker} */" if db_type == "mysql"
                 else f"SELECT pg_sleep(10) /* {marker} */")
    observer_sql = (
        f"SELECT COUNT(*) FROM information_schema.PROCESSLIST WHERE ID <> CONNECTION_ID() "
        f"AND INFO IS NOT NULL AND LOCATE('{marker}', INFO) > 0"
        if db_type == "mysql" else
        "SELECT COUNT(*) FROM pg_stat_activity WHERE pid <> pg_backend_pid() "
        "AND state = 'active' AND wait_event_type = 'Timeout' AND wait_event = 'PgSleep'"
    )
    signal = threading.Event()
    errors: list[Exception] = []

    def run() -> None:
        try:
            adapter.execute(config, statement, cancel_event=signal, timeout_seconds=15)
        except Exception as exc:  # noqa: BLE001 - assert the exact outcome after joining the worker
            errors.append(exc)

    worker = threading.Thread(target=run)
    worker.start()
    try:
        with adapter._connection(config, 5) as observer:
                deadline = monotonic() + 5
                while int(observer.exec_driver_sql(observer_sql).scalar_one()) == 0:
                    assert monotonic() < deadline, "Slow query never became visible to the observer"
                    observer.rollback()  # pg_stat_activity snapshots are cached for a transaction.
                    sleep(0.05)
        signal.set()
        worker.join(6)
        assert not worker.is_alive(), "Database driver did not return after cancellation"
        assert len(errors) == 1
        assert isinstance(errors[0], DatabaseExecutionInterrupted)
        assert errors[0].reason == "cancelled"
        assert errors[0].cancel_request_sent is True
        assert errors[0].server_termination_confirmed is True
        assert errors[0].write_outcome_unknown is False
    finally:
        signal.set()
        worker.join(16)
