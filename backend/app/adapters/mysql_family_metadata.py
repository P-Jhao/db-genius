"""Portable information_schema extraction for Doris and StarRocks FE endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from app.adapters.types import (
    ColumnMetadata,
    DbConnectionConfig,
    IndexMetadata,
    SchemaMetadata,
    TableMetadata,
)

if TYPE_CHECKING:
    from app.adapters.mysql_family import OlapMysqlAdapter


_TABLES = text("""SELECT TABLE_NAME, TABLE_COMMENT FROM information_schema.TABLES
                  WHERE TABLE_SCHEMA = :database AND TABLE_TYPE = 'BASE TABLE'
                  ORDER BY TABLE_NAME""")
_COLUMNS = text("""SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_COMMENT, COLUMN_KEY
                   FROM information_schema.COLUMNS
                   WHERE TABLE_SCHEMA = :database AND TABLE_NAME = :table
                   ORDER BY ORDINAL_POSITION""")
_INDEXES = text("""SELECT INDEX_NAME, COLUMN_NAME, SEQ_IN_INDEX
                   FROM information_schema.STATISTICS
                   WHERE TABLE_SCHEMA = :database AND TABLE_NAME = :table
                   ORDER BY INDEX_NAME, SEQ_IN_INDEX""")


def _read_table(
    connection: Connection, database: str, name: str, comment: str | None, *, indexes_supported: bool
) -> tuple[TableMetadata, list[str]]:
    parameters = {"database": database, "table": name}
    columns: list[ColumnMetadata] = [
        {
            "name": row.COLUMN_NAME,
            "type": row.COLUMN_TYPE,
            "nullable": row.IS_NULLABLE.upper() == "YES",
            "primaryKey": row.COLUMN_KEY == "PRI",
            "comment": row.COLUMN_COMMENT or None,
        }
        for row in connection.execute(_COLUMNS, parameters)
    ]
    if not columns:
        raise SQLAlchemyError("column metadata unavailable")
    errors: list[str] = []
    indexes: list[IndexMetadata] = []
    if not indexes_supported:
        errors.append("indexes: information_schema.STATISTICS is not implemented by this engine")
    else:
        try:
            by_name: dict[str, list[str]] = {}
            for row in connection.execute(_INDEXES, parameters):
                if row.INDEX_NAME is None or row.COLUMN_NAME is None:
                    errors.append("indexes: index name or column metadata unavailable")
                    continue
                by_name.setdefault(row.INDEX_NAME, []).append(row.COLUMN_NAME)
            indexes = [{"name": key, "columns": values} for key, values in by_name.items()]
        except SQLAlchemyError as exc:
            errors.append(f"indexes: {exc}")
    quote = connection.dialect.identifier_preparer.quote_identifier
    try:
        row_count = int(connection.exec_driver_sql(f"SELECT COUNT(*) FROM {quote(name)}").scalar_one())
    except SQLAlchemyError as exc:
        row_count = None
        errors.append(f"row count: {exc}")
    return {
        "name": name,
        "comment": comment or None,
        "rowCount": row_count,
        "columns": columns,
        "indexes": indexes,
    }, errors


def extract_olap_metadata(
    adapter: OlapMysqlAdapter, config: DbConnectionConfig, timeout_seconds: int
) -> SchemaMetadata:
    metadata: SchemaMetadata = {
        "dbType": adapter.db_type,
        "databaseName": config.db_name,
        "host": config.host,
        "port": config.port,
        "tables": [],
        "incomplete": False,
        "errorMessage": None,
    }
    errors: list[str] = []
    with adapter._connection(config, timeout_seconds) as connection:
        adapter._set_timeout(connection, timeout_seconds, True)
        try:
            tables = list(connection.execute(_TABLES, {"database": config.db_name}))
        except SQLAlchemyError as exc:
            metadata["incomplete"] = True
            metadata["errorMessage"] = f"table listing: {exc}"
            connection.rollback()
            return metadata
        for row in tables:
            try:
                table, table_errors = _read_table(
                    connection, config.db_name, row.TABLE_NAME, row.TABLE_COMMENT,
                    indexes_supported=adapter.index_metadata_supported,
                )
                metadata["tables"].append(table)
                errors.extend(f"{row.TABLE_NAME}: {error}" for error in table_errors)
            except SQLAlchemyError as exc:
                errors.append(f"{row.TABLE_NAME}: {exc}")
        connection.rollback()
    if errors:
        metadata["incomplete"] = True
        metadata["errorMessage"] = "; ".join(errors)
    return metadata
