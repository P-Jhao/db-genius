"""Real PG/MySQL data effects with a controlled HTTP model and production tools."""

import threading
from uuid import uuid4

import pytest
from sqlalchemy import inspect
from sqlalchemy.orm import Session, sessionmaker
from test_dsml import _invoke, _parameter, _reply, _wrapper
from test_model_protocol import Provider, model
from test_trial_targets import _target

from app.adapters import get_adapter
from app.adapters.relational import RelationalAdapter
from app.adapters.safety import UnsafeStatement
from app.agent.graph import RunContext, run_graph
from app.agent.streaming import ModelStream
from app.agent.tools import RunTools
from app.agent.types import ChatRequest, Usage
from app.core.config import get_settings
from app.core.security import encrypt
from app.models import DbConfig
from app.services import database_tools

pytest_plugins = ["test_model_protocol", "test_db_config_partial"]


@pytest.mark.asyncio
@pytest.mark.parametrize("db_type", ["postgresql", "mysql"])
async def test_trial_graph_reads_rejects_writes_and_normal_graph_commits_allowed_write(
    store: sessionmaker[Session], provider: Provider, monkeypatch: pytest.MonkeyPatch, db_type: str,
) -> None:
    target = _target(db_type)
    adapter = get_adapter(db_type)
    assert isinstance(adapter, RelationalAdapter)
    table = "s13_trial_" + uuid4().hex
    with adapter._connection(target, 30) as connection:
        quoted = adapter._qualified_name(connection, table)
        connection.exec_driver_sql(f"CREATE TABLE {quoted} (id INT PRIMARY KEY, label VARCHAR(20))")
        connection.exec_driver_sql(f"INSERT INTO {quoted} VALUES (1, 'original')")
        connection.commit()
    with store() as session:
        config = session.get(DbConfig, 12)
        assert config is not None
        config.db_type, config.host, config.port = target.db_type, target.host, target.port
        config.db_name, config.username = target.db_name, target.username
        config.password_encrypted = encrypt(target.password)
        config.status, config.builtin = 1, True
        session.commit()

    async def emit(_kind: str, _value: object, _step: int) -> None:
        pass

    def context() -> RunContext:
        request = ChatRequest.model_validate({"message": "synthetic operation", "dbConfigIds": [12],
                                              "confirmedIntent": "sql_query"})
        cancellation = threading.Event()
        return RunContext(request, [], "en", ModelStream(model(provider), emit, Usage(), cancellation),
                          RunTools(1, request, cancellation), emit, cancellation)

    def dsml(statement: str) -> list[bytes]:
        return _reply(_wrapper(_invoke("executeSql", _parameter("dbConfigId", "12")
                                       + _parameter("sql", statement, string=True))))

    try:
        monkeypatch.setattr(get_settings(), "trial_enabled", True)
        provider.replies = [dsml(f"SELECT id, label FROM {quoted}"), _reply("One original row.")]
        read = context()
        assert (await run_graph(read))["answer"] == "One original row."
        assert read.tools.last_result == {"success": True, "data": [{"id": 1, "label": "original"}],
                                          "rowCount": 1, "truncated": False}
        assert read.tools.completed_write_count == 0
        masked = database_tools.get_schema(1, 12)
        assert masked["databaseName"] == "*" and masked["host"] == "*" and masked["port"] == 0
        provider.replies = [dsml(f"UPDATE {quoted} SET label = 'forbidden' WHERE id = 1")]
        denied = context()
        with pytest.raises(UnsafeStatement):
            await run_graph(denied)
        assert denied.tools.statements_executed == denied.tools.completed_write_count == 0
        assert adapter.execute(target, f"SELECT label FROM {quoted}", trial_mode=True)["data"] == [
            {"label": "original"}]
        monkeypatch.setattr(get_settings(), "trial_enabled", False)
        provider.replies = [dsml(f"UPDATE {quoted} SET label = 'committed' WHERE id = 1"), _reply("Updated one row.")]
        ordinary = context()
        assert (await run_graph(ordinary))["answer"] == "Updated one row."
        assert ordinary.tools.completed_write_count == 1 and ordinary.tools.statements_executed == 1
        assert adapter.execute(target, f"SELECT label FROM {quoted}")["data"] == [{"label": "committed"}]
        for statement in (f"DROP TABLE {quoted}", f"TRUNCATE TABLE {quoted}"):
            with pytest.raises(UnsafeStatement):
                database_tools.execute_statement(1, 12, statement)
        with adapter._connection(target, 30) as connection:
            assert inspect(connection).has_table(table)
    finally:
        with adapter._connection(target, 30) as connection:
            connection.exec_driver_sql(f"DROP TABLE IF EXISTS {quoted}")
            connection.commit()
