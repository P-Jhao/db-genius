"""S11 comparison through isolated PostgreSQL/MySQL databases and the real adapters."""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Self
from uuid import uuid4

import pytest
from test_model_protocol import Provider, frame, model

from app.adapters import DbConnectionConfig
from app.adapters.mysql import MySqlAdapter
from app.adapters.postgresql import PostgreSqlAdapter
from app.agent.graph import RunContext, run_graph
from app.agent.streaming import ModelStream
from app.agent.tools import RunTools
from app.agent.types import ChatRequest, Usage
from app.core.errors import BusinessError
from app.models import DbConfig
from app.services import database_tools, schema_diff

USER_ID = 711
PRE_ID = 7111
TEST_ID = 7112


@dataclass(frozen=True)
class Targets:
    pre: DbConnectionConfig
    test: DbConnectionConfig


def _admin_config(db_type: str) -> DbConnectionConfig:
    prefix = "SQLCHAT_TEST_PG" if db_type == "postgresql" else "SQLCHAT_TEST_MYSQL"
    values = {key: os.environ.get(f"{prefix}_{key}") for key in ("HOST", "PORT", "DB", "USER", "PASSWORD")}
    if any(value is None for value in values.values()):
        pytest.skip(f"Isolated {db_type} target credentials are required")
    host, port, database, username, password = (values[key] for key in
                                                 ("HOST", "PORT", "DB", "USER", "PASSWORD"))
    assert host is not None and port is not None and database is not None
    assert username is not None and password is not None
    return DbConnectionConfig(db_type, host, int(port), database, username, password)


def _adapter(db_type: str) -> MySqlAdapter | PostgreSqlAdapter:
    if db_type == "postgresql":
        return PostgreSqlAdapter()
    if db_type == "mysql":
        return MySqlAdapter()
    raise ValueError(f"Unsupported isolated target: {db_type}")


@contextmanager
def temporary_pair(db_type: str) -> Iterator[Targets]:
    admin = _admin_config(db_type)
    adapter = _adapter(db_type)
    suffix = uuid4().hex[:10]
    pre_name = f"s11_pre_{suffix}"
    test_name = f"s11_test_{suffix}"
    names = (pre_name, test_name)
    engine = adapter._engine(admin, 30)
    quote = engine.dialect.identifier_preparer.quote_identifier
    created: list[str] = []
    try:
        for name in names:
            with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
                connection.exec_driver_sql(f"CREATE DATABASE {quote(name)}")
            created.append(name)
        pre = DbConnectionConfig(db_type, admin.host, admin.port, pre_name, admin.username, admin.password)
        test = DbConnectionConfig(db_type, admin.host, admin.port, test_name, admin.username, admin.password)
        for target, desired in ((pre, False), (test, True)):
            target_engine = adapter._engine(target, 30)
            try:
                with target_engine.begin() as connection:
                    connection.exec_driver_sql("CREATE TABLE orders ("
                                               "id INTEGER PRIMARY KEY, "
                                               f"status VARCHAR({40 if desired else 20}) "
                                               f"{'NULL' if desired else 'NOT NULL'}, "
                                               f"{'new_note TEXT NOT NULL' if desired else 'old_note TEXT NULL'})")
                    connection.exec_driver_sql(f"CREATE TABLE {'fresh' if desired else 'retired'} "
                                               "(id INTEGER PRIMARY KEY)")
            finally:
                target_engine.dispose()
        yield Targets(pre, test)
    finally:
        try:
            for name in reversed(created):
                with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
                    if db_type == "postgresql":
                        connection.exec_driver_sql(f"DROP DATABASE IF EXISTS {quote(name)} WITH (FORCE)")
                    else:
                        connection.exec_driver_sql(f"DROP DATABASE IF EXISTS {quote(name)}")
        finally:
            engine.dispose()


def install_configs(monkeypatch: pytest.MonkeyPatch, targets: Targets) -> None:
    configs = {PRE_ID: targets.pre, TEST_ID: targets.test}
    rows = {db_id: SimpleNamespace(user_id=USER_ID, status=1, db_type=target.db_type)
            for db_id, target in configs.items()}

    class Session:
        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def get(self, _model: object, db_id: int) -> SimpleNamespace | None:
            if _model is not DbConfig:
                raise TypeError("Expected DbConfig lookup")
            return rows.get(db_id)

        def expunge(self, _row: object) -> None:
            return None

    monkeypatch.setattr(database_tools, "SessionLocal", Session)

    def connection_for(row: object) -> DbConnectionConfig:
        if row is rows[PRE_ID]:
            return configs[PRE_ID]
        if row is rows[TEST_ID]:
            return configs[TEST_ID]
        raise ValueError("Unknown test database configuration")

    monkeypatch.setattr(database_tools, "connection_for", connection_for)


def assert_removed(db_type: str, names: tuple[str, str]) -> None:
    engine = _adapter(db_type)._engine(_admin_config(db_type), 30)
    try:
        with engine.connect() as connection:
            query = ("SELECT datname FROM pg_database" if db_type == "postgresql"
                     else "SHOW DATABASES")
            remaining = {str(row[0]) for row in connection.exec_driver_sql(query)}
            assert not set(names) & remaining
    finally:
        engine.dispose()


