"""Oracle service-name connections and current-user metadata in Thin mode."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import oracledb
from sqlalchemy import create_engine
from sqlalchemy.engine import URL, Connection, Engine
from sqlalchemy.engine.reflection import Inspector
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.pool import NullPool
from sqlalchemy.sql.elements import quoted_name

from app.adapters.native_reads import sequence_read
from app.adapters.native_relational import NativeRelationalAdapter, validate_timeout
from app.adapters.oracle_metadata import read_table
from app.adapters.oracle_read_catalog import OracleReadCatalog
from app.adapters.relational import _json_value
from app.adapters.types import DbConnectionConfig, SchemaMetadata, TableMetadata


class OracleAdapter(NativeRelationalAdapter):
    db_type = "oracle"
    dialect = "oracle"
    driver = "oracle+oracledb"
    default_port = 1521
    watchdog_on_timeout = True

    def _catalog(self, config: DbConnectionConfig, timeout_seconds: int) -> OracleReadCatalog:
        return OracleReadCatalog(lambda: self._connection(config, timeout_seconds),
                                 lambda connection: self._set_timeout(connection, timeout_seconds, True))

    def is_read_only_for_config(self, config: DbConnectionConfig, statement: str, *, timeout_seconds: int = 30) -> bool:
        with self._catalog(config, timeout_seconds) as catalog:
            return self._read_only(statement, catalog.field_exists)

    def _is_read_only_for_config(self, config: DbConnectionConfig, statement: str, timeout_seconds: int) -> bool:
        return self.is_read_only_for_config(config, statement, timeout_seconds=timeout_seconds)

    def _sequence_for_config(self, config: DbConnectionConfig, statement: str, timeout_seconds: int) -> bool:
        with self._catalog(config, timeout_seconds) as catalog:
            return sequence_read(statement, self.dialect, field_exists=catalog.field_exists)

    def _engine(self, config: DbConnectionConfig, timeout_seconds: int) -> Engine:
        self.validate_config(config)
        validate_timeout(timeout_seconds)
        if not oracledb.is_thin_mode():
            raise RuntimeError("Oracle adapter requires python-oracledb Thin mode")
        url = URL.create(self.driver, username=config.username, password=config.password,
                         host=config.host, port=config.port, query={"service_name": config.db_name})
        def connect() -> oracledb.Connection:
            driver = oracledb.connect(user=config.username, password=config.password,
                                      host=config.host, port=config.port, service_name=config.db_name,
                                      tcp_connect_timeout=float(min(timeout_seconds, 10)))
            # Configure before SQLAlchemy emits dialect-initialization SELECTs.
            driver.call_timeout = timeout_seconds * 1000
            return driver
        return create_engine(url, poolclass=NullPool, coerce_to_decimal=True, creator=connect)

    def test_connection(self, config: DbConnectionConfig) -> bool:
        with self._connection(config, 5) as connection:
            self._set_timeout(connection, 5, False)
            return connection.exec_driver_sql("SELECT 1 FROM DUAL").scalar_one() == 1

    def _set_timeout(self, connection: Connection, timeout_seconds: int, trial_mode: bool) -> None:
        validate_timeout(timeout_seconds)
        driver = connection.connection.driver_connection
        if not isinstance(driver, oracledb.Connection):
            raise TypeError("Oracle driver connection is unavailable")
        driver.call_timeout = timeout_seconds * 1000
        if trial_mode:
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")

    def _qualified_name(self, connection: Connection, table: str) -> str:
        # SQLAlchemy normalizes unquoted Oracle names; quoted_name keeps quoted case.
        preparer = connection.dialect.identifier_preparer
        name = str(preparer.quote(table))
        if self.metadata_schema is not None:
            return f"{preparer.quote_identifier(self.metadata_schema)}.{name}"
        return name

    def extract_metadata(self, config: DbConnectionConfig, *, timeout_seconds: int = 30) -> SchemaMetadata:
        with self._connection(config, timeout_seconds) as connection:
            self._set_timeout(connection, timeout_seconds, False)
            user: object = connection.exec_driver_sql(
                "SELECT SYS_CONTEXT('USERENV', 'SESSION_USER') FROM DUAL"
            ).scalar_one()
            if not isinstance(user, str) or not user:
                raise TypeError("Oracle session user is unavailable")
            connection.rollback()
            self._set_timeout(connection, timeout_seconds, True)
            reader = _OracleMetadataSession(connection, user)
            metadata = NativeRelationalAdapter.extract_metadata(reader, config, timeout_seconds=timeout_seconds)
            metadata["schemaName"] = user
            return metadata

    def _cancel_running_statement(self, config: DbConnectionConfig, connection: Connection,
                                  connection_id: int | None) -> None:
        driver = connection.connection.driver_connection
        if not isinstance(driver, oracledb.Connection):
            raise TypeError("Oracle driver connection is unavailable for cancellation")
        driver.cancel()

    def _server_confirmed_interrupt(self, exc: SQLAlchemyError) -> bool:
        if not isinstance(exc, DBAPIError):
            return False
        details = getattr(exc.orig, "args", ())
        return bool(details and getattr(details[0], "code", None) == 1013)

    def _driver_timeout(self, exc: SQLAlchemyError) -> bool:
        if not isinstance(exc, DBAPIError):
            return False
        details = getattr(exc.orig, "args", ())
        code = getattr(details[0], "full_code", "") if details else ""
        return code in {"DPY-4024", "DPI-1067", "DPI-1080"}

    def _json_value(self, value: object) -> object:
        if isinstance(value, oracledb.LOB):
            return _json_value(value.read())
        return _json_value(value)


class _OracleMetadataSession(OracleAdapter):
    """A per-call schema scope; never mutates the shared adapter instance."""

    def __init__(self, connection: Connection, username: str) -> None:
        self._metadata_connection = connection
        self.metadata_schema = quoted_name(username, True)

    @contextmanager
    def _connection(self, config: DbConnectionConfig, timeout_seconds: int) -> Iterator[Connection]:
        yield self._metadata_connection

    def _set_timeout(self, connection: Connection, timeout_seconds: int, trial_mode: bool) -> None:
        validate_timeout(timeout_seconds)  # Already configured before metadata reflection.


    def _read_table(self, connection: Connection, inspector: Inspector,
                    table_name: str) -> tuple[TableMetadata, str | None]:
        if self.metadata_schema is None:
            raise ValueError("Oracle metadata session schema is unavailable")
        return read_table(connection, inspector, table_name, self.metadata_schema,
                          self._qualified_name(connection, table_name))
