"""Native registration reaches the API, worker and owned database tools."""

from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from native_database_fixtures import oracle_target as oracle_fixture
from native_database_fixtures import sqlserver_target as sqlserver_fixture
from native_database_fixtures import wait_oracle_ddl
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from test_db_config import _token
from test_native_workflow_real import fixture_target

from app import main
from app.api import auth as api_auth
from app.core import auth as core_auth
from app.core.config import get_settings
from app.core.database import Base
from app.core.errors import BusinessError
from app.models import User
from app.services import database_tools, db_config, db_config_worker

oracle_target = oracle_fixture
sqlserver_target = sqlserver_fixture


@pytest.mark.parametrize("db_type", ["oracle", "sqlserver"])
def test_actual_native_api_worker_and_controlled_reads(
    db_type: str, request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    target, engine = fixture_target(request, db_type)
    table = "api_" + uuid4().hex[:12]
    created = False
    system = create_engine(f"sqlite:///{tmp_path / 'api.sqlite'}",
                           execution_options={"schema_translate_map": {"app": None}})
    Base.metadata.create_all(system)
    factory = sessionmaker(system, expire_on_commit=False)
    monkeypatch.setenv("SQLCHAT_ENCRYPT_KEY", "0123456789abcdef0123456789abcdef")
    get_settings.cache_clear()
    for module in (main, api_auth, core_auth, database_tools, db_config_worker):
        monkeypatch.setattr(module, "SessionLocal", factory)
    queued: list[tuple[int, int]] = []
    queue_locales: list[str] = []
    def enqueue(*, args: tuple[int, int], headers: dict[str, str]) -> None:
        queued.append(args)
        queue_locales.append(headers["locale"])
    monkeypatch.setattr(db_config.verify_config, "apply_async", enqueue)
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)")
            connection.exec_driver_sql(f"INSERT INTO {table} VALUES (1)")
        created = True
        if db_type == "oracle":
            wait_oracle_ddl(engine, [table.upper()])
        with factory() as session:
            owner = User(username="native-owner", password_hash="unused", status=1)
            other = User(username="native-outsider", password_hash="unused", status=1)
            session.add_all([owner, other])
            session.commit()
        payload = {"name": "native target", "dbType": db_type, "host": target.host,
                   "port": target.port, "dbName": target.db_name,
                   "username": target.username, "password": target.password}
        with TestClient(main.app) as client:
            headers = {"Authorization": _token(factory, owner), "Accept-Language": "zh-TW"}
            response = client.post("/api/db-config", headers=headers, json=payload).json()
            assert response["code"] == 200 and response["data"]["status"] == 0
            assert "password" not in response["data"] and target.password not in str(response)
            config_id = response["data"]["id"]
            assert queued == [(config_id, 1)]
            assert queue_locales == ["zh-TW"]
            db_config_worker.verify_and_generate(config_id, 1)
            verified = client.get(f"/api/db-config/{config_id}", headers=headers).json()["data"]
            assert verified["status"] == 1 and table.lower() in verified["docContent"].lower()
            assert client.post(f"/api/db-config/{config_id}/test", headers=headers).json()["data"] is True
            metadata = database_tools.get_schema(owner.id, config_id)
            assert metadata["dbType"] == db_type and metadata["incomplete"] is False
            read = database_tools.execute_comparison_read(owner.id, config_id, f"SELECT id FROM {table}")
            assert read["data"] == [{"ID" if db_type == "oracle" else "id": 1}]
            unsafe = (f"SELECT * FROM {table} FOR UPDATE" if db_type == "oracle" else
                      f"SELECT * FROM {table} WITH (UPDLOCK)")
            with pytest.raises(BusinessError, match="migration writes"):
                database_tools.execute_comparison_read(owner.id, config_id, unsafe)
            with pytest.raises(BusinessError) as denied:
                database_tools.get_schema(other.id, config_id)
            assert denied.value.code == 404
            assert client.delete(f"/api/db-config/{config_id}", headers=headers).json()["code"] == 200
    finally:
        if created:
            with engine.begin() as connection:
                suffix = " PURGE" if db_type == "oracle" else ""
                connection.exec_driver_sql(f"DROP TABLE {table}{suffix}")
        system.dispose()
        get_settings.cache_clear()
