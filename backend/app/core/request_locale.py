"""Explicit locale scopes for HTTP calls and independently delivered worker tasks."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from app.core.localization import select_locale

_locale: ContextVar[str] = ContextVar("sqlchat_request_locale", default="en")


def current_locale() -> str:
    return _locale.get()


@contextmanager
def locale_scope(accept_language: str | None) -> Iterator[None]:
    token = _locale.set(select_locale(accept_language))
    try:
        yield
    finally:
        _locale.reset(token)
