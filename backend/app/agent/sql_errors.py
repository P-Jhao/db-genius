"""Only known, rolled-back SQL diagnostics may be returned for model correction."""

import re
import sqlite3

from sqlalchemy.exc import DBAPIError

from app.adapters.types import QueryResult

_SQLSTATES = frozenset({"42601", "42P01", "42703", "42702", "42803", "42883"})
_MYSQL_CODES = frozenset({1052, 1054, 1064, 1146})
_SQLITE_MESSAGE = re.compile(
    r"^(?:no such (?:table|column|function):|ambiguous column name:|near .+: syntax error$)",
    re.IGNORECASE,
)


def repairable(error: DBAPIError, statement: str) -> bool:
    if (error.statement is None or error.statement.strip() != statement.strip() or
            error.connection_invalidated or any(
                "Rollback also failed" in note for note in getattr(error, "__notes__", []))):
        return False
    original = error.orig
    if getattr(original, "sqlstate", None) in _SQLSTATES:
        return True
    arguments = getattr(original, "args", ())
    if arguments and isinstance(arguments[0], int) and arguments[0] in _MYSQL_CODES:
        return True
    return isinstance(original, sqlite3.OperationalError) and _SQLITE_MESSAGE.match(str(original)) is not None


def failure(error: DBAPIError) -> QueryResult:
    original = error.orig
    result: QueryResult = {"success": False, "error": str(original)[:1000]}
    state = getattr(original, "sqlstate", None)
    if isinstance(state, str):
        result["sqlState"] = state
    code = getattr(original, "sqlite_errorcode", None)
    arguments = getattr(original, "args", ())
    if code is None and arguments and isinstance(arguments[0], int):
        code = arguments[0]
    if isinstance(code, int):
        result["errorCode"] = code
    return result
