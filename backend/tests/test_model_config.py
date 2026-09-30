import os
import threading
import uuid
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session, sessionmaker

from app.api import auth as api_auth
from app.core import auth as core_auth
from app.core.config import Settings, get_settings
from app.core.security import decrypt, hash_password
from app.main import app
from app.models import AuthSession, ModelProvider, User, UserModelConfig
from app.services import model_config as model_service
from app.services.model_config_info import known_context_window, lookup_context_window


@pytest.fixture
def pg_factory(monkeypatch: pytest.MonkeyPatch) -> Iterator[sessionmaker[Session]]:
    url = os.environ.get("SQLCHAT_TEST_DATABASE_URL")
    if not url:
        pytest.skip("SQLCHAT_TEST_DATABASE_URL is required for PostgreSQL model-config integration")
    engine = create_engine(url, connect_args={"options": "-csearch_path=app"})
    factory = sessionmaker(engine, expire_on_commit=False)
    from app import main

    monkeypatch.setattr(main, "SessionLocal", factory)
    monkeypatch.setattr(api_auth, "SessionLocal", factory)
    monkeypatch.setattr(core_auth, "SessionLocal", factory)
    monkeypatch.setenv("SQLCHAT_ENCRYPT_KEY", "12345678901234567890123456789012")
    monkeypatch.setenv("SQLCHAT_DEFAULT_MODEL_API_KEY", "system-secret")
    get_settings.cache_clear()
    try:
        yield factory
    finally:
        with factory() as session:
            ids = session.scalars(select(User.id).where(User.username.like("sqlchat_model_test_%"))).all()
            if ids:
                session.execute(delete(AuthSession).where(AuthSession.user_id.in_(ids)))
                session.execute(delete(UserModelConfig).where(UserModelConfig.user_id.in_(ids)))
                session.execute(delete(User).where(User.id.in_(ids)))
                session.commit()
        engine.dispose()
        get_settings.cache_clear()


def account(factory: sessionmaker[Session]) -> User:
    with factory() as session:
        user = User(username=f"sqlchat_model_test_{uuid.uuid4().hex}",
                    password_hash=hash_password("test-password"), role="user", status=1)
        session.add(user)
        session.commit()
        return user


def token(client: TestClient, user: User) -> dict[str, str]:
    response = client.post("/api/auth/login", json={"username": user.username, "password": "test-password"})
    assert response.json()["code"] == 200
    return {"Authorization": response.json()["data"]["token"]}


def payload(name: str, model: str = "deepseek-v4-pro", key: str = "private-key") -> dict[str, object]:
    return {"providerCode": "deepseek", "providerType": "openai_compatible", "displayName": name,
            "baseUrl": "", "apiKey": key, "modelName": model, "contextWindow": None}


