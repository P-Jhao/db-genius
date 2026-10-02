"""S05 API and state-machine checks against the isolated PostgreSQL system database."""

import os
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from kombu.exceptions import OperationalError  # type: ignore[import-untyped]
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session, sessionmaker

from app import main
from app.adapters.safety import UnsafeStatement
from app.api import auth as api_auth
from app.core import auth as core_auth
from app.core.config import get_settings
from app.core.errors import BusinessError
from app.core.security import token_digest
from app.models import AuthSession, DbConfig, User
from app.schemas.db_config import DbConfigRequest
from app.services import database_tools, db_config, db_config_worker


@pytest.fixture
def database(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[sessionmaker[Session], User, User]]:
    url = os.environ.get("SQLCHAT_TEST_DATABASE_URL")
    if not url:
        pytest.skip("SQLCHAT_TEST_DATABASE_URL is required")
    monkeypatch.setenv("SQLCHAT_ENCRYPT_KEY", "0123456789abcdef0123456789abcdef")
    get_settings.cache_clear()
    engine = create_engine(url, connect_args={"options": "-csearch_path=app"})
    factory = sessionmaker(engine, expire_on_commit=False)
    for module in (main, api_auth, core_auth, db_config_worker, database_tools):
        monkeypatch.setattr(module, "SessionLocal", factory)
    with factory() as session:
        users = [User(username=f"sqlchat_s05_{uuid4().hex}", password_hash="unused", status=1)
                 for _ in range(2)]
        session.add_all(users)
        session.commit()
    try:
        yield factory, users[0], users[1]
    finally:
        with factory() as session:
            ids = [user.id for user in users]
            session.execute(delete(AuthSession).where(AuthSession.user_id.in_(ids)))
            session.execute(delete(DbConfig).where(DbConfig.user_id.in_(ids)))
            session.execute(delete(User).where(User.id.in_(ids)))
            session.commit()
        engine.dispose()
        get_settings.cache_clear()


def _token(factory: sessionmaker[Session], user: User) -> str:
    token = uuid4().hex
    with factory() as session:
        session.add(AuthSession(token_hash=token_digest(token), user_id=user.id,
                                expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1),
                                last_active_at=datetime.now(UTC).replace(tzinfo=None)))
        session.commit()
    return token


def _payload(db_type: str) -> dict[str, object]:
    prefix = "SQLCHAT_TEST_PG" if db_type == "postgresql" else "SQLCHAT_TEST_MYSQL"
    values = {name: os.environ.get(f"{prefix}_{name}") for name in ("HOST", "PORT", "DB", "USER", "PASSWORD")}
    if any(value is None for value in values.values()):
        pytest.skip(f"{db_type} isolated target credentials are required")
    assert values["PORT"] is not None
    return {"name": f"S05 {db_type}", "dbType": db_type, "host": values["HOST"],
            "port": int(values["PORT"]), "dbName": values["DB"],
            "username": values["USER"], "password": values["PASSWORD"]}


@pytest.mark.parametrize("db_type", ["mysql", "postgresql"])
def test_api_worker_version_and_delete(database: tuple[sessionmaker[Session], User, User],
                                       monkeypatch: pytest.MonkeyPatch, db_type: str) -> None:
    factory, owner, outsider = database
    pending: list[tuple[int, int]] = []
    monkeypatch.setattr(db_config.verify_config, "apply_async",
                        lambda *, args, headers: pending.append((args[0], args[1])))
    payload = _payload(db_type)
    with TestClient(main.app) as client:
        owner_headers = {"Authorization": _token(factory, owner)}
        outsider_headers = {"Authorization": _token(factory, outsider)}
        created = client.post("/api/db-config", headers=owner_headers, json=payload).json()
        assert created["code"] == 200 and created["data"]["status"] == 0
        assert "password" not in created["data"]
        config_id = created["data"]["id"]
        assert pending == [(config_id, 1)]
        denied = client.get(f"/api/db-config/{config_id}", headers=outsider_headers).json()
        assert denied["code"] == 404
        assert client.get("/api/db-config", headers=outsider_headers).json()["data"] == []

        db_config_worker.verify_and_generate(config_id, 1)
        verified = client.get(f"/api/db-config/{config_id}", headers=owner_headers).json()["data"]
        assert verified["status"] == 1
        assert f"# Database: {payload['dbName']}" in verified["docContent"]
        assert client.get(f"/api/db-config/{config_id}/doc", headers=owner_headers).json()["data"] == verified["docContent"]
        assert database_tools.get_schema(owner.id, config_id)["databaseName"] == payload["dbName"]
        assert database_tools.execute_statement(owner.id, config_id, "SELECT 1 AS value")["data"] == [{"value": 1}]
        with pytest.raises(BusinessError) as denied_tool:
            database_tools.get_schema(outsider.id, config_id)
        assert denied_tool.value.code == 404

        revised = {**payload, "name": "new version", "password": ""}
        changed = client.put(f"/api/db-config/{config_id}", headers=owner_headers, json=revised).json()
        assert changed["data"]["status"] == 0 and changed["data"]["docContent"] is None
        assert pending[-1] == (config_id, 2)
        db_config_worker.verify_and_generate(config_id, 1)
        assert client.get(f"/api/db-config/{config_id}", headers=owner_headers).json()["data"]["status"] == 0
        db_config_worker.verify_and_generate(config_id, 2)
        assert client.get(f"/api/db-config/{config_id}", headers=owner_headers).json()["data"]["status"] == 1
        assert client.post(f"/api/db-config/{config_id}/test", headers=owner_headers).json()["data"] is True
        generated = client.post(f"/api/db-config/{config_id}/generate-doc", headers=owner_headers).json()
        assert generated["code"] == 200 and "# Database:" in generated["data"]
        refreshed = client.post(f"/api/db-config/{config_id}/refresh-doc", headers=owner_headers).json()
        assert refreshed["code"] == 200 and pending[-1] == (config_id, 5)
        deleted = client.delete(f"/api/db-config/{config_id}", headers=owner_headers).json()
        assert deleted == {"code": 200, "message": "success", "data": None}
        db_config_worker.verify_and_generate(config_id, 5)
        with factory() as session:
            assert session.get(DbConfig, config_id) is None


