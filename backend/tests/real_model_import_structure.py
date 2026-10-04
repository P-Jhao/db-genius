"""Fresh, fail-closed reflection evidence for the owned imported_contacts table."""

from __future__ import annotations

import hashlib
import json
import math
import warnings
from collections.abc import Callable, Mapping
from typing import Protocol, cast

TABLE = "imported_contacts"
REQUIRED = {
    "columns": ("name", "type", "nullable", "default"),
    "primaryKey": ("name", "constrained_columns"),
    "uniqueConstraints": ("name", "column_names"),
    "foreignKeys": ("name", "constrained_columns", "referred_schema", "referred_table", "referred_columns"),
    "indexes": ("name", "column_names", "unique"),
    "checkConstraints": ("name", "sqltext"),
}
METHODS = {
    "columns": "get_columns", "primaryKey": "get_pk_constraint",
    "uniqueConstraints": "get_unique_constraints", "foreignKeys": "get_foreign_keys",
    "indexes": "get_indexes", "checkConstraints": "get_check_constraints",
}
OPTIONAL = {
    "columns": ("autoincrement", "comment", "computed", "identity", "dialect_options"),
    "primaryKey": ("comment", "dialect_options"),
    "uniqueConstraints": ("comment", "duplicates_index", "dialect_options"),
    "foreignKeys": ("comment", "options"),
    "indexes": ("expressions", "duplicates_constraint", "include_columns", "column_sorting", "dialect_options"),
    "checkConstraints": ("comment", "dialect_options"),
}
NOT_CAPTURED = ("triggers", "grants", "tableOptions", "tableComment", "partitioning",
                "sequenceState", "catalogObjectIdentity", "transientDdl", "unreflectedDialectAttributes")


class UnsupportedMetadata(TypeError):
    """A returned value cannot be safely represented as known metadata."""


class StructureTarget(Protocol):
    @property
    def db_type(self) -> str: ...
    @property
    def name(self) -> str: ...
    @property
    def engine(self) -> object: ...


class ReflectionReader(Protocol):
    @property
    def default_schema_name(self) -> str: ...
    def get_table_names(self, *, schema: str) -> list[str]: ...


def canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _json_value(value: object) -> object:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("Reflected metadata keys must be strings")
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    raise UnsupportedMetadata("Unsupported reflected metadata value")


def _names(value: object, *, expressions: bool = False) -> None:
    if not isinstance(value, list) or not all(
            isinstance(name, str) and bool(name) or expressions and name is None for name in value):
        raise TypeError("Invalid reflected ordered column names")


def _record(raw: object, dimension: str) -> dict[str, object]:
    if not isinstance(raw, Mapping) or any(key not in raw for key in REQUIRED[dimension]):
        raise KeyError("Required reflected attribute is absent")
    row: dict[str, object] = dict(raw)
    if dimension == "columns":
        if not isinstance(row["name"], str) or not row["name"] or not isinstance(row["nullable"], bool):
            raise TypeError("Invalid column identity or nullability")
        if row["default"] is not None and not isinstance(row["default"], str):
            raise TypeError("Invalid reflected default")
        kind = row["type"]
        if kind is None or not str(kind):
            raise TypeError("Reflected type is absent")
        attributes = {} if isinstance(kind, str) else {
            key: item for key, item in vars(kind).items() if not key.startswith("_")}
        row["type"] = {"class": f"{type(kind).__module__}.{type(kind).__qualname__}",
                       "sql": str(kind), "publicAttributes": _json_value(attributes)}
    elif row["name"] is not None and not isinstance(row["name"], str):
        raise TypeError("Invalid reflected constraint name")
    for key in ("column_names", "constrained_columns", "referred_columns"):
        if key in row:
            _names(row[key], expressions=dimension == "indexes")
    if dimension == "foreignKeys":
        if not isinstance(row["referred_table"], str) or not row["referred_table"]:
            raise TypeError("Invalid foreign-key target")
        if row["referred_schema"] is not None and not isinstance(row["referred_schema"], str):
            raise TypeError("Invalid foreign-key schema")
        if len(cast(list[object], row["constrained_columns"])) != len(cast(list[object], row["referred_columns"])):
            raise ValueError("Foreign-key column counts differ")
    if dimension == "indexes":
        if not isinstance(row["unique"], bool):
            raise TypeError("Invalid index uniqueness")
        if None in cast(list[object], row["column_names"]) and "expressions" not in row:
            raise KeyError("Expression index lacks reflected expressions")
    if dimension == "checkConstraints" and (not isinstance(row["sqltext"], str) or not row["sqltext"]):
        raise TypeError("Invalid check expression")
    return cast(dict[str, object], _json_value(row))


