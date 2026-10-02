"""Target-specific read checks without changing accepted relational execution."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

import sqlglot
from sqlalchemy import event
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError
from sqlglot import exp

from app.adapters.cancellation import DatabaseExecutionInterrupted, DatabaseWriteOutcomeUnknown
from app.adapters.diagnostics import sanitize_diagnostic
from app.adapters.native_reads import ReadFieldCheck, sequence_read
from app.adapters.relational import RelationalAdapter
from app.adapters.safety import UnsafeStatement, check_statement
from app.adapters.types import DbConnectionConfig, QueryResult, SchemaMetadata


def validate_timeout(value: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError("timeout_seconds must be positive")


@dataclass
class _Dispatch:
    statement: str
    dispatched: bool = False
    cancel_event: threading.Event | None = None


_DISPATCH: ContextVar[_Dispatch | None] = ContextVar("native_statement_dispatch", default=None)


def execution_cancel_event() -> threading.Event | None:
    state = _DISPATCH.get()
    return state.cancel_event if state is not None else None


class NativeRelationalAdapter(RelationalAdapter):
    @contextmanager
    def _connection(self, config: DbConnectionConfig, timeout_seconds: int) -> Iterator[Connection]:
        with super()._connection(config, timeout_seconds) as connection:
            state = _DISPATCH.get()
            if state is not None:
                def before_execute(_connection: object, _cursor: object, statement: str,
                                   _parameters: object, _context: object, _many: bool) -> None:
                    if statement == state.statement:
                        state.dispatched = True
                event.listen(connection, "before_cursor_execute", before_execute)
            if state is not None and self.dialect == "oracle":
                # This engine belongs to this call only. SQLAlchemy 2.1 RowMapping otherwise
                # retains normalized lookup aliases that can collapse distinct ID/id values.
                connection.dialect.requires_name_normalize = False
                connection = connection.execution_options(driver_column_names=True)
            yield connection

    def _validate_native_statement(self, statement: str) -> None:
        root = sqlglot.parse_one(statement, read=self.dialect)
        if isinstance(root, (exp.Show, exp.Describe)):
            raise UnsafeStatement("SHOW/DESC client commands are unsupported for this database")

    def is_read_only(self, statement: str) -> bool:
        return self._read_only(statement)

    def _read_only(self, statement: str, field_exists: ReadFieldCheck | None = None) -> bool:
        policy = check_statement(statement, self.dialect)
        self._validate_native_statement(statement)
        if not policy.read_only or sequence_read(statement, self.dialect, field_exists=field_exists):
            return False
        root = sqlglot.parse_one(statement, read=self.dialect)
        if any(isinstance(node, exp.Lock) for node in root.walk()):
            return False
        return not any(
            isinstance(node, exp.Var) and node.name.upper() in {"UPDLOCK", "XLOCK"}
            for hint in root.find_all(exp.WithTableHint) for node in hint.walk()
        )

    def _is_read_only_for_config(self, config: DbConnectionConfig, statement: str, timeout_seconds: int) -> bool:
        return self.is_read_only(statement)

    def _sequence_for_config(self, config: DbConnectionConfig, statement: str, timeout_seconds: int) -> bool:
        return sequence_read(statement, self.dialect)

    def execute(self, config: DbConnectionConfig, statement: str, *, trial_mode: bool = False,
                timeout_seconds: int = 30, max_rows: int = 100,
                cancel_event: threading.Event | None = None) -> QueryResult:
        check_statement(statement, self.dialect, trial_mode=trial_mode)
        self._validate_native_statement(statement)
        if cancel_event is not None and cancel_event.is_set():
            raise DatabaseExecutionInterrupted("cancelled", cancel_request_sent=False,
                                               server_termination_confirmed=False,
                                               write_outcome_unknown=False)
        if trial_mode and not self._is_read_only_for_config(config, statement, timeout_seconds):
            raise UnsafeStatement("Trial mode permits read-only statements only")
        sequence = self._sequence_for_config(config, statement, timeout_seconds)
        state = _Dispatch(statement, cancel_event=cancel_event)
        token = _DISPATCH.set(state)
        try:
            return super().execute(config, statement, trial_mode=trial_mode,
                                   timeout_seconds=timeout_seconds, max_rows=max_rows,
                                   cancel_event=cancel_event)
        except DatabaseExecutionInterrupted as exc:
            if sequence and state.dispatched:
                raise DatabaseExecutionInterrupted(
                    exc.reason, cancel_request_sent=exc.cancel_request_sent,
                    server_termination_confirmed=exc.server_termination_confirmed,
                    write_outcome_unknown=True, cancel_error=exc.cancel_error,
                ) from exc
            raise
        except SQLAlchemyError as exc:
            if sequence and state.dispatched:
                raise DatabaseWriteOutcomeUnknown(
                    "Sequence-advancing statement failed after dispatch; outcome may be unknown"
                ) from exc
            raise
        finally:
            _DISPATCH.reset(token)

    def extract_metadata(self, config: DbConnectionConfig, *, timeout_seconds: int = 30) -> SchemaMetadata:
        metadata = super().extract_metadata(config, timeout_seconds=timeout_seconds)
        if metadata["errorMessage"] is not None:
            metadata["errorMessage"] = sanitize_diagnostic(metadata["errorMessage"], config)
        return metadata
