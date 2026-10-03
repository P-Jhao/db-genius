"""Safe diagnostics at handlers, including Celery's startup logging setup."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Mapping

from app.agent.protocol_errors import ProtocolCode, ProtocolStage
from app.core.config import Settings
from app.core.diagnostics import sanitize_diagnostic

_SQL = re.compile(r"(?is)\[(?:SQL|parameters):.*?\]")
_CONTENT = re.compile(r"(?is)\b(?:prompt|reasoning|response_body|tool_output|sql_result)\s*[:=].*")
_SENSITIVE = re.compile(r"(?i)password|passwd|secret|token|api.?key|authorization|cookie")
_STANDARD = frozenset(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}
_TERMS = frozenset({"done", "error", "partial", "cancelled", "timeout", "aborted",
                    "write_outcome_unknown", "stale", "sql_query", "workflow", "db_compare", "simple_chat"})


def redact(message: str, settings: Settings) -> str:
    value = sanitize_diagnostic(message, settings)
    value = _SQL.sub("[database statement redacted]", value)
    return _CONTENT.sub("[content-redacted]", value)


def safe_value(value: object) -> object:
    if type(value) is ProtocolCode:
        return value.text
    if type(value) is ProtocolStage:
        return value.value
    if isinstance(value, BaseException):
        return type(value).__name__
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, str):
        if value in _TERMS or re.fullmatch(r"[0-9a-f]{32}", value):
            return value
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,40}(?:Error|Exception)", value):
            return value
    if isinstance(value, Mapping):
        return {str(key): "[redacted]" if _SENSITIVE.search(str(key)) else safe_value(item)
                for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe_value(item) for item in value]
    return "[redacted]"


class SafeLogFilter(logging.Filter):
    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings

    def filter(self, record: logging.LogRecord) -> bool:
        template = (str(safe_value(record.msg)) if isinstance(record.msg, (Mapping, BaseException))
                    else str(record.msg))
        if record.args:
            arguments = (safe_value(record.args) if isinstance(record.args, Mapping)
                         else tuple(safe_value(value) for value in record.args))
            try:
                template = template % arguments
            except (TypeError, ValueError):
                template = "[invalid log format]"
        if record.exc_info is not None and record.exc_info[0] is not None:
            template += " errorType=" + record.exc_info[0].__name__
        record.msg, record.args = redact(template, self.settings), ()
        for key in set(record.__dict__) - _STANDARD:
            record.__dict__[key] = "[redacted]" if _SENSITIVE.search(key) else safe_value(record.__dict__[key])
        record.exc_info = record.exc_text = record.stack_info = None
        return True


def configure_logging(settings: Settings) -> None:
    global _record_filter, _installed_factory
    _record_filter = SafeLogFilter(settings)
    current_factory = logging.getLogRecordFactory()
    if current_factory is not _installed_factory:
        _installed_factory = record_factory(current_factory)
        logging.setLogRecordFactory(_installed_factory)
    root = logging.getLogger()
    if not root.handlers:
        root.addHandler(logging.StreamHandler())
    loggers = [root, *(logger for logger in logging.Logger.manager.loggerDict.values()
                       if isinstance(logger, logging.Logger))]
    for logger in loggers:
        for handler in logger.handlers:
            for item in list(handler.filters):
                if isinstance(item, SafeLogFilter):
                    handler.removeFilter(item)
            handler.addFilter(SafeLogFilter(settings))


_record_filter: SafeLogFilter | None = None
_installed_factory: Callable[..., logging.LogRecord] | None = None


class SafeRecord(logging.LogRecord):
    def getMessage(self) -> str:
        # Logger.makeRecord attaches extra *after* calling the factory. Sanitize
        # here as well, before any formatter can interpolate those attributes.
        if _record_filter is not None:
            _record_filter.filter(self)
        return super().getMessage()


def record_factory[**P](factory: Callable[P, logging.LogRecord]) -> Callable[P, logging.LogRecord]:
    def create(*args: P.args, **kwargs: P.kwargs) -> logging.LogRecord:
        original = factory(*args, **kwargs)
        secured = SafeRecord("", 0, "", 0, "", (), None)
        secured.__dict__.update(original.__dict__)
        return secured
    return create
