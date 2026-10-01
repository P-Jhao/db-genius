"""Independently read sampled fields, reliable indexes and estimated counts."""

from collections.abc import Callable

from pymongo.collection import Collection
from pymongo.errors import PyMongoError

from app.adapters.types import ColumnMetadata, IndexMetadata, TableMetadata


def _index(value: object) -> IndexMetadata:
    if not isinstance(value, dict):
        raise TypeError("index metadata must be an object")
    name = value.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("index name must be nonempty text")
    keys = value.get("key")
    if not isinstance(keys, dict) or not keys:
        raise ValueError(f"index {name} key must be a nonempty object")
    if any(not isinstance(column, str) or not column.strip() for column in keys):
        raise ValueError(f"index {name} column names must be nonempty text")
    return {"name": name, "columns": list(keys)}


def read_collection(name: str, collection: Collection[dict[str, object]], max_time_ms: int,
                    classify: Callable[[object], str]) -> tuple[TableMetadata, list[str]]:
    table: TableMetadata = {
        "name": name, "comment": "Schema inferred from at most 50 sample documents per collection; "
        "first-seen BSON types and approximate row counts; fields may be missing.",
        "rowCount": None, "columns": [], "indexes": [],
    }
    errors: list[str] = []
    fields: dict[str, str] = {}
    try:
        for document in collection.find({}).limit(50).max_time_ms(max_time_ms):
            if not isinstance(document, dict):
                raise TypeError("sample document must be an object")
            for key, value in document.items():
                if not isinstance(key, str) or not key.strip():
                    raise ValueError("sample field name must be nonempty text")
                fields.setdefault(key, classify(value))
    except (PyMongoError, TypeError, ValueError) as error:
        errors.append(f"{name} fields: {type(error).__name__}: {error}")
    columns: list[ColumnMetadata] = [
        {"name": key, "type": value, "nullable": True, "primaryKey": key == "_id", "comment": None}
        for key, value in fields.items()
    ]
    table["columns"] = columns
    try:
        for position, value in enumerate(collection.list_indexes(), start=1):
            try:
                table["indexes"].append(_index(value))
            except (TypeError, ValueError) as error:
                errors.append(f"{name} indexes entry {position}: {type(error).__name__}: {error}")
    except (PyMongoError, TypeError, ValueError) as error:
        errors.append(f"{name} indexes: {type(error).__name__}: {error}")
    try:
        count = collection.estimated_document_count(maxTimeMS=max_time_ms)
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise ValueError("estimated row count must be a nonnegative integer")
        table["rowCount"] = count
    except (PyMongoError, TypeError, ValueError) as error:
        errors.append(f"{name} rowCount: {type(error).__name__}: {error}")
    return table, errors
