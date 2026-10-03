"""Allowlisted metadata actually present in a provider request; no supplemental reads."""
from __future__ import annotations

import hashlib
import json
import re
from typing import cast

from real_model_synthetic_evidence import scrub

HEADER = re.compile(r"Database (-?(?:0|[1-9]\d*)) schema:\n")
MARKER = "[TRUNCATED:TOOL_OUTPUT_TOO_LONG]"
UNCAPTURED = ["connection", "comments", "errorText", "defaults", "identity", "foreignKeys", "dependencies"]


class CaptureError(ValueError):
    """Only the fixed diagnostic category is retained, never exception text."""


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise CaptureError("invalid_object")
    return cast(dict[str, object], value)


def _array(value: object) -> list[object]:
    if not isinstance(value, list):
        raise CaptureError("invalid_array")
    return cast(list[object], value)


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise CaptureError("duplicate_json_key")
        result[key] = value
    return result


def _constant(_value: str) -> object:
    raise CaptureError("invalid_json_number")


DECODER = json.JSONDecoder(object_pairs_hook=_pairs, parse_constant=_constant)


def _diagnostic(error: ValueError | TypeError | RecursionError) -> str:
    if isinstance(error, CaptureError):
        return str(error)
    return "schema_nesting_limit" if isinstance(error, RecursionError) else "malformed_schema_json"


def _fields(source: dict[str, object], target: dict[str, object],
            fields: dict[str, tuple[type[object], ...]], missing: list[str], path: str) -> None:
    for key, expected in fields.items():
        if key not in source:
            missing.append(f"{path}/{key}")
            continue
        value = source[key]
        if type(value) not in expected:
            raise CaptureError("invalid_schema_field")
        if isinstance(value, str):
            if not value:
                raise CaptureError("empty_schema_field")
            value.encode("utf-8")
        if isinstance(value, int) and not isinstance(value, bool) and value < 0:
            raise CaptureError("invalid_schema_count")
        target[key] = value


def _projection(schema: dict[str, object], bounded: bool) -> tuple[dict[str, object], list[str]]:
    result: dict[str, object] = {}
    missing: list[str] = []
    _fields(schema, result, {"dbType": (str,), "incomplete": (bool,)}, missing, "")
    if "tables" not in schema:
        if not bounded:
            raise CaptureError("missing_schema_tables")
        missing.append("/tables")
        return result, missing
    tables: list[dict[str, object]] = []
    for i, raw in enumerate(_array(schema["tables"])):
        table = _object(raw)
        projected: dict[str, object] = {}
        path = f"/tables/{i}"
        _fields(table, projected, {"name": (str,), "rowCount": (int, type(None))}, missing, path)
        for key in ("columns", "indexes"):
            if key not in table:
                missing.append(f"{path}/{key}")
                continue
            items: list[dict[str, object]] = []
            for j, raw_item in enumerate(_array(table[key])):
                item = _object(raw_item)
                output: dict[str, object] = {}
                item_path = f"{path}/{key}/{j}"
                fields: dict[str, tuple[type[object], ...]] = {
                    "name": (str,), "type": (str,), "nullable": (bool,), "primaryKey": (bool,),
                }
                _fields(item, output, fields if key == "columns" else {"name": (str,)}, missing, item_path)
                if key == "indexes":
                    if "columns" not in item:
                        missing.append(f"{item_path}/columns")
                    else:
                        columns = _array(item["columns"])
                        if not all(isinstance(column, str) and column for column in columns):
                            raise CaptureError("invalid_index_columns")
                        for column in columns:
                            cast(str, column).encode("utf-8")
                        output["columns"] = list(columns)
                items.append(output)
            projected[key] = items
        tables.append(projected)
    result["tables"] = tables
    if "dbType" not in schema and not bounded:
        raise CaptureError("missing_schema_type")
    for key, expected in [("schemaInferred", bool), ("sampleSize", int)]:
        if key in schema:
            _fields(schema, result, {key: (expected,)}, missing, "")
            if key == "sampleSize" and schema[key] == 0:
                raise CaptureError("invalid_schema_count")
    return result, missing