def test_failure_queue_diagnostic_and_trial_mask(database: tuple[sessionmaker[Session], User, User],
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    factory, owner, _ = database
    payload = _payload("postgresql")
    monkeypatch.setattr(db_config.verify_config, "apply_async",
                        lambda *, args, headers: (_ for _ in ()).throw(OperationalError("connection refused")))
    with TestClient(main.app) as client:
        headers = {"Authorization": _token(factory, owner)}
        created = client.post("/api/db-config", headers=headers, json=payload).json()
        assert created["data"]["status"] == 2
        assert "queue unavailable" in created["data"]["statusDesc"]
        config_id = created["data"]["id"]
        with factory() as session:
            config = session.get(DbConfig, config_id)
            assert config is not None
            config.builtin = True
            config.doc_content = "private schema"
            session.commit()
        get_settings().trial_enabled = True
        masked = client.get(f"/api/db-config/{config_id}", headers=headers).json()["data"]
        assert all(masked[key] == "*" for key in ("dbType", "host", "dbName", "username", "docContent"))
        assert "queue unavailable" not in masked["statusDesc"]
        assert client.get(f"/api/db-config/{config_id}/doc", headers=headers).json()["data"] == "*"
        with factory() as session:
            config = session.get(DbConfig, config_id)
            assert config is not None
            config.status = 1
            session.commit()
        metadata = database_tools.get_schema(owner.id, config_id)
        assert metadata["databaseName"] == "*" and metadata["host"] == "*" and metadata["port"] == 0
        with pytest.raises(UnsafeStatement):
            database_tools.execute_statement(owner.id, config_id, "UPDATE users SET name = 'changed'")
        for method, path in (("put", f"/api/db-config/{config_id}"),
                             ("delete", f"/api/db-config/{config_id}"),
                             ("post", f"/api/db-config/{config_id}/test"),
                             ("post", f"/api/db-config/{config_id}/generate-doc"),
                             ("post", f"/api/db-config/{config_id}/refresh-doc")):
            response = client.request(method.upper(), path, headers=headers,
                                      json=payload if method == "put" else None).json()
            assert response["code"] == 403
        assert client.post("/api/db-config", headers=headers, json=payload).json()["code"] == 403
        get_settings().trial_enabled = False


def test_worker_failure_and_timeout(database: tuple[sessionmaker[Session], User, User],
                                    monkeypatch: pytest.MonkeyPatch) -> None:
    factory, owner, _ = database
    monkeypatch.setattr(db_config.verify_config, "apply_async", lambda *, args, headers: None)
    payload = _payload("postgresql")
    with factory() as session:
        created = db_config.create_config(session, owner.id, DbConfigRequest.model_validate(payload))
        config_id = created.id
    class BrokenAdapter:
        def test_connection(self, _connection: object) -> bool:
            raise RuntimeError(f"authentication rejected {payload['password']}")

    monkeypatch.setattr(db_config_worker, "get_adapter", lambda _db_type: BrokenAdapter())
    db_config_worker.verify_and_generate(config_id, 1)
    with factory() as session:
        failed = db_config.get_config(session, owner.id, config_id)
        assert failed.status == 2
        assert "authentication rejected" in failed.status_desc
        assert str(payload["password"]) not in failed.status_desc
        config = session.get(DbConfig, config_id)
        assert config is not None
        config.status = 0
        config.updated_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1)
        session.commit()
        stale = db_config.get_config(session, owner.id, config_id)
        assert stale.status == 2 and "worker unavailable" in stale.status_desc


@pytest.mark.parametrize("connected", [True, False])
def test_live_celery_worker(database: tuple[sessionmaker[Session], User, User], connected: bool) -> None:
    if not os.environ.get("SQLCHAT_TEST_BROKER_URL"):
        pytest.skip("SQLCHAT_TEST_BROKER_URL is required for the live Celery worker")
    factory, owner, _ = database
    payload = _payload("postgresql")
    if not connected:
        payload["port"] = 1
    with factory() as session:
        created = db_config.create_config(session, owner.id, DbConfigRequest.model_validate(payload))
        assert created.status == 0
        config_id = created.id
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        with factory() as session:
            config = session.get(DbConfig, config_id)
            assert config is not None
            if config.status != 0:
                if connected:
                    assert config.status == 1, config.verification_error
                    assert config.doc_content is not None and "# Database:" in config.doc_content
                else:
                    assert config.status == 2
                    assert config.verification_error is not None
                    assert config.doc_content is None
                return
        time.sleep(0.2)
    pytest.fail("Celery worker did not consume the verification task within 60 seconds")


def test_unreachable_broker_persists_failure(database: tuple[sessionmaker[Session], User, User]) -> None:
    if os.environ.get("SQLCHAT_TEST_BROKER_UNAVAILABLE") != "1":
        pytest.skip("Run with SQLCHAT_BROKER_URL pointing to an unused local port")
    factory, owner, _ = database
    payload = _payload("postgresql")
    with factory() as session:
        created = db_config.create_config(session, owner.id, DbConfigRequest.model_validate(payload))
        assert created.status == 2
        assert "Verification queue unavailable" in created.status_desc
        config = session.get(DbConfig, created.id)
        assert config is not None and config.status == 2
