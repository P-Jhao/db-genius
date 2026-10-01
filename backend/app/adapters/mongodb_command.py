"""Strict JSON command boundary for the original MongoDB read operations."""

from __future__ import annotations

import json
from dataclasses import dataclass


class UnsafeMongoCommand(ValueError):
    pass


@dataclass(frozen=True)
class MongoCommand:
    collection: str
    operation: str
    filter: dict[str, object]
    field: str | None
    pipeline: list[dict[str, object]]
    limit: int


_OPERATIONS = {"find", "count", "distinct", "aggregate"}
_ROOT_FIELDS = {"collection", "operation", "filter", "field", "pipeline", "limit"}
_STAGES = {"$match", "$project", "$group", "$sort", "$limit", "$skip", "$unwind",
           "$addFields", "$set", "$unset", "$count", "$replaceRoot", "$replaceWith",
           "$lookup", "$graphLookup", "$facet", "$unionWith", "$bucket", "$bucketAuto",
           "$sortByCount", "$redact", "$sample", "$geoNear", "$densify", "$fill",
           "$setWindowFields", "$documents"}
_FORBIDDEN_KEYS = {"$out", "$merge", "$where", "$function", "$accumulator",
                   "$eval", "$mapReduce", "$currentOp"}


def _pairs_unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise UnsafeMongoCommand(f"Duplicate MongoDB command key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise UnsafeMongoCommand(f"Non-JSON value in MongoDB command: {value}")


def _check_nested(value: object) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if not isinstance(key, str):
                raise UnsafeMongoCommand("MongoDB command keys must be strings")
            if key in _FORBIDDEN_KEYS or key.lower() in {item.lower() for item in _FORBIDDEN_KEYS}:
                raise UnsafeMongoCommand(f"Forbidden MongoDB operator: {key}")
            _check_nested(nested)
    elif isinstance(value, list):
        for nested in value:
            _check_nested(nested)


def parse_command(statement: str) -> MongoCommand:
    if not isinstance(statement, str) or not statement.strip():
        raise UnsafeMongoCommand("MongoDB command is empty")
    try:
        raw: object = json.loads(statement, object_pairs_hook=_pairs_unique,
                                 parse_constant=_reject_constant)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise UnsafeMongoCommand("Invalid MongoDB command JSON") from exc
    if not isinstance(raw, dict):
        raise UnsafeMongoCommand("MongoDB command must be a JSON object")
    if set(raw) - _ROOT_FIELDS:
        raise UnsafeMongoCommand("Unsupported MongoDB command field")
    collection = raw.get("collection")
    operation = raw.get("operation")
    if not isinstance(collection, str) or not collection.strip() or "\x00" in collection:
        raise UnsafeMongoCommand("MongoDB collection is required")
    if not isinstance(operation, str) or operation.lower() not in _OPERATIONS:
        raise UnsafeMongoCommand("Unsupported MongoDB operation")
    operation = operation.lower()
    filters = raw.get("filter", {})
    if not isinstance(filters, dict):
        raise UnsafeMongoCommand("MongoDB filter must be an object")
    field = raw.get("field")
    if operation == "distinct":
        if not isinstance(field, str) or not field.strip() or "\x00" in field:
            raise UnsafeMongoCommand("MongoDB distinct field is required")
    elif field is not None:
        raise UnsafeMongoCommand("MongoDB field is valid only for distinct")
    pipeline = raw.get("pipeline", [])
    if operation == "aggregate":
        if not isinstance(pipeline, list):
            raise UnsafeMongoCommand("MongoDB pipeline must be an array")
        for stage in pipeline:
            if not isinstance(stage, dict) or len(stage) != 1 or next(iter(stage)) not in _STAGES:
                raise UnsafeMongoCommand("Unsupported MongoDB aggregation stage")
    elif "pipeline" in raw:
        raise UnsafeMongoCommand("MongoDB pipeline is valid only for aggregate")
    if operation == "aggregate" and "filter" in raw:
        raise UnsafeMongoCommand("MongoDB aggregate uses $match instead of filter")
    if operation not in {"find", "aggregate"} and "limit" in raw:
        raise UnsafeMongoCommand("MongoDB limit is valid only for find or aggregate")
    limit = raw.get("limit", 100)
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise UnsafeMongoCommand("MongoDB limit must be a positive integer")
    _check_nested(raw)
    return MongoCommand(collection, operation, filters, field if isinstance(field, str) else None,
                        pipeline, min(limit, 100))