def assert_direction(report: dict[str, object], targets: Targets) -> None:
    assert report["success"] is True and report["complete"] is True
    assert report["preDatabase"] == targets.pre.db_name
    assert report["testDatabase"] == targets.test.db_name
    assert report["newTables"] == [{"table": "fresh", "columnCount": 1}]
    assert report["droppedTables"] == [{"table": "retired", "columnCount": 1}]
    altered = report["alteredTables"]
    assert isinstance(altered, list) and len(altered) == 1
    assert altered[0]["table"] == "orders"
    changes = altered[0]["changes"]
    assert {(item["change"], item["column"]) for item in changes} == {
        ("ADD_COLUMN", "new_note"), ("DROP_COLUMN", "old_note"),
        ("MODIFY_COLUMN", "status"), ("MODIFY_NULLABLE", "status"),
    }
    nullable = next(item for item in changes if item["change"] == "MODIFY_NULLABLE")
    assert nullable["preNullable"] is False and nullable["testNullable"] is True
    modified = next(item for item in changes if item["change"] == "MODIFY_COLUMN")
    assert "20" in modified["preType"] and "40" in modified["testType"]
    pre_schema, test_schema = report["preSchema"], report["testSchema"]
    assert isinstance(pre_schema, dict) and isinstance(test_schema, dict)
    assert pre_schema["databaseName"] == targets.pre.db_name
    assert test_schema["databaseName"] == targets.test.db_name
    fresh = next(table for table in test_schema["tables"] if table["name"] == "fresh")
    assert fresh["columns"][0]["name"] == "id"
    assert "INT" in fresh["columns"][0]["type"]
    assert fresh["columns"][0]["nullable"] is False and fresh["columns"][0]["primaryKey"] is True
    orders = next(table for table in test_schema["tables"] if table["name"] == "orders")
    note = next(column for column in orders["columns"] if column["name"] == "new_note")
    assert note["type"] == "TEXT" and note["nullable"] is False


@pytest.mark.parametrize("db_type", ["postgresql", "mysql"])
def test_real_target_schema_diff_direction_and_ownership(
    monkeypatch: pytest.MonkeyPatch, db_type: str,
) -> None:
    with temporary_pair(db_type) as targets:
        install_configs(monkeypatch, targets)
        report = schema_diff.compare_databases(USER_ID, PRE_ID, TEST_ID)
        assert_direction(report, targets)
        reversed_report = schema_diff.compare_databases(USER_ID, TEST_ID, PRE_ID)
        assert reversed_report["newTables"] == [{"table": "retired", "columnCount": 1}]
        assert reversed_report["droppedTables"] == [{"table": "fresh", "columnCount": 1}]
        with pytest.raises(BusinessError) as denied:
            schema_diff.compare_databases(USER_ID + 1, PRE_ID, TEST_ID)
        assert denied.value.code == 404
    assert_removed(db_type, (targets.pre.db_name, targets.test.db_name))


@pytest.fixture
def provider() -> Iterator[Provider]:
    service = Provider([])
    thread = threading.Thread(target=service.serve_forever, daemon=True)
    thread.start()
    yield service
    service.shutdown()
    service.server_close()
    thread.join(timeout=2)


def _call(name: str, arguments: dict[str, object], call_id: str) -> list[bytes]:
    return [frame({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": call_id,
             "function": {"name": name, "arguments": json.dumps(arguments)}}]}}]}), frame("[DONE]")]


def _answer(content: str) -> list[bytes]:
    return [frame({"choices": [{"delta": {"content": content}}]}), frame("[DONE]")]


@pytest.mark.asyncio
@pytest.mark.parametrize("cross_engine", [False, True])
async def test_graph_uses_real_target_diff_and_cross_engine_guard(
    monkeypatch: pytest.MonkeyPatch, provider: Provider, cross_engine: bool,
) -> None:
    with temporary_pair("postgresql") as postgres:
        if cross_engine:
            with temporary_pair("mysql") as mysql:
                await _run_graph_case(monkeypatch, provider, Targets(postgres.pre, mysql.test), True)
            assert_removed("mysql", (mysql.pre.db_name, mysql.test.db_name))
        else:
            await _run_graph_case(monkeypatch, provider, postgres, False)
    assert_removed("postgresql", (postgres.pre.db_name, postgres.test.db_name))


async def _run_graph_case(monkeypatch: pytest.MonkeyPatch, provider: Provider,
                          targets: Targets, cross_engine: bool) -> None:
    install_configs(monkeypatch, targets)
    calls: list[tuple[int, int, int]] = []
    original = schema_diff.compare_databases

    def observed(user_id: int, pre_id: int, test_id: int) -> dict[str, object]:
        calls.append((user_id, pre_id, test_id))
        return original(user_id, pre_id, test_id)

    monkeypatch.setattr(schema_diff, "compare_databases", observed)
    provider.replies = [_call("compareDatabases", {"pre_id": PRE_ID, "test_id": TEST_ID}, "compare")]
    if not cross_engine:
        provider.replies += [_call("doTerminate", {"reason": "report ready"}, "terminate"),
                             _answer("pre to test: add fresh, remove retired, alter orders.")]
    request = ChatRequest.model_validate({"message": "Compare selected databases", "preDbConfigId": PRE_ID,
                                          "testDbConfigId": TEST_ID, "confirmedIntent": "db_compare"})
    events: list[tuple[str, object]] = []

    async def emit(kind: str, content: object, _step: int) -> None:
        events.append((kind, content))

    context = RunContext(request, [], "en", ModelStream(model(provider), emit, Usage()),
                         RunTools(USER_ID, request), emit)
    result = await run_graph(context)
    assert calls == [(USER_ID, PRE_ID, TEST_ID)]
    assert any(kind == "step" and "fresh" in str(content) and "ADD_COLUMN" in str(content)
               for kind, content in events)
    if cross_engine:
        assert "Cross-engine comparison" in result["answer"]
        assert "No directly executable migration SQL" in result["answer"]
        assert any(kind == "step" and '"preDbType": "postgresql"' in str(content)
                   and '"testDbType": "mysql"' in str(content) for kind, content in events)
        assert len(provider.requests) == 1
    else:
        assert result["answer"] == "pre to test: add fresh, remove retired, alter orders."
