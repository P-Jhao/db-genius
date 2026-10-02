"""SQL Server dbo metadata through serialized pymssql/FreeTDS connections."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.engine import URL, Connection, Engine
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.pool import NullPool

from app.adapters.cancellation import DatabaseExecutionInterrupted
from app.adapters.native_relational import NativeRelationalAdapter, execution_cancel_event, validate_timeout
from app.adapters.types import DbConnectionConfig

# DB-Lib timeout/login_timeout are process-wide. All adapter-owned sessions share this lock.
_DRIVER_LOCK = threading.Lock()


class SqlServerAdapter(NativeRelationalAdapter):
    db_type = "sqlserver"
    dialect = "tsql"
    driver = "mssql+pymssql"
    default_port = 1433
    metadata_schema = "dbo"
    watchdog_on_timeout = True

    def _engine(self, config: DbConnectionConfig, timeout_seconds: int) -> Engine:
        self.validate_config(config)
        validate_timeout(timeout_seconds)
        url = URL.create(self.driver, username=config.username, password=config.password,
                         host=config.host, port=config.port, database=config.db_name)
        return create_engine(url, poolclass=NullPool,
                             connect_args={"timeout": timeout_seconds,
                                           "login_timeout": min(timeout_seconds, 10),
                                           "charset": "UTF-8", "use_datetime2": True,
                                           "encryption": "require"})

    @contextmanager
    def _connection(self, config: DbConnectionConfig, timeout_seconds: int) -> Iterator[Connection]:
        self.validate_config(config)
        validate_timeout(timeout_seconds)
        deadline = time.monotonic() + timeout_seconds
        signal = execution_cancel_event()
        while True:
            if signal is not None and signal.is_set():
                raise DatabaseExecutionInterrupted("cancelled", cancel_request_sent=False,
                                                   server_termination_confirmed=False,
                                                   write_outcome_unknown=False)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("SQL Server driver session slot timed out before dispatch")
            if _DRIVER_LOCK.acquire(timeout=min(remaining, 0.05)):
                break
        try:
            with super()._connection(config, timeout_seconds) as connection:
                yield connection
        finally:
            _DRIVER_LOCK.release()

    def _set_timeout(self, connection: Connection, timeout_seconds: int, trial_mode: bool) -> None:
        validate_timeout(timeout_seconds)
        # SQL Server has no READ ONLY transaction; native AST guard rejects trial writes.
        # read_only=True in pymssql is routing intent, not an enforcement mechanism.

    def _cancel_running_statement(self, config: DbConnectionConfig, connection: Connection,
                                  connection_id: int | None) -> None:
        raise RuntimeError("pymssql has no safe in-flight cancel API; await driver timeout")

    def _server_confirmed_interrupt(self, exc: SQLAlchemyError) -> bool:
        return False

    def _driver_timeout(self, exc: SQLAlchemyError) -> bool:
        if not isinstance(exc, DBAPIError):
            return False
        # DB-Lib SYBETIME: error text alone is not evidence of a driver timeout.
        args = getattr(exc.orig, "args", ())
        return bool(args and args[0] == 20003)
