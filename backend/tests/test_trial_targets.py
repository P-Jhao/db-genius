"""Trial SQL policy against disposable PostgreSQL and MySQL target databases."""

import os
from uuid import uuid4

import pytest
from sqlalchemy import inspect

from app.adapters import DbConnectionConfig, get_adapter
from app.adapters.relational import RelationalAdapter
from app.adapters.safety import UnsafeStatement


def _target(db_type: str) -> DbConnectionConfig:
    prefix = "SQLCHAT_TEST_PG" if db_type == "postgresql" else "SQLCHAT_TEST_MYSQL"
    def required(key: str) -> str:
        value = os.environ.get(f"{prefix}_{key}")
        if value is None:
            pytest.skip(f"{db_type} disposable target credentials are not configured")
        return value

    fields = {key: required(key) for key in ("HOST", "PORT", "DB", "USER", "PASSWORD")}
    return DbConnectionConfig(db_type, fields["HOST"], int(fields["PORT"]),
                              fields["DB"], fields["USER"], fields["PASSWORD"])


@pytest.mark.parametrize("db_type", ["postgresql", "mysql"])
def test_trial_reads_but_never_changes_disposable_target(db_type: str) -> None:
    config = _target(db_type)
    adapter = get_adapter(db_type)
    assert isinstance(adapter, RelationalAdapter)
    suffix = uuid4().hex[:12]
    table = f"s13_trial_{suffix}"
    copy = f"s13_trial_copy_{suffix}"
    with adapter._connection(config, 30) as connection:
        qualified = adapter._qualified_name(connection, table)
        copied = adapter._qualified_name(connection, copy)
        connection.exec_driver_sql(f"CREATE TABLE {qualified} (id INT PRIMARY KEY, label VARCHAR(20))")
        connection.exec_driver_sql(f"INSERT INTO {qualified} VALUES (1, 'original')")
        connection.commit()
    try:
        before = adapter.execute(config, f"SELECT id, label FROM {qualified}", trial_mode=True)
        assert before["data"] == [{"id": 1, "label": "original"}]
        select_into = (f"SELECT id INTO {copied} FROM {qualified}" if db_type == "postgresql"
                       else f"SELECT id INTO @s13_trial_value FROM {qualified}")
        for statement in (
            f"INSERT INTO {qualified} VALUES (2, 'forbidden')",
            f"UPDATE {qualified} SET label = 'forbidden' WHERE id = 1",
            select_into,
        ):
            with pytest.raises(UnsafeStatement):
                adapter.execute(config, statement, trial_mode=True)
        after = adapter.execute(config, f"SELECT id, label FROM {qualified}", trial_mode=True)
        assert after["data"] == before["data"]
        with adapter._connection(config, 30) as connection:
            assert not inspect(connection).has_table(copy)
    finally:
        with adapter._connection(config, 30) as connection:
            connection.exec_driver_sql(f"DROP TABLE IF EXISTS {copied}")
            connection.exec_driver_sql(f"DROP TABLE IF EXISTS {qualified}")
            connection.commit()