def _dimension(reader: ReflectionReader, schema: str, dimension: str) -> dict[str, object]:
    try:
        method = cast(Callable[..., object], getattr(reader, METHODS[dimension]))
        with warnings.catch_warnings(record=True) as raised:
            warnings.simplefilter("always")
            raw = method(TABLE, schema=schema)
        if raised:
            return {"status": "unknown", "warningTypes": [type(item.message).__name__ for item in raised]}
        raw_records = [raw] if dimension == "primaryKey" else raw
        if isinstance(raw_records, list):
            missing = [{"record": index, "attributes": [key for key in REQUIRED[dimension] if key not in item]}
                       for index, item in enumerate(raw_records) if isinstance(item, Mapping)
                       and any(key not in item for key in REQUIRED[dimension])]
            if missing:
                return {"status": "unknown", "missingRequiredAttributes": missing}
        if dimension == "primaryKey":
            records = [_record(raw, dimension)]
            value: object = records[0]
        else:
            if not isinstance(raw, list) or dimension == "columns" and not raw:
                raise TypeError("Expected reflected records")
            records = [_record(item, dimension) for item in raw]
            if dimension == "columns":
                if len({row["name"] for row in records}) != len(records):
                    raise ValueError("Duplicate reflected columns")
                value = records  # Physical column order is material.
            else:
                value = sorted(records, key=canonical)  # Preserve column order inside each constraint.
        absent = [{"record": index, "attributes": [key for key in OPTIONAL[dimension] if key not in row]}
                  for index, row in enumerate(records) if any(key not in row for key in OPTIONAL[dimension])]
        return {"status": "supported", "value": value, "optionalAttributesNotReturned": absent}
    except (AttributeError, NotImplementedError, UnsupportedMetadata) as error:
        return {"status": "unknown", "errorType": type(error).__name__}
    except Exception as error:  # noqa: BLE001 - retain only safe error type, never diagnostic text
        return {"status": "failed", "errorType": type(error).__name__}


def capture_structure(target: StructureTarget, *,
                      inspector_factory: Callable[[object], ReflectionReader] | None = None) -> dict[str, object]:
    snapshot: dict[str, object] = {"databaseType": target.db_type, "database": target.name, "table": TABLE,
                                  "scope": "sqlalchemy-returned-reflection-only", "notCaptured": list(NOT_CAPTURED),
                                  "status": "unverified", "fingerprint": None}
    try:
        if target.db_type not in {"postgresql", "mysql"}:
            raise ValueError("Unexpected imported-contacts database family")
        if inspector_factory is None:
            from sqlalchemy import inspect

            reader = cast(ReflectionReader, inspect(target.engine))
        else:
            reader = inspector_factory(target.engine)
        schema = reader.default_schema_name
        if not isinstance(schema, str) or not schema or target.db_type == "mysql" and schema != target.name:
            raise ValueError("Unexpected owned target schema")
        snapshot["schema"] = schema
        with warnings.catch_warnings(record=True) as raised:
            warnings.simplefilter("always")
            tables = reader.get_table_names(schema=schema)
        if raised or not isinstance(tables, list) or tables.count(TABLE) != 1:
            raise ValueError("Owned imported-contacts table not uniquely reflected")
        dimensions = {name: _dimension(reader, schema, name) for name in METHODS}
        snapshot["dimensions"] = dimensions
        if all(value["status"] == "supported" for value in dimensions.values()):
            content = {"databaseType": target.db_type, "database": target.name, "schema": schema, "table": TABLE,
                       "metadata": {name: value["value"] for name, value in dimensions.items()}}
            snapshot.update({"status": "observed", "fingerprint": hashlib.sha256(canonical(content).encode()).hexdigest()})
    except Exception as error:  # noqa: BLE001 - before/after failure is evidence, not permission to pass
        snapshot["errorType"] = type(error).__name__
    return snapshot


def structure_evidence(before: dict[str, object], after: dict[str, object]) -> dict[str, object]:
    identity = ("databaseType", "database", "schema", "table", "scope")
    verified = (before.get("status") == after.get("status") == "observed"
                and isinstance(before.get("fingerprint"), str) and isinstance(after.get("fingerprint"), str))
    same_target = all(key in before and key in after and before[key] == after[key] for key in identity)
    changed: list[str] = []
    dimensions: dict[str, object] = {}
    left, right = before.get("dimensions"), after.get("dimensions")
    if isinstance(left, dict) and isinstance(right, dict):
        for name in METHODS:
            prior, current = left.get(name), right.get(name)
            supported = (isinstance(prior, dict) and isinstance(current, dict)
                         and prior.get("status") == current.get("status") == "supported")
            equal = prior.get("value") == current.get("value") if supported else None
            dimensions[name] = {"status": "unknown" if not supported else "passed" if equal else "failed",
                                "unchanged": equal}
            if supported and not equal:
                changed.append(name)
    unchanged = (verified and same_target and before["fingerprint"] == after["fingerprint"]
                 and len(dimensions) == len(METHODS)
                 and all(isinstance(value, dict) and value["status"] == "passed" for value in dimensions.values()))
    return {"before": before, "after": after, "dimensions": dimensions, "changedDimensions": changed,
            "checks": {"importStructureObserved": verified, "importStructureSameTarget": same_target,
                       "importStructureUnchangedWithinReflection": unchanged},
            "status": "passed" if unchanged else "failed"}
