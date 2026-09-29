from datetime import UTC, datetime

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from app.core.config import Settings, get_settings
from app.core.errors import BusinessError, success
from app.core.localization import translate
from app.core.security import decrypt, encrypt
from app.main import app
from app.models.entities import Conversation, UploadedFile, User
from app.schemas.db_config import DbConfigRequest
from app.schemas.model_config import UserModelConfigVO


def test_original_runtime_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "SQLCHAT_SESSION_LIFETIME_SECONDS",
        "SQLCHAT_SESSION_IDLE_SECONDS",
        "SQLCHAT_QUERY_TIMEOUT_SECONDS",
        "SQLCHAT_QUERY_MAX_ROWS",
        "SQLCHAT_SQL_AGENT_MAX_STEPS",
        "SQLCHAT_WORKFLOW_AGENT_MAX_STEPS",
        "SQLCHAT_COMPARE_AGENT_MAX_STEPS",
    ):
        monkeypatch.delenv(key, raising=False)
    settings = Settings(_env_file=None)
    assert (settings.session_lifetime_seconds, settings.session_idle_seconds) == (86400, 3600)
    assert (settings.query_timeout_seconds, settings.query_max_rows) == (30, 100)
    assert (
        settings.sql_agent_max_steps,
        settings.workflow_agent_max_steps,
        settings.compare_agent_max_steps,
    ) == (10, 20, 15)


def test_public_contracts_use_camel_case_and_hide_secrets() -> None:
    request = DbConfigRequest.model_validate({"name": "db", "dbName": "sample"})
    assert request.db_type == "mysql"
    assert request.model_dump(by_alias=True)["dbName"] == "sample"
    model = UserModelConfigVO(
        id=1, provider_code="custom", provider_type="openai_compatible", display_name="Test",
        base_url="https://example.test", model_name="model", context_window=None,
        is_default=True, status=1, status_desc="Enabled", created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert "apiKey" not in model.model_dump(by_alias=True)
    assert model.model_dump(by_alias=True)["isDefault"] is True


def test_original_bigint_columns() -> None:
    dialect = postgresql.dialect()
    assert User.__table__.c.id.type.compile(dialect=dialect) == "BIGINT"
    assert Conversation.__table__.c.total_tokens.type.compile(dialect=dialect) == "BIGINT"
    assert UploadedFile.__table__.c.file_size.type.compile(dialect=dialect) == "BIGINT"


def test_error_codes_and_localized_message() -> None:
    assert success(None) == {"code": 200, "message": "success", "data": None}
    with pytest.raises(TypeError):
        BusinessError("NOT_FOUND", "error.dbConfig.notFound")  # type: ignore[arg-type]
    assert translate("error.dbConfig.notFound", "zh-CN,zh;q=0.9").startswith("数据库")
    assert translate("error.dbConfig.notFound", "fr-FR,fr;q=0.9") != "error.dbConfig.notFound"


def test_java_aes_layout_is_compatible(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SQLCHAT_ENCRYPT_KEY", "12345678901234567890123456789012")
    get_settings.cache_clear()
    try:
        nonce = bytes(range(12))
        java_key = b"12345678901234567890123456789012"
        legacy = nonce + AESGCM(java_key).encrypt(nonce, b"password", None)
        import base64

        assert decrypt(base64.b64encode(legacy).decode()) == "password"
        assert decrypt(encrypt("new secret")) == "new secret"
    finally:
        get_settings.cache_clear()


def test_health_route_is_real() -> None:
    client = TestClient(app)
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "UP"
    assert client.post("/api/auth/login", json={}).status_code == 400
