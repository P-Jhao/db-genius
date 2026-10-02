"""Queue diagnostics retain wording/status while removing synthetic credentials."""

import json
from unittest.mock import Mock
from urllib.parse import quote, quote_plus

import pytest
from kombu.exceptions import OperationalError  # type: ignore[import-untyped]
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.diagnostics import safe_exception_diagnostic, sanitize_diagnostic
from app.core.errors import BusinessError
from app.core.localization import translate
from app.core.request_locale import current_locale, locale_scope
from app.models import DbConfig
from app.services import db_config
from app.tasks import db_config as task

pytest_plugins = ["test_db_config_partial"]

PASSWORD = "queue synthetic+/ password?"
KEY = "SYNTHETIC_PROVIDER_KEY"


def settings() -> Settings:
    encoded = quote(PASSWORD, safe="")
    configured = Settings(database_url=f"postgresql://system_user:{encoded}@local.invalid/db",
                    broker_url=f"amqp://broker_user:{encoded}@local.invalid//",
                    checkpoint_database_url=f"postgresql://checkpoint_user:{encoded}@local.invalid/db",
                    oss_access_key_secret="SYNTHETIC_OSS_KEY", ocr_access_key_secret="SYNTHETIC_OCR_KEY")
    configured.default_model_api_key = KEY
    configured.encrypt_key = "SYNTHETIC_ENCRYPT_KEY"
    return configured


@pytest.mark.parametrize("encoding", ["raw", "percent", "plus"])
def test_known_broker_system_checkpoint_password_variants(encoding: str) -> None:
    value = {"raw": PASSWORD, "percent": quote(PASSWORD, safe=""), "plus": quote_plus(PASSWORD)}[encoding]
    actual = sanitize_diagnostic("OperationalError: broker refused credential " + value, settings())
    assert value not in actual
    assert actual == "OperationalError: broker refused credential [redacted]"


@pytest.mark.parametrize("field", ["SYNTHETIC_PROVIDER_KEY", "SYNTHETIC_ENCRYPT_KEY",
                                   "SYNTHETIC_OSS_KEY", "SYNTHETIC_OCR_KEY"])
def test_configured_keys_never_remain(field: str) -> None:
    assert sanitize_diagnostic("OperationalError: refused " + field, settings()) == \
        "OperationalError: refused [redacted]"


@pytest.mark.parametrize("message", [
    "OperationalError: mongodb://other_user:other_password@local.invalid/db connection refused",
    "OperationalError: amqp://other_user:other%2Fpassword@local.invalid// connection refused",
    "OperationalError: amqp://other_user:other+password@local.invalid// connection refused",
    "OperationalError: Authorization: Bearer OTHER_SECRET",
    "OperationalError: authorization='Basic OTHER_SECRET'",
    "OperationalError: api_key=OTHER_SECRET",
    "OperationalError: {'password': 'OTHER_SECRET'}",
])
def test_uri_header_and_named_credential_secrets(message: str) -> None:
    result = sanitize_diagnostic(message, settings())
    assert all(value not in result for value in ("other_user", "other_password", "other%2Fpassword",
                                                "other+password", "OTHER_SECRET"))
    assert result.startswith("OperationalError:")
    if "connection refused" in message:
        assert result.endswith("connection refused")


@pytest.mark.parametrize("locale", ["en", "zh-CN", "zh-TW", "fr", "ms", "ja", "es"])
def test_nonsensitive_language_diagnostics_remain(locale: str) -> None:
    message = "OperationalError: " + translate("error.trial.workflow", locale)
    assert sanitize_diagnostic(message, settings()) == message
    assert sanitize_diagnostic("OperationalError: broker refused connection after 3 attempts", settings()) == \
        "OperationalError: broker refused connection after 3 attempts"


@pytest.mark.parametrize("stale", [False, True])
@pytest.mark.parametrize("encoding", ["raw", "percent", "plus"])
def test_queue_state_prefix_and_business_arguments_are_preserved(
    store: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch, stale: bool, encoding: str,
) -> None:
    config_settings = settings()
    monkeypatch.setattr(db_config, "get_settings", lambda: config_settings)
    value = {"raw": PASSWORD, "percent": quote(PASSWORD, safe=""), "plus": quote_plus(PASSWORD)}[encoding]
    publish = Mock(side_effect=OperationalError("broker refused credential " + value))
    monkeypatch.setattr(task.verify_config, "apply_async", publish)
    with store() as session:
        config = session.get(DbConfig, 12)
        assert config is not None
        if stale:
            config.verification_version = 2
            session.commit()
        with locale_scope("fr"):
            assert db_config._enqueue(session, 12, 1) is False
        session.refresh(config)
        if stale:
            assert config.status == 0 and config.verification_error is None
        else:
            assert config.status == 2 and config.doc_content is None
            assert config.verification_error == \
                "Verification queue unavailable: OperationalError: broker refused credential [redacted]"
    publish.assert_called_once_with(args=(12, 1), headers={"locale": "fr"})
    assert current_locale() == "en"