@pytest.fixture
def model_server() -> Iterator[tuple[str, list[tuple[str, str | None]]]]:
    observed: list[tuple[str, str | None]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            observed.append((self.path, self.headers.get("Authorization")))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"data":[{"id":"unknown-model"}]}')

        def log_message(self, _format: str, *_args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1", observed
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_provider_init_crud_defaults_ownership_and_secret(
    pg_factory: sessionmaker[Session], model_server: tuple[str, list[tuple[str, str | None]]],
) -> None:
    local_base, observed = model_server
    first = account(pg_factory)
    second = account(pg_factory)
    with TestClient(app) as client:
        anonymous = client.get("/api/model-config/providers")
        assert anonymous.status_code == 401 and anonymous.json()["code"] == 401
        first_auth, second_auth = token(client, first), token(client, second)
        providers = client.get("/api/model-config/providers", headers=first_auth).json()
        assert providers["code"] == 200
        assert {item["providerCode"] for item in providers["data"]} >= {
            "deepseek", "openai", "ollama", "custom"}
        assert client.get("/api/model-config/providers", headers=second_auth).json() == providers
        fallback = client.get("/api/model-config/active", headers=first_auth).json()["data"]
        assert fallback["id"] is None and fallback["providerCode"] == "system"
        assert fallback["modelName"] == "deepseek-flash"
        assert fallback["contextWindow"] == 1048576
        assert "apiKey" not in fallback and "system-secret" not in str(fallback)
        with pg_factory() as session:
            resolved = model_service.resolve_active_model(session, first.id)
            assert resolved.id is None and resolved.api_key.get_secret_value() == "system-secret"
            assert "system-secret" not in repr(resolved)
        created = client.post("/api/model-config/configs", headers=first_auth,
                              json=payload("primary")).json()["data"]
        assert created["isDefault"] is True and created["contextWindow"] == 65536
        assert created["baseUrl"] == "https://api.deepseek.com"
        assert "apiKey" not in created and "private-key" not in str(created)
        primary_id = created["id"]
        with pg_factory() as session:
            resolved = model_service.resolve_active_model(session, first.id)
            assert resolved.id == primary_id and resolved.api_key.get_secret_value() == "private-key"
            assert "private-key" not in repr(resolved)
        unknown = client.post("/api/model-config/configs", headers=first_auth,
                              json=payload("secondary", model="unknown-model", key="secondary-key")).json()["data"]
        assert unknown["contextWindow"] is None and unknown["isDefault"] is False
        secondary_id = unknown["id"]
        remote = payload("local-probe", model="unknown-model", key="saved-secret")
        remote["providerCode"] = "custom"
        remote["baseUrl"] = local_base
        saved_id = client.post("/api/model-config/configs", headers=first_auth,
                               json=remote).json()["data"]["id"]
        result = client.get(f"/api/model-config/configs/{saved_id}/context-window",
                            headers=first_auth).json()["data"]
        assert result == {"modelName": "unknown-model", "contextWindow": None, "source": "not_found"}
        assert observed == [("/v1/models", "Bearer saved-secret")]
        direct = client.post("/api/model-config/context-window/lookup", headers=first_auth,
                             json={"baseUrl": local_base, "apiKey": "new-secret",
                                   "modelName": "deepseek-chat"}).json()["data"]
        assert direct == {"modelName": "deepseek-chat", "contextWindow": 65536, "source": "registry"}
        assert len(observed) == 1
        assert client.get("/api/model-config/configs", headers=second_auth).json()["data"] == []
        assert client.put(f"/api/model-config/configs/{primary_id}", headers=second_auth,
                          json=payload("stolen")).json()["code"] == 404
        assert client.get(f"/api/model-config/configs/{primary_id}/context-window",
                          headers=second_auth).json()["code"] == 404
        assert client.delete(f"/api/model-config/configs/{primary_id}",
                             headers=first_auth).json()["code"] == 400
        edit = payload("edited", model="deepseek-chat", key="")
        updated = client.put(f"/api/model-config/configs/{primary_id}", headers=first_auth,
                             json=edit).json()["data"]
        assert updated["displayName"] == "edited"
        with pg_factory() as session:
            stored = session.get(UserModelConfig, primary_id)
            assert stored is not None
            assert stored.api_key_encrypted != "private-key"
            assert decrypt(stored.api_key_encrypted) == "private-key"
        assert client.put(f"/api/model-config/configs/{secondary_id}/default",
                          headers=first_auth).json()["code"] == 200
        assert client.get("/api/model-config/active", headers=first_auth).json()["data"]["id"] == secondary_id
        assert client.delete(f"/api/model-config/configs/{primary_id}",
                             headers=first_auth).json()["code"] == 200
        with pg_factory() as session:
            current = session.get(UserModelConfig, secondary_id)
            assert current is not None
            current.status = 0
            session.commit()
        assert client.put(f"/api/model-config/configs/{secondary_id}/default",
                          headers=first_auth).json()["code"] == 400
        assert client.get("/api/model-config/active", headers=first_auth).json()["data"]["id"] == saved_id
        with pg_factory() as session:
            local = session.get(UserModelConfig, saved_id)
            assert local is not None
            local.status = 0
            session.commit()
        assert client.get("/api/model-config/active", headers=first_auth).json()["data"]["id"] is None


def test_no_fallback_and_trial_mutations(pg_factory: sessionmaker[Session],
                                         monkeypatch: pytest.MonkeyPatch) -> None:
    user = account(pg_factory)
    with TestClient(app) as client:
        auth = token(client, user)
        monkeypatch.setenv("SQLCHAT_DEFAULT_MODEL_API_KEY", "")
        get_settings.cache_clear()
        assert client.get("/api/model-config/active", headers=auth).json()["code"] == 400
        monkeypatch.setenv("SQLCHAT_TRIAL_ENABLED", "true")
        get_settings.cache_clear()
        created = client.post("/api/model-config/configs", headers=auth, json=payload("blocked"))
        assert created.json()["code"] == 403
        for method, path, body in (
            ("put", "/api/model-config/configs/1", payload("blocked")),
            ("delete", "/api/model-config/configs/1", None),
            ("put", "/api/model-config/configs/1/default", None),
            ("post", "/api/model-config/context-window/lookup",
             {"baseUrl": "https://example.test", "apiKey": "x", "modelName": "deepseek-chat"}),
            ("get", "/api/model-config/configs/1/context-window", None),
        ):
            response = client.request(method, path, headers=auth, json=body)
            assert response.json()["code"] == 403
        assert client.get("/api/model-config/providers", headers=auth).json()["code"] == 200


def test_registry_and_local_http_probe(model_server: tuple[str, list[tuple[str, str | None]]]) -> None:
    base, observed = model_server
    known = lookup_context_window(base, "secret", "deepseek-chat")
    assert known.source == "registry" and known.context_window == 65536
    assert observed == []
    unknown = lookup_context_window(base, "secret", "unknown-model")
    assert unknown.source == "not_found" and unknown.context_window is None
    assert observed == [("/v1/models", "Bearer secret")]
    lookup_context_window(base + "/chat/completions", "second", "unknown-model")
    lookup_context_window(base.removesuffix("/v1") + "/api/chat/completions",
                          "third", "unknown-model")
    assert observed[-2:] == [("/v1/models", "Bearer second"),
                             ("/api/models", "Bearer third")]
    failed = lookup_context_window("not-a-url", "secret", "unknown-model")
    assert failed.source == "not_found" and failed.context_window is None


def test_deepseek_flash_default_and_window_without_env_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SQLCHAT_DEFAULT_MODEL_NAME", raising=False)
    settings = Settings(_env_file=None)
    assert settings.default_model_base_url == "https://api.deepseek.com"
    assert settings.default_model_name == "deepseek-flash"
    assert known_context_window(settings.default_model_name) == 1048576
    provider = next(item for item in model_service.BUILTIN_PROVIDERS if item[0] == "deepseek")
    assert provider[2:4] == ("https://api.deepseek.com", "deepseek-flash")
    assert known_context_window("deepseek-v4-pro") == 65536


def test_provider_seed_upgrades_only_builtin_default_and_is_idempotent() -> None:
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS app")
        ModelProvider.__table__.create(engine)
        with Session(engine) as session:
            model_service.initialize_providers(session)
            provider = session.scalar(select(ModelProvider).where(ModelProvider.provider_code == "deepseek"))
            assert provider is not None and provider.default_model == "deepseek-flash"
            provider.default_model = "deepseek-v4-pro"
            session.commit()
            model_service.initialize_providers(session)
            assert provider.default_model == "deepseek-flash"
            model_service.initialize_providers(session)
            assert provider.default_model == "deepseek-flash"
            provider.builtin = False
            provider.default_model = "custom-deepseek"
            session.commit()
            model_service.initialize_providers(session)
            assert provider.default_model == "custom-deepseek"
    finally:
        engine.dispose()