def _source(text: object, source_type: str, index: int, db_id: int,
            call_id: str | None = None) -> dict[str, object]:
    result: dict[str, object] = {"sourceType": source_type, "messageIndex": index, "dbId": db_id,
                                "status": "malformed", "inputBounded": None, "metadataIncomplete": None}
    if call_id is not None:
        result["toolCallId"] = call_id
    try:
        if not isinstance(text, str):
            raise CaptureError("schema_content_not_text")
        result.update({"jsonCharacters": len(text), "jsonUtf8Sha256": hashlib.sha256(
            text.encode("utf-8", errors="surrogatepass")).hexdigest()})
        value = _object(DECODER.decode(text))
        bounded = value.get("marker") == MARKER
        result["inputBounded"] = bounded
        if bounded and value.get("truncated") is not True:
            raise CaptureError("invalid_bound_marker")
        schema = _object(value.get("preview")) if bounded else value
        projection, missing = _projection(schema, bounded)
        incomplete = schema.get("incomplete")
        if bounded and "sourceIncomplete" in value:
            if type(value["sourceIncomplete"]) is not bool:
                raise CaptureError("invalid_schema_field")
            if incomplete is not None and incomplete != value["sourceIncomplete"]:
                raise CaptureError("conflicting_incomplete_flags")
            incomplete = value["sourceIncomplete"]
        error_present: bool | None = None
        if "errorMessage" in schema:
            error = schema["errorMessage"]
            if error is not None and not isinstance(error, str):
                raise CaptureError("invalid_schema_error_flag")
            error_present = error is not None
        else:
            missing.append("/errorMessage")
        complete = not bounded and not missing and incomplete is False and error_present is False
        result.update({"status": "complete" if complete else "partial", "projection": projection,
                       "metadataIncomplete": incomplete, "metadataErrorPresent": error_present,
                       "missingFields": missing, "notCapturedProperties": list(UNCAPTURED)})
    except (ValueError, TypeError, RecursionError) as error:
        result["diagnostic"] = _diagnostic(error)
    return result


def _system(content: str, index: int) -> list[dict[str, object]]:
    sources: list[dict[str, object]] = []
    offset = 0
    while offset < len(content):
        header = HEADER.match(content, offset)
        if header is None:
            raise CaptureError("schema_block_trailing_content")
        start = header.end()
        try:
            _value, end = DECODER.raw_decode(content, start)
        except (ValueError, TypeError, RecursionError):
            sources.append(_source(content[start:], "system_schema_block", index, int(header[1])))
            return sources
        sources.append(_source(content[start:end], "system_schema_block", index, int(header[1])))
        if end == len(content):
            break
        if not content.startswith("\n\n", end):
            raise CaptureError("schema_block_trailing_content")
        offset = end + 2
        if offset == len(content):
            raise CaptureError("schema_block_trailing_content")
    return sources


def _capture(request: dict[str, object]) -> dict[str, object]:
    sources: list[dict[str, object]] = []
    links: dict[str, int] = {}
    for i, raw in enumerate(_array(request.get("messages"))):
        message = _object(raw)
        role, content = message.get("role"), message.get("content")
        if role == "system" and isinstance(content, str) and HEADER.match(content):
            sources.extend(_system(content, i))
        elif role == "assistant":
            for raw_call in _array(message.get("tool_calls", [])):
                call = _object(raw_call)
                function = _object(call.get("function"))
                if function.get("name") != "getDatabaseSchema":
                    continue
                call_id, encoded = call.get("id"), function.get("arguments")
                if not isinstance(call_id, str) or not call_id or not isinstance(encoded, str):
                    raise CaptureError("invalid_schema_tool_link")
                call_id.encode("utf-8")
                args = _object(DECODER.decode(encoded))
                db_id = args.get("db_id")
                if type(db_id) is not int or call_id in links:
                    raise CaptureError("invalid_schema_tool_link")
                links[call_id] = db_id
        elif role == "tool":
            call_id = message.get("tool_call_id")
            if isinstance(call_id, str) and call_id in links:
                sources.append(_source(content, "getDatabaseSchema_tool_result", i, links[call_id], call_id))
    status = "absent" if not sources else "malformed" if any(s["status"] == "malformed" for s in sources) else "observed"
    return {"status": status, "sources": sources, "absenceMeaning": "no recognized schema source; other metadata forms are not parsed"}


def metadata_inputs(request: dict[str, object], secrets: tuple[str, ...]) -> dict[str, object]:
    """Read the real outgoing payload without modifying it; capture errors never stop forwarding."""
    try:
        result = _capture(request)
    except (ValueError, TypeError, RecursionError) as error:
        result = {"status": "malformed", "sources": [],
                  "diagnostic": _diagnostic(error)}
    return _object(scrub(result, secrets))