@pytest.mark.parametrize("credential", ["OTHER_SECRET'double\"slash\\suffix", "OTHER_SECRET\"double'slash\\suffix",
                                       "OTHER_SECRET\\trailing\\", "OTHER_SECRET\nline\t終点"])
@pytest.mark.parametrize("representation", ["repr", "json", "unicode-json"])
def test_known_escaped_credentials_in_repr_and_json(credential: str, representation: str) -> None:
    configured = settings()
    configured.bootstrap_password = credential
    value = {"detail": credential, "password": credential, "reason": "connection refused"}
    message = (repr(value) if representation == "repr" else
               json.dumps(value, ensure_ascii=representation != "unicode-json"))
    actual = sanitize_diagnostic("OperationalError: " + message, configured)
    assert "OTHER_SECRET" not in actual and "suffix" not in actual and "trailing" not in actual
    assert "終点" not in actual and "\\u7d42" not in actual
    assert "connection refused" in actual and actual.startswith("OperationalError: ")


@pytest.mark.parametrize("key", ["password", "Authorization", "api_key", "Cookie"])
@pytest.mark.parametrize("representation", ["repr", "json"])
def test_unconfigured_named_values_respect_quote_and_escape_boundaries(key: str, representation: str) -> None:
    credential = "OTHER_SECRET'double\"slash\\suffix"
    value = {key: credential, "reason": "connection refused"}
    message = repr(value) if representation == "repr" else json.dumps(value)
    actual = sanitize_diagnostic("OperationalError: " + message, settings())
    assert all(piece not in actual for piece in ("OTHER_SECRET", "double", "suffix"))
    assert "connection refused" in actual


@pytest.mark.parametrize("message", [
    "OperationalError: password='OTHER_SECRET\\'double\"slash\\\\suffix' reason=refused",
    'OperationalError: password="OTHER_SECRET\'double\\"slash\\\\suffix" reason=refused',
    "OperationalError: Authorization: Bearer OTHER_SECRET'double\\suffix reason=refused",
    "OperationalError: Authorization='Bearer OTHER_SECRET\\'double\\\\suffix' reason=refused",
    "OperationalError: https://host.invalid/?password=OTHER_SECRET'double\\suffix&port=123",
])
def test_header_and_query_quotes_keep_following_diagnostics(message: str) -> None:
    actual = sanitize_diagnostic(message, settings())
    assert all(piece not in actual for piece in ("OTHER_SECRET", "double", "suffix"))
    assert "reason=refused" in actual or "port=123" in actual


@pytest.mark.parametrize("representation", ["raw", "percent", "plus", "repr", "json"])
def test_complete_secret_is_removed_before_1000_character_cap(representation: str) -> None:
    credential = "SYNTHETIC_SECRET_AT_TRUNCATION_END'double\"slash\\suffix"
    configured = settings()
    configured.bootstrap_password = credential
    value = {"raw": credential, "percent": quote(credential, safe=""), "plus": quote_plus(credential),
             "repr": repr(credential)[1:-1], "json": json.dumps(credential)[1:-1]}[representation]
    actual = safe_exception_diagnostic(RuntimeError("x" * 979 + " " + value), configured)
    assert len(actual) == 1000 and actual.startswith("RuntimeError: " + "x" * 979 + " ")
    assert "SYNTH" not in actual and "SECRET" not in actual


def test_nonsensitive_long_diagnostic_keeps_prefix_and_cap() -> None:
    actual = safe_exception_diagnostic(RuntimeError("x" * 1400), settings())
    assert actual == ("RuntimeError: " + "x" * 1400)[:1000]


@pytest.mark.parametrize("locale", ["en", "zh-CN", "zh-TW", "fr", "ms", "ja", "es"])
def test_business_error_translation_and_args_remain(locale: str) -> None:
    error = BusinessError(400, "error.file.uploadFailed", 200, PASSWORD)
    with locale_scope(locale):
        actual = safe_exception_diagnostic(error, settings())
    assert actual == "BusinessError: " + translate("error.file.uploadFailed", locale, "[redacted]")
    assert error.message_args == (PASSWORD,) and current_locale() == "en"


def test_actual_queue_failure_redacts_before_cap_and_keeps_args(
    store: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured = settings()
    configured.bootstrap_password = "SYNTHETIC_SECRET_AT_TRUNCATION_END"
    error = OperationalError("x" * 979 + " " + configured.bootstrap_password)
    publish = Mock(side_effect=error)
    monkeypatch.setattr(db_config, "get_settings", lambda: configured)
    monkeypatch.setattr(task.verify_config, "apply_async", publish)
    with store() as session, locale_scope("ja"):
        assert db_config._enqueue(session, 12, 1) is False
        config = session.get(DbConfig, 12)
        assert config is not None and config.status == 2 and config.verification_error is not None
        assert config.verification_error.startswith("Verification queue unavailable: OperationalError: ")
        assert len(config.verification_error) == len("Verification queue unavailable: ") + 1000
        assert "SYNTH" not in config.verification_error
    publish.assert_called_once_with(args=(12, 1), headers={"locale": "ja"})
