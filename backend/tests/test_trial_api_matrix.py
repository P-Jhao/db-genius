"""Original TrialDeny endpoints and built-in restrictions through FastAPI."""

from collections.abc import Iterator
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker
from test_db_config_partial import metadata

from app.api.auth import database_session
from app.core.auth import current_user
from app.core.config import get_settings
from app.core.localization import translate
from app.main import app
from app.models import DbConfig, User
from app.services import db_config

pytest_plugins = ["test_db_config_partial"]

DB_BODY = {"name": "fixture", "dbType": "mysql", "host": "localhost", "port": 3306,
           "dbName": "synthetic", "username": "fixture", "password": "synthetic-password"}
MODEL_BODY = {"providerCode": "test", "providerType": "OPENAI_COMPATIBLE", "displayName": "test",
              "modelName": "test", "baseUrl": "https://example.invalid", "apiKey": "synthetic"}


@pytest.fixture
def client(store: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setattr(get_settings(), "trial_enabled", True)
    with store() as session:
        owner = session.get(User, 1)
        assert owner is not None
        owner.role = "admin"
        config = session.get(DbConfig, 12)
        assert config is not None
        config.builtin = True
        config.status = 1
        config.doc_content = "private builtin document"
        session.commit()

    def session_override() -> Iterator[Session]:
        with store() as session:
            yield session

    app.dependency_overrides[database_session] = session_override
    app.dependency_overrides[current_user] = lambda: owner
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("method,path,body,key", [
    ("POST", "/auth/user", {"username": "new", "password": "synthetic", "role": "user"}, "createUser"),
    ("POST", "/db-config", DB_BODY, "dbConfigCreate"),
    ("POST", "/model-config/configs", MODEL_BODY, "modelConfigCreate"),
    ("PUT", "/model-config/configs/999", MODEL_BODY, "modelConfigUpdate"),
    ("DELETE", "/model-config/configs/999", None, "modelConfigDelete"),
    ("PUT", "/model-config/configs/999/default", None, "modelConfigSetDefault"),
    ("POST", "/model-config/context-window/lookup", {"baseUrl": "https://example.invalid",
        "apiKey": "synthetic", "modelName": "test"}, "contextWindowLookup"),
    ("GET", "/model-config/configs/999/context-window", None, "contextWindowLookup"),
    ("PUT", "/db-config/12", DB_BODY, "builtinModify"),
    ("DELETE", "/db-config/12", None, "builtinModify"),
    ("POST", "/db-config/12/test", None, "builtinModify"),
    ("POST", "/db-config/12/generate-doc", None, "builtinModify"),
    ("POST", "/db-config/12/refresh-doc", None, "builtinModify"),
])
def test_original_restricted_apis_fail_before_external_side_effects(
    client: TestClient, method: str, path: str, body: dict[str, object] | None, key: str,
) -> None:
    response = client.request(method, "/api" + path, json=body, headers={"Accept-Language": "fr"})
    assert response.status_code == 200
    assert response.json() == {"code": 403, "message": translate("error.trial." + key, "fr"), "data": None}


def test_builtin_views_are_masked(client: TestClient) -> None:
    one = client.get("/api/db-config/12").json()["data"]
    many = client.get("/api/db-config").json()["data"]
    assert many == [one]
    assert all(one[key] == "*" for key in ("dbType", "host", "dbName", "username", "docContent"))
    assert one["port"] == 0 and "password" not in one
    assert client.get("/api/db-config/12/doc").json()["data"] == "*"


def test_removed_sales_endpoint_is_absent_instead_of_success_shell(client: TestClient) -> None:
    assert client.post("/api/sales/contact", json={"name": "synthetic"}).status_code == 404
    paths = client.get("/openapi.json").json()["paths"]
    assert not any(path.startswith("/api/sales") for path in paths)


def test_nonbuiltin_existing_config_is_not_restricted_beyond_original_rules(
    client: TestClient, store: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch,
) -> None:
    with store() as session:
        config = session.get(DbConfig, 12)
        assert config is not None
        config.builtin = False
        session.commit()
    adapter = Mock()
    adapter.test_connection.return_value = True
    adapter.extract_metadata.return_value = metadata(False)
    monkeypatch.setattr(db_config, "get_adapter", lambda _type: adapter)
    monkeypatch.setattr(db_config, "_enqueue", Mock(return_value=True))
    assert client.put("/api/db-config/12", json=DB_BODY).json()["code"] == 200
    assert client.post("/api/db-config/12/test").json()["data"] is True
    assert client.post("/api/db-config/12/generate-doc").json()["code"] == 200
    assert client.post("/api/db-config/12/refresh-doc").json()["code"] == 200
    assert client.delete("/api/db-config/12").json()["code"] == 200
