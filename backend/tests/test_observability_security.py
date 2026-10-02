"""Synthetic diagnostics only; no live credentials or business contents."""

import io
import logging
from urllib.parse import quote, quote_plus

import pytest
from celery.signals import after_setup_logger  # type: ignore[import-untyped]

from app.core.config import Settings
from app.core.observability_logging import SafeLogFilter, configure_logging
from app.tasks import celery_app as task_app

PASSWORD = "S14 synthetic+/ password?"


@pytest.mark.parametrize("message", [
    "raw " + PASSWORD,
    "encoded " + quote(PASSWORD, safe=""),
    "encoded " + quote_plus(PASSWORD),
    {"password": PASSWORD, "nested": {"sql_result": "SYNTHETIC_RESULT"}},
    'Authorization: Bearer SYNTHETIC_TOKEN',
    'authorization="Basic SYNTHETIC_TOKEN"',
    "mongodb://other_user:other_password@local.invalid/db",
    'prompt=SYNTHETIC_PROMPT',
    "[SQL: SELECT 'SYNTHETIC_SQL'] [parameters: ('SYNTHETIC_SQL',)]",
])
def test_message_redaction(message: object) -> None:
    record = logging.LogRecord("synthetic", logging.ERROR, "synthetic", 1, message, (), None)
    SafeLogFilter(Settings(trial_builtin_password=PASSWORD)).filter(record)
    content = record.getMessage()
    assert all(value not in content for value in (
        PASSWORD, quote(PASSWORD, safe=""), quote_plus(PASSWORD), "SYNTHETIC_RESULT",
        "SYNTHETIC_TOKEN", "other_user", "other_password", "SYNTHETIC_PROMPT", "SYNTHETIC_SQL",
    ))


def test_known_urls_bootstrap_and_exception_are_cleared() -> None:
    settings = Settings(bootstrap_password=PASSWORD,
                        database_url=f"postgresql://user:{quote(PASSWORD, safe='')}@local.invalid/db")
    record = logging.LogRecord("synthetic", logging.ERROR, "synthetic", 1,
                               "event errorType=%s credential=%s", (RuntimeError(PASSWORD), PASSWORD), None)
    record.exc_text = PASSWORD
    record.stack_info = PASSWORD
    SafeLogFilter(settings).filter(record)
    assert PASSWORD not in record.getMessage() and "RuntimeError" in record.getMessage()
    assert record.exc_text is None
    assert record.exc_info is None
    assert record.stack_info is None


def test_worker_setup_and_late_formatter_do_not_expose_extra(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings()
    settings.default_model_api_key = PASSWORD
    monkeypatch.setattr(task_app, "get_settings", lambda: settings)
    old_factory = logging.getLogRecordFactory()
    stream = io.StringIO()
    logger = logging.getLogger("s14.synthetic.late")
    logger.setLevel(logging.WARNING)
    logger.propagate = False
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s %(headers)s %(payload)s %(token)s"))
    try:
        after_setup_logger.send(sender="synthetic-worker")
        # Handler created after the signal: SafeRecord sanitizes extras during formatting.
        logger.addHandler(handler)
        logger.warning("event errorType=%s", RuntimeError(PASSWORD), extra={
            "headers": {"Authorization": "Bearer " + PASSWORD},
            "payload": {"prompt": "SYNTHETIC_PROMPT"}, "token": "SYNTHETIC_TOKEN",
        })
        assert PASSWORD not in stream.getvalue()
        assert "SYNTHETIC_PROMPT" not in stream.getvalue()
        assert "SYNTHETIC_TOKEN" not in stream.getvalue()
        assert "RuntimeError" in stream.getvalue()
    finally:
        logger.removeHandler(handler)
        logging.setLogRecordFactory(old_factory)


def test_configured_root_handler_retains_types_and_safe_numbers() -> None:
    configure_logging(Settings())
    record = logging.LogRecord("synthetic", logging.ERROR, "synthetic", 1,
                               "event errorType=%s count=%s", ("ConnectionError", 3), None)
    SafeLogFilter(Settings()).filter(record)
    assert "ConnectionError" in record.getMessage() and "count=3" in record.getMessage()


@pytest.mark.parametrize("representation", ["repr", "json"])
def test_logging_reuses_accepted_escape_redaction(representation: str) -> None:
    import json

    credential = "OTHER_SECRET'double\"slash\\suffix"
    configured = Settings(bootstrap_password=credential)
    value = {"detail": credential, "password": credential}
    text = repr(value) if representation == "repr" else json.dumps(value)
    record = logging.LogRecord("synthetic", logging.ERROR, "synthetic", 1, text, (), None)
    SafeLogFilter(configured).filter(record)
    assert "OTHER_SECRET" not in record.getMessage() and "suffix" not in record.getMessage()


def test_exception_object_and_traceback_keep_only_type() -> None:
    error = RuntimeError("SYNTHETIC_UNKNOWN_PROVIDER_BODY")
    record = logging.LogRecord("synthetic", logging.ERROR, "synthetic", 1, error, (),
                               (RuntimeError, error, None))
    SafeLogFilter(Settings()).filter(record)
    assert "SYNTHETIC_UNKNOWN_PROVIDER_BODY" not in record.getMessage()
    assert "RuntimeError" in record.getMessage() and record.exc_info is None
