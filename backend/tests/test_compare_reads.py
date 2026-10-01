"""Comparison authorization uses the stored target adapter before execution."""

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.adapters import DbConnectionConfig, get_adapter
from app.agent.tools import RunTools
from app.agent.types import ChatRequest
from app.core.database import Base
from app.core.errors import BusinessError
from app.models import DbConfig, User
from app.services import database_tools


@pytest.fixture
def configs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'configs.sqlite'}",
                           execution_options={"schema_translate_map": {"app": None}})
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as session:
        session.add_all([User(id=7, username="owner", password_hash="unused"),
                         User(id=8, username="other", password_hash="unused")])
        session.flush()
        for db_id, owner, db_type, status in [(12, 7, "postgresql", 1), (13, 7, "mysql", 1),
                (14, 8, "postgresql", 1), (15, 7, "postgresql", 0), (16, 7, "postgresql", 2)]:
            session.add(DbConfig(id=db_id, user_id=owner, name=f"target {db_id}", db_type=db_type,
                host="127.0.0.1", port=5432, db_name=f"target_{db_id}", username="unused", status=status))
        session.commit()
    monkeypatch.setattr(database_tools, "SessionLocal", factory)
    monkeypatch.setattr(database_tools, "connection_for", lambda row: DbConnectionConfig(
        row.db_type, row.host, row.port, row.db_name, row.username, "test-only"))
    try:
        yield factory
    finally:
        engine.dispose()


@pytest.mark.parametrize("db_id,statement", [
    (12, "SELECT 1 INTO unwanted"),
    (12, "WITH changed AS (DELETE FROM orders RETURNING *) SELECT * FROM changed"),
    (12, "WITH changed AS (INSERT INTO orders VALUES (1) RETURNING *) SELECT * FROM changed"),
    (12, "EXPLAIN ANALYZE DELETE FROM orders"),
    (12, "SELECT 1; DELETE FROM orders"),
    (13, "SELECT 1; UPDATE orders SET id=2"),
    (13, "SELECT * FROM `order items`; CREATE TABLE unwanted (id INT)"),
    (13, "EXPLAIN DELETE FROM orders"),
])
def test_comparison_rejects_nested_writes_and_multiple_statements(
    configs: object, monkeypatch: pytest.MonkeyPatch, db_id: int, statement: str,
) -> None:
    monkeypatch.setattr(type(get_adapter("postgresql")), "execute", lambda *_args, **_kwargs:
                        pytest.fail("Rejected comparison reached a driver"))
    monkeypatch.setattr(type(get_adapter("mysql")), "execute", lambda *_args, **_kwargs:
                        pytest.fail("Rejected comparison reached a driver"))
    with pytest.raises(BusinessError):
        database_tools.execute_comparison_read(7, db_id, statement)


@pytest.mark.parametrize("db_id,expected_code", [(14, 404), (15, 400), (16, 400), (99, 404)])
def test_owned_ready_config_is_required_before_the_policy(
    configs: object, monkeypatch: pytest.MonkeyPatch, db_id: int, expected_code: int,
) -> None:
    monkeypatch.setattr(database_tools, "get_adapter", lambda _db_type:
                        pytest.fail("Unowned or disconnected config reached a target adapter"))
    with pytest.raises(BusinessError) as denied:
        database_tools.execute_comparison_read(7, db_id, "SELECT 1")
    assert denied.value.code == expected_code


@pytest.mark.asyncio
async def test_model_cannot_supply_a_dialect_or_expand_comparison_targets(
    configs: object, monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    original = database_tools.get_adapter

    def selected(db_type: str):
        calls.append(db_type)
        return original(db_type)

    monkeypatch.setattr(database_tools, "get_adapter", selected)
    drivers: list[tuple[str, str]] = []

    def driver(_adapter: object, target: DbConnectionConfig, statement: str, **_kwargs: object):
        drivers.append((target.db_type, statement))
        return {"success": True, "rowCount": 1, "data": [{"value": 1}]}

    monkeypatch.setattr(type(original("postgresql")), "execute", driver)
    tools = RunTools(7, ChatRequest(message="compare", dbConfigIds=[14], preDbConfigId=12, testDbConfigId=13))
    execute = next(tool for tool in tools.for_intent("db_compare") if tool.name == "executeSql")
    try:
        result = await execute.ainvoke({"db_id": 12, "dbType": "mysql", "statement": "SHOW ALL"})
        assert json.loads(result)["success"] is True
        assert calls == ["postgresql"]
        assert drivers == [("postgresql", "SHOW ALL")]
        with pytest.raises(BusinessError, match="comparison target"):
            await execute.ainvoke({"db_id": 14, "statement": "SELECT 1"})
        with pytest.raises(BusinessError, match="not selected"):
            await execute.ainvoke({"db_id": 99, "statement": "SELECT 1"})
        assert calls == ["postgresql"]
    finally:
        tools.close()


def test_check_and_execute_use_one_resolved_config(configs: object, monkeypatch: pytest.MonkeyPatch) -> None:
    first = database_tools._ready_config(7, 12)
    resolutions: list[int] = []

    def ready(_user_id: int, db_id: int) -> DbConfig:
        resolutions.append(db_id)
        if len(resolutions) > 1:
            pytest.fail("Comparison executed against a separately resolved configuration")
        return first

    monkeypatch.setattr(database_tools, "_ready_config", ready)
    adapter = get_adapter("postgresql")
    calls: list[tuple[str, bool]] = []

    def execute(_adapter: object, target: DbConnectionConfig, statement: str, **kwargs: object):
        assert target.db_type == "postgresql" and target.db_name == "target_12"
        calls.append((statement, kwargs["trial_mode"]))
        return {"success": True, "rowCount": 1, "data": [{"value": 1}]}

    monkeypatch.setattr(type(adapter), "execute", execute)
    assert database_tools.execute_comparison_read(7, 12, "SELECT 1")["success"] is True
    assert resolutions == [12]
    assert calls == [("SELECT 1", True)]


def test_future_mongo_reads_delegate_to_its_json_policy(configs: object, monkeypatch: pytest.MonkeyPatch) -> None:
    ready = database_tools._ready_config(7, 12)
    ready.db_type = "mongodb"
    monkeypatch.setattr(database_tools, "_ready_config", lambda _user, _db: ready)
    calls: list[str] = []

    class JsonAdapter:
        def is_read_only(self, statement: str) -> bool:
            calls.append(statement)
            return json.loads(statement).get("command") == "find"

        def execute(self, _target: object, _statement: str, **kwargs: object):
            assert kwargs["trial_mode"] is True
            return {"success": True, "rowCount": 0, "data": []}

    monkeypatch.setattr(database_tools, "get_adapter", lambda db_type:
                        JsonAdapter() if db_type == "mongodb" else pytest.fail("Wrong adapter"))
    read = '{"command":"find","collection":"orders"}'
    assert database_tools.execute_comparison_read(7, 12, read)["success"] is True
    with pytest.raises(BusinessError, match="migration writes"):
        database_tools.execute_comparison_read(7, 12, '{"command":"delete","collection":"orders"}')
    assert calls == [read, '{"command":"delete","collection":"orders"}']
