"""Opt-in isolated native instances; credentials remain in ignored runtime files."""

from __future__ import annotations

import os
import re
import time
from collections.abc import Iterator
from pathlib import Path
from typing import NamedTuple
from uuid import uuid4

import pytest
from sqlalchemy.engine import Engine

from app.adapters.sqlserver import SqlServerAdapter
from app.adapters.types import DbConnectionConfig


def wait_oracle_ddl(engine: Engine, names: list[str], *, age_seconds: int = 5) -> None:
    """Wait for this fixture's server-side DDL timestamp boundary, without retrying product SQL."""
    if not names or len(set(names)) != len(names) or age_seconds < 1:
        raise ValueError("Oracle fixture requires unique object names and a positive stable age")
    bindings = {f"name_{index}": name for index, name in enumerate(names)}
    placeholders = ",".join(f":{name}" for name in bindings)
    deadline = time.monotonic() + 20
    with engine.connect() as connection:
        while True:
            count, age = connection.exec_driver_sql(
                "SELECT COUNT(*), MIN((SYSDATE-last_ddl_time)*86400) FROM user_objects "
                f"WHERE object_name IN ({placeholders})", bindings,
            ).one()
            if count != len(names) or age is None:
                raise ValueError("Oracle fixture DDL objects are absent or ambiguous")
            if float(age) >= age_seconds:
                return
            if time.monotonic() >= deadline:
                raise TimeoutError("Oracle fixture server DDL timestamp did not reach a stable boundary")
            time.sleep(0.1)


class NativeTarget(NamedTuple):
    config: DbConnectionConfig
    engine: Engine

    def __repr__(self) -> str:
        return "NativeTarget(config=<credentials redacted>, engine=<isolated target>)"


def runtime_values(variable: str) -> dict[str, str]:
    location = os.environ.get(variable)
    if location is None:
        pytest.skip(f"Set {variable} to the ignored real-instance runtime file")
    result: dict[str, str] = {}
    for line in Path(location).read_text(encoding="utf-8-sig").splitlines():
        if line and not line.lstrip().startswith("#"):
            key, separator, value = line.partition("=")
            if not separator:
                raise ValueError("Runtime file contains an invalid assignment")
            result[key.strip()] = value.strip().strip('"').strip("'")
    return result


@pytest.fixture(scope="module")
def sqlserver_target() -> Iterator[tuple[DbConnectionConfig, Engine]]:
    runtime = runtime_values("SQLCHAT_SQLSERVER_RUNTIME")
    password = runtime.get("MSSQL_SA_PASSWORD")
    if password is None or not password:
        raise ValueError("SQL Server runtime password is required")
    adapter = SqlServerAdapter()
    admin = DbConnectionConfig("sqlserver", "127.0.0.1", 14333, "master", "sa", password)
    admin_engine = adapter._engine(admin, 30)
    name = "s12_native_" + uuid4().hex[:16]
    if not re.fullmatch(r"s12_native_[a-f0-9]{16}", name):
        raise ValueError("Unsafe fixture database name")
    engine: Engine | None = None
    try:
        with admin_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            connection.exec_driver_sql(f"CREATE DATABASE [{name}]")
        target = DbConnectionConfig("sqlserver", admin.host, admin.port, name, admin.username, password)
        engine = adapter._engine(target, 30)
        yield NativeTarget(target, engine)
    finally:
        if engine is not None:
            engine.dispose()
        with admin_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            connection.exec_driver_sql(f"ALTER DATABASE [{name}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE")
            connection.exec_driver_sql(f"DROP DATABASE [{name}]")
        admin_engine.dispose()


@pytest.fixture(scope="module")
def oracle_target() -> Iterator[tuple[DbConnectionConfig, Engine]]:
    from app.adapters.oracle import OracleAdapter
    runtime = runtime_values("SQLCHAT_ORACLE_RUNTIME")
    required = ("ORACLE_HOST", "ORACLE_PORT", "ORACLE_SERVICE", "ORACLE_USERNAME", "ORACLE_PASSWORD")
    if any(not runtime.get(name) for name in required):
        raise ValueError("Oracle runtime requires explicit host/port/service/username/password")
    config = DbConnectionConfig("oracle", runtime["ORACLE_HOST"], int(runtime["ORACLE_PORT"]),
                                runtime["ORACLE_SERVICE"], runtime["ORACLE_USERNAME"], runtime["ORACLE_PASSWORD"])
    engine = OracleAdapter()._engine(config, 30)
    try:
        yield NativeTarget(config, engine)
    finally:
        engine.dispose()
