"""Private, parameterized Oracle field evidence for sequence-like references."""

from collections.abc import Callable
from contextlib import AbstractContextManager, ExitStack
from typing import Self

from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError
from sqlglot import exp

from app.adapters.safety import UnsafeStatement


def _identifier(value: object) -> str | None:
    if not isinstance(value, exp.Identifier):
        return None
    return value.name if value.args.get("quoted") else value.name.upper()


class OracleReadCatalog:
    """One check owns one lazy connection; repeated references share exact catalog evidence."""

    def __init__(self, connect: Callable[[], AbstractContextManager[Connection]],
                 setup: Callable[[Connection], None]) -> None:
        self._connect, self._setup = connect, setup
        self._stack = ExitStack()
        self._connection: Connection | None = None
        self._owner: str | None = None
        self._fields: dict[tuple[str, str, str], bool] = {}

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        try:
            self._stack.close()
        except SQLAlchemyError as error:
            raise UnsafeStatement("Oracle read-only catalog cleanup failed") from error

    def field_exists(self, column: exp.Column, source: exp.Expression) -> bool:
        if not isinstance(source, exp.Table) or source.args.get("catalog") is not None:
            return False
        table, field = _identifier(source.this), _identifier(column.this)
        if table is None or field is None:
            return False
        try:
            if self._connection is None:
                self._connection = self._stack.enter_context(self._connect())
                self._setup(self._connection)
                owner: object = self._connection.exec_driver_sql(
                    "SELECT SYS_CONTEXT('USERENV', 'CURRENT_SCHEMA') FROM DUAL"
                ).scalar_one()
                if not isinstance(owner, str) or not owner:
                    raise UnsafeStatement("Oracle read-only catalog schema identity is unavailable")
                self._owner = owner
            owner = _identifier(source.args.get("db")) if source.args.get("db") is not None else self._owner
            if owner is None:
                raise UnsafeStatement("Oracle read-only catalog owner is unavailable")
            key = (owner, table, field)
            if key not in self._fields:
                result = self._connection.exec_driver_sql(
                    "SELECT 1 FROM ALL_TAB_COLUMNS WHERE OWNER=:owner "
                    "AND TABLE_NAME=:table_name AND COLUMN_NAME=:column_name AND ROWNUM<=1",
                    {"owner": owner, "table_name": table, "column_name": field},
                )
                try:
                    self._fields[key] = result.scalar_one_or_none() == 1
                finally:
                    result.close()
            return self._fields[key]
        except SQLAlchemyError as error:
            raise UnsafeStatement("Oracle read-only catalog could not establish ordinary-field evidence") from error
