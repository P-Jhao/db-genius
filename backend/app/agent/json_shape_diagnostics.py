"""Private observations only; never validate, repair, retry or expose wire."""
import json
from collections import Counter
from dataclasses import dataclass
from typing import Literal

from app.agent.cancellation import RunAborted

Contract = Literal["classification", "final_report"]
JsonKind = Literal["object", "array", "string", "number", "boolean", "null"]
MAX_DIAGNOSTIC_CHARACTERS = 65_536
MAX_DIAGNOSTIC_DEPTH = 64
JSON_KINDS = frozenset({"object", "array", "string", "number", "boolean", "null"})
SYNTAX_KINDS = frozenset({"valid_json", "invalid_json", "unobserved_size_bound", "unobserved_depth_bound",
                        "unobserved_diagnostic_failure"})
DIAGNOSTIC_ERRORS = frozenset({"ValueError", "TypeError", "RecursionError", "MemoryError", "other"})


@dataclass(frozen=True)
class _ObjectPairs:
    pairs: tuple[tuple[str, object], ...]


def _kind(value: object) -> JsonKind:
    if isinstance(value, _ObjectPairs):
        return "object"
    if isinstance(value, list):
        return "array"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (float, int)):
        return "number"
    if isinstance(value, str):
        return "string"
    raise TypeError("Unexpected internal JSON observation value")


def _reject_constant(value: str) -> object:
    raise ValueError("Nonstandard JSON constant")


def _exceeds_depth(wire: str) -> bool:
    depth = 0
    quoted = escaped = False
    for character in wire:
        if quoted:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                quoted = False
        elif character == '"':
            quoted = True
        elif character in "[{":
            depth += 1
            if depth > MAX_DIAGNOSTIC_DEPTH:
                return True
        elif character in "]}":
            depth -= 1
    return False


def observe_json_shape(wire: str, contract: Contract) -> dict[str, object]:
    """Only fixed keys, types, counts and structural presence/order predicates leave this function."""
    if contract not in {"classification", "final_report"}:
        raise ValueError("Unknown JSON diagnostic contract")
    if len(wire) > MAX_DIAGNOSTIC_CHARACTERS:
        return {"contract": contract, "syntax": "unobserved_size_bound"}
    if _exceeds_depth(wire):
        return {"contract": contract, "syntax": "unobserved_depth_bound"}
    nested_duplicates = 0

    def collect(pairs: list[tuple[str, object]]) -> _ObjectPairs:
        nonlocal nested_duplicates
        nested_duplicates += len(pairs) - len({key for key, _ in pairs})
        return _ObjectPairs(tuple(pairs))

    try:
        value: object = json.loads(wire, object_pairs_hook=collect, parse_constant=_reject_constant)
    except (json.JSONDecodeError, ValueError):
        return {"contract": contract, "syntax": "invalid_json"}
    except RecursionError:
        return {"contract": contract, "syntax": "unobserved_depth_bound"}
    result: dict[str, object] = {"contract": contract, "syntax": "valid_json", "rootType": _kind(value)}
    if not isinstance(value, _ObjectPairs):
        return result
    expected = ("report", "complete") if contract == "final_report" else (
        "intent", "confidence", "reasoning", "needsClarification")
    counts = Counter(key for key, _ in value.pairs)
    observed = dict(value.pairs)
    result.update({"knownFields": {key: {"present": key in counts,
                                         "type": _kind(observed[key]) if key in counts else None,
                                         "duplicateCount": max(counts[key] - 1, 0)} for key in expected},
                   "unexpectedFieldCount": len(set(counts) - set(expected)),
                   "topLevelDuplicateCount": len(value.pairs) - len(counts),
                   "allObjectDuplicateCount": nested_duplicates,
                   "expectedFieldOrder": tuple(key for key, _ in value.pairs) == expected})
    return result


def safe_json_shape(raw: object) -> dict[str, object]:
    """Validate the private observer's fixed schema; never accept arbitrary JSON mappings."""
    if not isinstance(raw, dict) or raw.get("contract") not in {"classification", "final_report"}:
        raise ValueError("Invalid private JSON shape contract")
    contract, syntax = raw["contract"], raw.get("syntax")
    if not isinstance(syntax, str) or syntax not in SYNTAX_KINDS:
        raise ValueError("Invalid private JSON shape syntax")
    safe: dict[str, object] = {"contract": contract, "syntax": syntax}
    if syntax == "unobserved_diagnostic_failure":
        failure = raw.get("diagnosticError")
        if set(raw) != {"contract", "syntax", "diagnosticError"} or not isinstance(failure, str) or failure not in DIAGNOSTIC_ERRORS:
            raise ValueError("Invalid private JSON diagnostic failure")
        safe["diagnosticError"] = failure
        return safe
    if syntax != "valid_json":
        if set(raw) != {"contract", "syntax"}:
            raise ValueError("Unexpected private JSON shape fields")
        return safe
    root = raw.get("rootType")
    if not isinstance(root, str) or root not in JSON_KINDS:
        raise ValueError("Invalid private JSON shape root")
    safe["rootType"] = root
    if root != "object":
        if set(raw) != {"contract", "syntax", "rootType"}:
            raise ValueError("Unexpected private JSON shape fields")
        return safe
    counts = {"unexpectedFieldCount", "topLevelDuplicateCount", "allObjectDuplicateCount"}
    if set(raw) != {"contract", "syntax", "rootType", "knownFields", "expectedFieldOrder"} | counts:
        raise ValueError("Unexpected private JSON shape fields")
    for key in counts:
        count = raw[key]
        if type(count) is not int or count < 0:
            raise TypeError("Private JSON shape count must be nonnegative")
        safe[key] = count
    order = raw["expectedFieldOrder"]
    if type(order) is not bool:
        raise TypeError("Private JSON shape order must be boolean")
    safe["expectedFieldOrder"] = order
    expected = ("report", "complete") if contract == "final_report" else (
        "intent", "confidence", "reasoning", "needsClarification")
    fields = raw["knownFields"]
    if not isinstance(fields, dict) or set(fields) != set(expected):
        raise ValueError("Unexpected private JSON known fields")
    safe_fields: dict[str, object] = {}
    for key in expected:
        field = fields[key]
        if not isinstance(field, dict) or set(field) != {"present", "type", "duplicateCount"}:
            raise ValueError("Unexpected private JSON known field properties")
        present, kind, duplicate = field["present"], field["type"], field["duplicateCount"]
        if type(present) is not bool or type(duplicate) is not int or duplicate < 0:
            raise TypeError("Invalid private JSON field presence/count")
        if kind is not None and (not isinstance(kind, str) or kind not in JSON_KINDS):
            raise ValueError("Invalid private JSON field type")
        safe_fields[key] = {"present": present, "type": kind, "duplicateCount": duplicate}
    safe["knownFields"] = safe_fields
    return safe


def safe_observe_json_shape(wire: str, contract: Contract) -> dict[str, object]:
    """Diagnostic failure is explicit and cannot replace the caller's validation result."""
    try:
        return safe_json_shape(observe_json_shape(wire, contract))
    except RunAborted:
        raise
    except Exception as error:  # noqa: BLE001 - private diagnostic only; original validator still decides
        kind = type(error).__name__
        return {"contract": contract, "syntax": "unobserved_diagnostic_failure",
                "diagnosticError": kind if kind in DIAGNOSTIC_ERRORS else "other"}
