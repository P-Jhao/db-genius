"""SQLGlot-backed guard for a single target-database statement."""

import re
from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError, TokenError, UnsupportedError
from sqlglot.tokens import Tokenizer


class UnsafeStatement(ValueError):
    pass


@dataclass(frozen=True)
class StatementPolicy:
    read_only: bool
    returns_rows: bool


_FORBIDDEN = (exp.Drop, exp.TruncateTable)
_WRITES = (exp.Insert, exp.Update, exp.Delete, exp.Merge, exp.Create, exp.Alter, exp.Drop,
           exp.TruncateTable, exp.Into)
_READ_ROOTS = (exp.Select, exp.Union, exp.Intersect, exp.Except, exp.Show, exp.Describe)
_WRITE_ROOTS = (exp.Insert, exp.Update, exp.Delete, exp.Merge, exp.Create, exp.Alter)
_PG_SHOW = re.compile(r"SHOW\s+(?:ALL|[A-Za-z_][A-Za-z_0-9.]*)\s*;?\s*\Z", re.IGNORECASE)
_PG_EXPLAIN = re.compile(r"EXPLAIN\s+(?:ANALYZE\s+)?(.+)\Z", re.IGNORECASE | re.DOTALL)


def check_statement(statement: str, dialect: str, *, trial_mode: bool = False) -> StatementPolicy:
    if not statement or not statement.strip():
        raise UnsafeStatement("SQL statement is empty")
    try:
        for token in Tokenizer().tokenize(statement):
            if any(comment.lstrip().upper().startswith(("!", "M!")) for comment in token.comments):
                raise UnsafeStatement("Executable SQL comments are not supported")
        parsed = [node for node in sqlglot.parse(statement, read=dialect, error_level="RAISE") if node]
    except (ParseError, TokenError, UnsupportedError) as exc:
        raise UnsafeStatement("SQL statement could not be safely parsed") from exc
    if len(parsed) != 1:
        raise UnsafeStatement("Multiple SQL statements are not supported")
    root = parsed[0]
    if isinstance(root, exp.Command):
        if dialect == "postgres":
            if _PG_SHOW.fullmatch(statement.strip()):
                return StatementPolicy(read_only=True, returns_rows=True)
            explain = _PG_EXPLAIN.fullmatch(statement.strip())
            if explain:
                inner = check_statement(explain.group(1), dialect, trial_mode=trial_mode)
                return StatementPolicy(read_only=inner.read_only, returns_rows=True)
        raise UnsafeStatement("Unsupported SQL command")
    if any(isinstance(node, _FORBIDDEN) for node in root.walk()):
        raise UnsafeStatement("DROP and TRUNCATE operations are forbidden")
    if isinstance(root, exp.Alter) and any(isinstance(node, exp.Drop) for node in root.walk()):
        raise UnsafeStatement("ALTER ... DROP is forbidden")
    if not isinstance(root, _READ_ROOTS + _WRITE_ROOTS):
        raise UnsafeStatement("Unsupported SQL statement")
    read_only = isinstance(root, _READ_ROOTS) and not any(
        isinstance(node, _WRITES) for node in root.walk()
    )
    if trial_mode and not read_only:
        raise UnsafeStatement("Trial mode permits read-only statements only")
    returns_rows = isinstance(root, _READ_ROOTS) or bool(root.args.get("returning"))
    return StatementPolicy(read_only=read_only, returns_rows=returns_rows)
