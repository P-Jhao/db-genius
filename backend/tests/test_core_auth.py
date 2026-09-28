import os
import uuid
from collections.abc import Iterator
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session, sessionmaker

from app.api import auth as api_auth
from app.core import auth as core_auth
from app.core.auth import authenticated_user, utc_now
from app.core.errors import BusinessError
from app.core.ownership import require_owned
from app.core.security import hash_password, verify_password
from app.main import app
from app.models import AuthSession, DbConfig, User


@pytest.fixture
def pg_session_factory(monkeypatch: pytest.MonkeyPatch) -> Iterator[sessionmaker[Session]]:
    url = os.environ.get("SQLCHAT_TEST_DATABASE_URL")
    if not url:
        pytest.skip("SQLCHAT_TEST_DATABASE_URL is required for PostgreSQL authentication integration")
    engine = create_engine(url, connect_args={"options": "-csearch_path=app"})
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(core_auth, "SessionLocal", factory)
    monkeypatch.setattr(api_auth, "SessionLocal", factory)
    try:
        yield factory
    finally:
        with factory() as session:
            names = session.scalars(select(User.username).where(User.username.like("sqlchat_test_%"))).all()
            if names:
                ids = session.scalars(select(User.id).where(User.username.in_(names))).all()
                session.execute(delete(AuthSession).where(AuthSession.user_id.in_(ids)))
                session.execute(delete(DbConfig).where(DbConfig.user_id.in_(ids)))
                session.execute(delete(User).where(User.id.in_(ids)))
                session.commit()
        engine.dispose()


def create_account(factory: sessionmaker[Session], role: str = "user", status: int = 1) -> User:
    with factory() as session:
        user = User(username=f"sqlchat_test_{uuid.uuid4().hex}", password_hash=hash_password("test-password"),
                    role=role, status=status)
        session.add(user)
        session.commit()
        return user


def login(client: TestClient, user: User) -> str:
    response = client.post("/api/auth/login", json={"username": user.username, "password": "test-password"})
    assert response.status_code == 200
    assert response.json()["code"] == 200
    return response.json()["data"]["token"]


def test_login_roles_logout_and_bcrypt_compatibility(pg_session_factory: sessionmaker[Session]) -> None:
    admin = create_account(pg_session_factory, role="admin")
    member = create_account(pg_session_factory)
    disabled = create_account(pg_session_factory, status=0)
    assert verify_password("test-password", admin.password_hash)
    with TestClient(app) as client:
        bad = client.post("/api/auth/login", json={"username": admin.username, "password": "wrong"})
        assert bad.status_code == 200 and bad.json()["code"] == 401
        blocked = client.post("/api/auth/login", json={"username": disabled.username, "password": "test-password"})
        assert blocked.status_code == 200 and blocked.json()["code"] == 403
        admin_token = login(client, admin)
        member_token = login(client, member)
        payload = {"username": f"sqlchat_test_{uuid.uuid4().hex}", "password": "child-password"}
        denied = client.post("/api/auth/user", headers={"Authorization": member_token}, json=payload)
        assert denied.status_code == 200 and denied.json()["code"] == 403
        created = client.post("/api/auth/user", headers={"Authorization": admin_token}, json=payload)
        assert created.json() == {"code": 200, "message": "success", "data": None}
        duplicate = client.post("/api/auth/user", headers={"Authorization": admin_token}, json=payload)
        assert duplicate.json()["code"] == 400
        assert client.post("/api/auth/logout", headers={"Authorization": admin_token}).json()["code"] == 200
        expired = client.post("/api/auth/user", headers={"Authorization": admin_token}, json=payload)
        assert expired.status_code == 401


def test_idle_and_total_expiration(pg_session_factory: sessionmaker[Session]) -> None:
    user = create_account(pg_session_factory)
    with TestClient(app) as client:
        token = login(client, user)
        with pg_session_factory() as session:
            authenticated_user(session, token, utc_now() + timedelta(seconds=3599))
            with pytest.raises(BusinessError) as idle_error:
                authenticated_user(session, token, utc_now() + timedelta(seconds=7200))
            assert idle_error.value.code == 401
        second_token = login(client, user)
        with pg_session_factory() as session:
            with pytest.raises(BusinessError) as total_error:
                authenticated_user(session, second_token, utc_now() + timedelta(seconds=86401))
            assert total_error.value.code == 401


def test_cross_user_resource_id_is_rejected(pg_session_factory: sessionmaker[Session]) -> None:
    first = create_account(pg_session_factory)
    second = create_account(pg_session_factory)
    with pg_session_factory() as session:
        config = DbConfig(user_id=first.id, name="private", db_type="mysql", host="localhost", port=3306,
                          db_name="test", username="test", status=0)
        session.add(config)
        session.commit()
        with pytest.raises(BusinessError) as denied:
            require_owned(session, DbConfig, config.id, second.id, "error.dbConfig.notFound")
        assert denied.value.code == 404
        assert require_owned(session, DbConfig, config.id, first.id, "error.dbConfig.notFound").id == config.id
