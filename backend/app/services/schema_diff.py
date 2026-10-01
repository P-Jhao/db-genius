"""Deterministic diffs for database schemas extracted by the adapters."""

import threading

from app.adapters.types import ColumnMetadata, SchemaMetadata, TableMetadata
from app.agent.cancellation import check_cancelled
from app.services import database_tools


def compare_databases(user_id: int, pre_id: int, test_id: int,
                      cancel_event: threading.Event | None = None) -> dict[str, object]:
    """Compare the current ``pre`` schema with the desired ``test`` schema.

    ``database_tools.get_schema`` performs the ownership, connectivity, and
    extraction checks. Its exceptions intentionally propagate so a failed read
    cannot be mistaken for an empty schema.
    """
    check_cancelled(cancel_event)
    pre_schema = database_tools.get_schema(user_id, pre_id)
    check_cancelled(cancel_event)
    test_schema = database_tools.get_schema(user_id, test_id)
    check_cancelled(cancel_event)

    pre_tables = _index_tables(pre_schema)
    test_tables = _index_tables(test_schema)

    new_tables: list[dict[str, object]] = []
    dropped_tables: list[dict[str, object]] = []
    altered_tables: list[dict[str, object]] = []

    for table_name in sorted(pre_tables.keys() | test_tables.keys()):
        pre_table = pre_tables.get(table_name)
        test_table = test_tables.get(table_name)
        if pre_table is None:
            if test_table is None:
                raise ValueError("Table comparison lost both table definitions")
            new_tables.append({"table": table_name, "columnCount": len(test_table["columns"])})
        elif test_table is None:
            dropped_tables.append({"table": table_name, "columnCount": len(pre_table["columns"])})
        else:
            changes = _compare_columns(
                _index_columns(pre_table),
                _index_columns(test_table),
            )
            if changes:
                altered_tables.append({"table": table_name, "changes": changes})

    pre_complete = _is_complete(pre_schema)
    test_complete = _is_complete(test_schema)
    complete = pre_complete and test_complete
    pre_inferred, pre_sample = _inference(pre_schema)
    test_inferred, test_sample = _inference(test_schema)
    report: dict[str, object] = {
        "success": complete,
        "complete": complete,
        "preComplete": pre_complete,
        "testComplete": test_complete,
        "preDatabase": pre_schema["databaseName"],
        "testDatabase": test_schema["databaseName"],
        "preDbType": pre_schema["dbType"],
        "testDbType": test_schema["dbType"],
        "preSchemaInferred": pre_inferred,
        "testSchemaInferred": test_inferred,
        "summary": {
            "newTables": len(new_tables),
            "droppedTables": len(dropped_tables),
            "alteredTables": len(altered_tables),
        },
        "newTables": new_tables,
        "droppedTables": dropped_tables,
        "alteredTables": altered_tables,
        "preSchema": pre_schema,
        "testSchema": test_schema,
    }
    if pre_sample is not None:
        report["preSampleSize"] = pre_sample
    if test_sample is not None:
        report["testSampleSize"] = test_sample

    pre_error = _schema_error(pre_schema)
    test_error = _schema_error(test_schema)
    if pre_error is not None:
        report["preError"] = pre_error
    if test_error is not None:
        report["testError"] = test_error
    return report


def _inference(schema: SchemaMetadata) -> tuple[bool, int | None]:
    inferred = schema.get("schemaInferred", False)
    if not isinstance(inferred, bool):
        raise TypeError("schemaInferred must be a boolean")
    sample_size = schema.get("sampleSize")
    if "sampleSize" in schema and (not isinstance(sample_size, int) or
                                   isinstance(sample_size, bool) or sample_size < 0):
        raise TypeError("sampleSize must be a non-negative integer")
    return inferred, sample_size if isinstance(sample_size, int) else None


def _is_complete(schema: SchemaMetadata) -> bool:
    return not schema["incomplete"] and schema["errorMessage"] is None


def _schema_error(schema: SchemaMetadata) -> str | None:
    message = schema["errorMessage"]
    if not schema["incomplete"] and message is None:
        return None
    if message is not None and message.strip():
        return message
    return "Schema metadata is incomplete."


def _index_tables(schema: SchemaMetadata) -> dict[str, TableMetadata]:
    tables: dict[str, TableMetadata] = {}
    for table in schema["tables"]:
        name = table["name"]
        if name in tables:
            raise ValueError(f"Duplicate table name in schema metadata: {name}")
        tables[name] = table
    return tables


def _index_columns(table: TableMetadata) -> dict[str, ColumnMetadata]:
    columns: dict[str, ColumnMetadata] = {}
    for column in table["columns"]:
        name = column["name"]
        if name in columns:
            raise ValueError(f"Duplicate column name in schema metadata: {table['name']}.{name}")
        columns[name] = column
    return columns


def _compare_columns(
    pre_columns: dict[str, ColumnMetadata],
    test_columns: dict[str, ColumnMetadata],
) -> list[dict[str, object]]:
    changes: list[dict[str, object]] = []
    for name in sorted(pre_columns.keys() | test_columns.keys()):
        pre = pre_columns.get(name)
        test = test_columns.get(name)
        if pre is None:
            if test is None:
                raise ValueError("Column comparison lost both column definitions")
            changes.append({"change": "ADD_COLUMN", "column": name, "type": test["type"]})
        elif test is None:
            changes.append({"change": "DROP_COLUMN", "column": name, "type": pre["type"]})
        else:
            if pre["type"] != test["type"]:
                changes.append({
                    "change": "MODIFY_COLUMN",
                    "column": name,
                    "preType": pre["type"],
                    "testType": test["type"],
                })
            if pre["nullable"] != test["nullable"]:
                changes.append({
                    "change": "MODIFY_NULLABLE",
                    "column": name,
                    "preNullable": pre["nullable"],
                    "testNullable": test["nullable"],
                })
    return changes
