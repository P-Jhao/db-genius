"""Restore Oracle catalog identifier spelling before PK/index comparisons."""

from __future__ import annotations

from sqlalchemy.engine import Connection
from sqlalchemy.engine.reflection import Inspector
from sqlalchemy.exc import SQLAlchemyError

from app.adapters.types import ColumnMetadata, IndexMetadata, TableMetadata


def raw_name(connection: Connection, normalized: str) -> str:
    value: object = connection.dialect.denormalize_name(normalized)
    if not isinstance(value, str):
        raise TypeError("Oracle metadata identifier is not text")
    return str(value)


def read_table(connection: Connection, inspector: Inspector, table_name: str,
               schema: str, qualified: str) -> tuple[TableMetadata, str | None]:
    columns_raw = inspector.get_columns(table_name, schema=schema)
    pk_raw = inspector.get_pk_constraint(table_name, schema=schema)
    indexes_raw = inspector.get_indexes(table_name, schema=schema)
    comment_raw = inspector.get_table_comment(table_name, schema=schema)
    constrained = pk_raw.get("constrained_columns")
    pk_columns = [] if constrained is None else [raw_name(connection, name) for name in constrained]
    primary_keys = set(pk_columns)
    columns: list[ColumnMetadata] = [
        {"name": raw_name(connection, column["name"]), "type": column["type"].compile(dialect=connection.dialect),
         "nullable": bool(column["nullable"]),
         "primaryKey": raw_name(connection, column["name"]) in primary_keys,
         "comment": column.get("comment")}
        for column in columns_raw
    ]
    indexes: list[IndexMetadata] = []
    for index in indexes_raw:
        expressions = index.get("expressions")
        fields: list[str] = []
        for position, name in enumerate(index["column_names"]):
            if name is None:
                if expressions is None or position >= len(expressions):
                    raise ValueError("Oracle index expression is unavailable")
                fields.append(str(expressions[position]))
            else:
                fields.append(raw_name(connection, name))
        index_name = index.get("name")
        indexes.append({"name": "<unnamed>" if index_name is None else raw_name(connection, index_name),
                        "columns": fields})
    if primary_keys and not any(set(index["columns"]) == primary_keys for index in indexes):
        name = pk_raw.get("name")
        indexes.insert(0, {"name": "PRIMARY" if name is None else raw_name(connection, name), "columns": pk_columns})
    error: str | None = None
    try:
        with connection.begin_nested():
            count: int | None = int(connection.exec_driver_sql(f"SELECT COUNT(*) FROM {qualified}").scalar_one())
    except SQLAlchemyError as exc:
        count, error = None, str(exc)
    return {"name": raw_name(connection, table_name), "comment": comment_raw.get("text"),
            "rowCount": count, "columns": columns, "indexes": indexes}, error
