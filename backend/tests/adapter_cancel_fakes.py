"""Test doubles for synchronous database cancellation protocol tests."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import Mock

import pytest

from app.adapters import DbConnectionConfig


class DriverError(Exception):
    def __init__(self, code: int | None = None, sqlstate: str | None = None) -> None:
        self.sqlstate = sqlstate
        super().__init__(code, "query interrupted")


class Result:
    returns_rows = False
    rowcount = 1

    def scalar_one(self) -> int:
        return 42

    def close(self) -> None:
        return None


class FakeConnection:
    def __init__(self, statement_result: Mock) -> None:
        self.statement_result = statement_result
        self.connection = Mock(driver_connection=Mock())
        self.commits = 0
        self.rollbacks = 0
        self.on_commit: Mock | None = None

    def exec_driver_sql(self, statement: str) -> Result:
        if statement == "SELECT CONNECTION_ID()":
            return Result()
        return self.statement_result(statement)

    def execution_options(self, **_options: object) -> FakeConnection:
        return self

    def commit(self) -> None:
        self.commits += 1
        if self.on_commit is not None:
            self.on_commit()

    def rollback(self) -> None:
        self.rollbacks += 1


def config(db_type: str) -> DbConnectionConfig:
    return DbConnectionConfig(db_type, "localhost", 5432 if db_type == "postgresql" else 3306,
                              "isolated", "user", "password")


def install_connection(monkeypatch: pytest.MonkeyPatch, adapter: object,
                       execution: FakeConnection, control: FakeConnection | None = None) -> None:
    calls = 0

    @contextmanager
    def connection(_config: DbConnectionConfig, _timeout: int) -> Iterator[FakeConnection]:
        nonlocal calls
        calls += 1
        yield execution if calls == 1 else control or execution

    monkeypatch.setattr(adapter, "_connection", connection)
    monkeypatch.setattr(adapter, "_set_timeout", lambda *_args: None)
