"""Synchronous database execution cancellation state and watchdog."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Literal

from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

InterruptReason = Literal["cancelled", "timeout"]


def cancel_postgresql_statement(connection: Connection) -> None:
    driver_connection = connection.connection.driver_connection
    if driver_connection is None:
        raise RuntimeError("PostgreSQL driver connection is unavailable for cancellation")
    driver_connection.cancel_safe(timeout=3)


def cancel_mysql_statement(connection_id: int,
                           open_control: Callable[[], AbstractContextManager[Connection]]) -> None:
    # The control session is separate because the executing session is blocked in its driver.
    with open_control() as control:
        control.exec_driver_sql(f"KILL QUERY {connection_id}")


def server_confirmed_interrupt(exc: SQLAlchemyError) -> bool:
    if not isinstance(exc, DBAPIError):
        return False
    original = exc.orig
    if getattr(original, "sqlstate", None) == "57014":
        return True
    args = getattr(original, "args", ())
    return bool(args and args[0] in (1317, 3024))


class DatabaseExecutionInterrupted(TimeoutError):
    """An execution stopped or was abandoned; a write may have taken effect."""

    def __init__(self, reason: InterruptReason, *, cancel_request_sent: bool,
                 server_termination_confirmed: bool, write_outcome_unknown: bool,
                 cancel_error: Exception | None = None) -> None:
        self.reason = reason
        self.cancel_request_sent = cancel_request_sent
        self.server_termination_confirmed = server_termination_confirmed
        self.write_outcome_unknown = write_outcome_unknown
        self.cancel_error = cancel_error
        super().__init__(
            f"Database execution {reason}; cancel request sent={cancel_request_sent}; "
            f"server termination confirmed={server_termination_confirmed}; "
            f"write outcome unknown={write_outcome_unknown}"
        )


class DatabaseWriteOutcomeUnknown(RuntimeError):
    """The statement ran, but the write commit could not be confirmed."""


class ExecutionWatchdog:
    def __init__(self, cancel_event: threading.Event | None, timeout_seconds: int,
                 send_cancel: Callable[[], None]) -> None:
        self.cancel_event = cancel_event
        self.deadline = time.monotonic() + timeout_seconds
        self.send_cancel = send_cancel
        self.reason: InterruptReason | None = None
        self.cancel_request_sent = False
        self.cancel_error: Exception | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._watch, name="sqlchat-db-cancel", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join()

    def _watch(self) -> None:
        while not self._stop.wait(0.02):
            if self.cancel_event is not None and self.cancel_event.is_set():
                self.reason = "cancelled"
                break
            if time.monotonic() >= self.deadline:
                self.reason = "timeout"
                break
        if self.reason is None or self._stop.is_set():
            return
        try:
            self.send_cancel()
            self.cancel_request_sent = True
        except Exception as exc:  # noqa: BLE001 - cancellation failures must reach the executing thread
            self.cancel_error = exc
