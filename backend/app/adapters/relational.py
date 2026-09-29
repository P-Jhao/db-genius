"""Shared MySQL/PostgreSQL execution and metadata operations."""

from __future__ import annotations

import base64
import math
import time as clock
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import URL, Connection, Engine
from sqlalchemy.engine.reflection import Inspector
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool

from app.adapters.document import render_document
from app.adapters.safety import check_statement
from app.adapters.types import (
    ColumnMetadata,
    DbConnectionConfig,
    IndexMetadata,
    QueryResult,
    SchemaMetadata,
    TableMetadata,
)


def _json_value(value: object) -> object:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, timedelta):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (bytes, memoryview)):
        return base64.b64encode(bytes(value)).decode("ascii")
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("Database result contains a non-string object key")
        return {key: _json_value(item) for key, item in value.items()}
    raise TypeError(f"Unsupported database value type: {type(value).__name__}")


class RelationalAdapter:
    db_type: str
    dialect: str
    driver: str
    default_port: int
    metadata_schema: str | None = None

    def validate_config(self, config: DbConnectionConfig) -> None:
        if config.db_type != self.db_type:
            raise ValueError(f"Expected database type {self.db_type}")
        for field in ("host", "db_name", "username", "password"):
            value = getattr(config, field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field} is required")
        if not isinstance(config.port, int) or isinstance(config.port, bool) or not 1 <= config.port <= 65535:
            raise ValueError("port must be between 1 and 65535")

    def _engine(self, config: DbConnectionConfig, timeout_seconds: int) -> Engine:
        self.validate_config(config)
        if not isinstance(timeout_seconds, int) or isinstance(timeout_seconds, bool) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        url = URL.create(self.driver, username=config.username, password=config.password,
                         host=config.host, port=config.port, database=config.db_name)
        if self.db_type == "mysql":
            arguments: dict[str, object] = {"connect_timeout": min(timeout_seconds, 10),
                                            "read_timeout": timeout_seconds,
                                            "write_timeout": timeout_seconds, "charset": "utf8mb4"}
        else:
            arguments = {"connect_timeout": min(timeout_seconds, 10)}
        return create_engine(url, poolclass=NullPool, connect_args=arguments)

    @contextmanager
    def _connection(self, config: DbConnectionConfig, timeout_seconds: int) -> Iterator[Connection]:
        engine = self._engine(config, timeout_seconds)
        try:
            with engine.connect() as connection:
                yield connection
        finally:
            engine.dispose()

    def test_connection(self, config: DbConnectionConfig) -> bool:
        with self._connection(config, 5) as connection:
            return connection.exec_driver_sql("SELECT 1").scalar_one() == 1

    def is_read_only(self, statement: str) -> bool:
        return check_statement(statement, self.dialect).read_only

    def _set_timeout(self, connection: Connection, timeout_seconds: int, trial_mode: bool) -> None:
        if self.db_type == "postgresql":
            if trial_mode:
                connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            connection.exec_driver_sql(f"SET LOCAL statement_timeout = {timeout_seconds * 1000}")
        else:
            connection.exec_driver_sql(f"SET SESSION MAX_EXECUTION_TIME = {timeout_seconds * 1000}")
            if trial_mode:
                connection.exec_driver_sql("START TRANSACTION READ ONLY")

    def execute(self, config: DbConnectionConfig, statement: str, *, trial_mode: bool = False,
                timeout_seconds: int = 30, max_rows: int = 100) -> QueryResult:
        policy = check_statement(statement, self.dialect, trial_mode=trial_mode)
        if not isinstance(max_rows, int) or isinstance(max_rows, bool) or max_rows <= 0:
            raise ValueError("max_rows must be positive")
        with self._connection(config, timeout_seconds) as connection:
            try:
                self._set_timeout(connection, timeout_seconds, trial_mode)
                target = connection.execution_options(no_parameters=True, stream_results=policy.read_only)
                started = clock.monotonic()
                result = target.exec_driver_sql(statement)
                try:
                    if result.returns_rows:
                        rows = result.fetchmany(max_rows + 1)
                        data = [{key: _json_value(value) for key, value in row._mapping.items()}
                                for row in rows[:max_rows]]
                        response: QueryResult = {"success": True, "rowCount": len(data), "data": data,
                                                 "truncated": len(rows) > max_rows}
                    else:
                        affected = result.rowcount if result.rowcount >= 0 else None
                        detail = (f"{affected} row(s) affected." if affected is not None
                                  else "Affected row count unavailable.")
                        response = {"success": True, "affectedRows": affected,
                                    "message": f"SQL executed successfully. {detail}"}
                finally:
                    result.close()
                if clock.monotonic() - started >= timeout_seconds:
                    raise TimeoutError("SQL execution exceeded its time limit; write outcome may be unknown")
                if trial_mode:
                    connection.rollback()
                else:
                    connection.commit()
                return response
            except Exception as exc:
                try:
                    connection.rollback()
                except SQLAlchemyError as rollback_exc:
                    exc.add_note(f"Rollback also failed: {rollback_exc}")
                raise

    def _qualified_name(self, connection: Connection, table: str) -> str:
        quote = connection.dialect.identifier_preparer.quote_identifier
        return f"{quote(self.metadata_schema)}.{quote(table)}" if self.metadata_schema else quote(table)

    def extract_metadata(self, config: DbConnectionConfig, *, timeout_seconds: int = 30) -> SchemaMetadata:
        metadata: SchemaMetadata = {"dbType": self.db_type, "databaseName": config.db_name,
                                    "host": config.host, "port": config.port, "tables": [],
                                    "incomplete": False, "errorMessage": None}
        errors: list[str] = []
        with self._connection(config, timeout_seconds) as connection:
            self._set_timeout(connection, timeout_seconds, True)
            inspector = inspect(connection)
            for table_name in inspector.get_table_names(schema=self.metadata_schema):
                try:
                    with connection.begin_nested():
                        table, table_error = self._read_table(connection, inspector, table_name)
                    metadata["tables"].append(table)
                    if table_error:
                        errors.append(f"{table_name}: {table_error}")
                except SQLAlchemyError as exc:
                    errors.append(f"{table_name}: {exc}")
            connection.rollback()
        if errors:
            metadata["incomplete"] = True
            metadata["errorMessage"] = "; ".join(errors)
        return metadata

    def generate_document(self, config: DbConnectionConfig, *, timeout_seconds: int = 30) -> str:
        return render_document(self.extract_metadata(config, timeout_seconds=timeout_seconds))

    def _read_table(self, connection: Connection, inspector: Inspector,
                    table_name: str) -> tuple[TableMetadata, str | None]:
        columns_raw = inspector.get_columns(table_name, schema=self.metadata_schema)
        pk_raw = inspector.get_pk_constraint(table_name, schema=self.metadata_schema)
        indexes_raw = inspector.get_indexes(table_name, schema=self.metadata_schema)
        comment_raw = inspector.get_table_comment(table_name, schema=self.metadata_schema)
        pk_columns = pk_raw.get("constrained_columns") or []
        primary_keys = set(pk_columns)
        columns: list[ColumnMetadata] = [
            {"name": column["name"], "type": str(column["type"]),
             "nullable": bool(column["nullable"]), "primaryKey": column["name"] in primary_keys,
             "comment": column.get("comment") or None}
            for column in columns_raw
        ]
        indexes: list[IndexMetadata] = []
        for index in indexes_raw:
            names = index["column_names"]
            expressions = index.get("expressions") or []
            fields = [name if name is not None else str(expressions[position])
                      for position, name in enumerate(names)]
            indexes.append({"name": index.get("name") or "<unnamed>", "columns": fields})
        if primary_keys and not any(set(item["columns"]) == primary_keys for item in indexes):
            indexes.insert(0, {"name": pk_raw.get("name") or "PRIMARY", "columns": pk_columns})
        count_error: str | None = None
        try:
            with connection.begin_nested():
                row_count: int | None = int(connection.exec_driver_sql(
                    f"SELECT COUNT(*) FROM {self._qualified_name(connection, table_name)}"
                ).scalar_one())
        except SQLAlchemyError as exc:
            row_count = None
            count_error = str(exc)
        return {"name": table_name, "comment": comment_raw.get("text") or None,
                "rowCount": row_count, "columns": columns, "indexes": indexes}, count_error
