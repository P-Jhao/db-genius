"""Restricted recovery of provider DSML tool text and summary cleanup."""

import json
import math
import re
from dataclasses import dataclass
from uuid import uuid4

_PREFIX = r"[｜|]+DSML[｜|]+"
_WRAPPER = re.compile(fr"<{_PREFIX}tool_calls\s*>(.*?)</{_PREFIX}tool_calls\s*>", re.IGNORECASE | re.DOTALL)
_INVOKE = re.compile(fr"<(?:{_PREFIX})?invoke\b([^>]*)>(.*?)</(?:{_PREFIX})?invoke\s*>", re.IGNORECASE | re.DOTALL)
_PARAMETER = re.compile(fr"<(?:{_PREFIX})?parameter\b([^>]*)>(.*?)</(?:{_PREFIX})?parameter\s*>", re.IGNORECASE | re.DOTALL)
_ATTRIBUTE = re.compile(r'\b(name|string)\s*=\s*"([^"]*)"', re.IGNORECASE)
_PROTOCOL = re.compile(r"<(?:(?:[｜|]+DSML[｜|]+)|tool_calls\b|invoke\b|parameter\b)", re.IGNORECASE)
_CLOSING = re.compile(fr"</(?:{_PREFIX})?(?:tool_calls|invoke|parameter)\s*>", re.IGNORECASE)
_SIMPLE_BLOCK = re.compile(r"<(tool_calls|invoke)\b[^>]*>.*?</\1\s*>", re.IGNORECASE | re.DOTALL)


@dataclass(frozen=True)
class RecoveredCall:
    name: str
    args: dict[str, object]


@dataclass(frozen=True)
class StructuredCall:
    name: str | None
    args: str | None
    id: str | None


@dataclass(frozen=True)
class AllowedTool:
    required: frozenset[str]
    fields: frozenset[str]


_LEGACY_ARGUMENTS: dict[str, dict[str, str]] = {
    "getDatabaseSchema": {"dbConfigId": "db_id"},
    "executeSql": {"dbConfigId": "db_id", "sql": "statement"},
    "readFile": {"fileId": "file_id"},
    "readImage": {"fileId": "file_id"},
    "compareDatabases": {"preDbConfigId": "pre_id", "testDbConfigId": "test_id"},
    "readToolOutput": {"artifactId": "artifact_id", "limit": "length"},
    "doTerminate": {"summary": "reason"},
}


def _normalize(name: str, arguments: dict[str, object], schema: AllowedTool) -> dict[str, object]:
    aliases = _LEGACY_ARGUMENTS.get(name, {})
    normalized: dict[str, object] = {}
    for key, value in arguments.items():
        canonical = aliases.get(key, key)
        if canonical not in schema.fields:
            raise ValueError(f"Unknown DSML argument for {name}: {key}")
        if canonical in normalized:
            raise ValueError(f"Conflicting DSML argument aliases for {name}: {canonical}")
        normalized[canonical] = value
    return normalized


def _attributes(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for match in _ATTRIBUTE.finditer(text):
        key = match.group(1).lower()
        if key in values:
            raise ValueError(f"Duplicate DSML {key} attribute")
        values[key] = match.group(2)
    return values


def _typed_value(raw: str, string: str | None) -> object:
    if string is not None and string.lower() not in {"true", "false"}:
        raise ValueError("Invalid DSML string attribute")
    if string is not None and string.lower() == "true":
        return raw
    value = raw.strip()
    try:
        return int(value)
    except ValueError:
        pass
    try:
        number = float(value)
    except ValueError:
        number = None
    if number is not None:
        if not math.isfinite(number):
            raise ValueError("Non-finite DSML numeric parameter")
        return number
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    return raw


def _parse_invokes(body: str) -> list[RecoveredCall]:
    calls: list[RecoveredCall] = []
    position = 0
    for invoke in _INVOKE.finditer(body):
        if body[position:invoke.start()].strip():
            raise ValueError("Malformed DSML invoke sequence")
        attributes = _attributes(invoke.group(1))
        name = attributes.get("name", "")
        if not name:
            raise ValueError("DSML invoke is missing a tool name")
        arguments: dict[str, object] = {}
        parameter_position = 0
        for parameter in _PARAMETER.finditer(invoke.group(2)):
            if invoke.group(2)[parameter_position:parameter.start()].strip():
                raise ValueError("Malformed DSML parameter sequence")
            parameter_attributes = _attributes(parameter.group(1))
            key = parameter_attributes.get("name", "")
            if not key or key in arguments:
                raise ValueError("DSML parameter name is missing or duplicated")
            arguments[key] = _typed_value(parameter.group(2), parameter_attributes.get("string"))
            parameter_position = parameter.end()
        if invoke.group(2)[parameter_position:].strip():
            raise ValueError("DSML invoke has malformed parameters")
        calls.append(RecoveredCall(name, arguments))
        position = invoke.end()
    if body[position:].strip() or not calls:
        raise ValueError("Malformed DSML tool call block")
    return calls


def parse(content: str, *, allow_simple: bool = False) -> tuple[list[RecoveredCall], str] | None:
    """Parse a complete wrapper; simple invokes require a corroborating structured call."""
    wrappers = list(_WRAPPER.finditer(content))
    if len(wrappers) > 1:
        raise ValueError("Multiple DSML tool-call wrappers are ambiguous")
    if wrappers:
        wrapper = wrappers[0]
        outside = content[:wrapper.start()] + content[wrapper.end():]
        if _PROTOCOL.search(outside):
            raise ValueError("DSML protocol text outside the tool-call wrapper")
        return _parse_invokes(wrapper.group(1)), outside.strip()
    if _INVOKE.search(content) and (allow_simple or re.match(fr"\s*<{_PREFIX}invoke\b", content,
                                                          re.IGNORECASE)):
        return _parse_invokes(content), ""
    if not allow_simple and re.search(fr"<{_PREFIX}", content, re.IGNORECASE) is None:
        return None
    if _PROTOCOL.search(content):
        raise ValueError("Incomplete DSML tool-call block")
    return None


def reconcile(content: str, structured: list[StructuredCall],
              allowed: dict[str, AllowedTool]) -> tuple[str, list[dict[str, object]] | None]:
    """Return recovered calls only with an explicit tool allowlist and unambiguous evidence."""
    parsed = parse(content, allow_simple=bool(structured))
    if parsed is None:
        return content, None
    recovered, clean = parsed
    if not structured and clean:
        return strip(content), None
    if structured and len(structured) != len(recovered):
        raise ValueError("DSML and structured tool-call counts differ")
    calls: list[dict[str, object]] = []
    for index, candidate in enumerate(recovered):
        if candidate.name not in allowed:
            raise ValueError(f"Unknown DSML tool: {candidate.name}")
        schema = allowed[candidate.name]
        normalized = _normalize(candidate.name, candidate.args, schema)
        original = structured[index] if structured else None
        if original is not None and original.name and original.name != candidate.name:
            raise ValueError("DSML and structured tool names differ")
        if original is not None and not original.id:
            raise ValueError("Structured tool call lacks an ID")
        arguments = normalized
        if original is not None and original.args:
            try:
                existing = json.loads(original.args)
            except json.JSONDecodeError:
                pass
            else:
                if not isinstance(existing, dict):
                    raise TypeError("Model tool-call arguments must be a JSON object")
                # Original valid structured arguments take precedence over DSML text.
                arguments = existing
        if not schema.required.issubset(arguments):
            raise ValueError(f"DSML tool arguments are missing required fields for {candidate.name}")
        if any(key not in schema.fields for key in arguments):
            raise ValueError(f"Unknown structured argument for {candidate.name}")
        calls.append({"name": candidate.name, "args": arguments,
                      "id": original.id if original is not None else f"dsml-{uuid4().hex}",
                      "type": "tool_call"})
    ids = [call["id"] for call in calls]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate tool-call IDs")
    return clean, calls


def strip(content: str) -> str:
    """Remove protocol blocks and unfinished markers from a final summary."""
    clean = _WRAPPER.sub("", content)
    clean = _SIMPLE_BLOCK.sub("", clean)
    clean = _INVOKE.sub("", clean)
    clean = _CLOSING.sub("", clean)
    # An unfinished invoke may contain SQL parameters, so do not expose its body.
    marker = re.search(fr"<(?:{_PREFIX})?(?:invoke|parameter)\b", clean, re.IGNORECASE)
    if marker is not None:
        clean = clean[:marker.start()]
    clean = re.sub(fr"</?{_PREFIX}[^>\n]*>?", "", clean, flags=re.IGNORECASE)
    clean = re.sub(r"</?tool_calls\b[^>\n]*>?", "", clean, flags=re.IGNORECASE)
    for index, character in enumerate(clean):
        if character == "<":
            tail = re.sub(r"\|+", "||", clean[index:index + 40].replace("｜", "|").lower())
            tail = tail.replace("</", "<", 1)
            if len(tail) > 2 and any(prefix.startswith(tail) or tail.startswith(prefix) for prefix in (
                "<||dsml||tool_calls", "<||dsml||invoke", "<||dsml||parameter",
                "<tool_calls", "<invoke", "<parameter",
            )):
                clean = clean[:index]
                break
    return clean


def summary_cleanup(content: str) -> tuple[str, str]:
    """Classify cleanup without granting summary text any tool capability."""
    clean = strip(content)
    remainder = _WRAPPER.sub("", content)
    remainder = _SIMPLE_BLOCK.sub("", remainder)
    remainder = _INVOKE.sub("", remainder)
    if (_PROTOCOL.search(remainder) or _CLOSING.search(remainder) or
            strip(remainder) != remainder):
        return clean, "incomplete"
    for wrapper in _WRAPPER.finditer(content):
        try:
            _parse_invokes(wrapper.group(1))
        except ValueError:
            return clean, "incomplete"
    return clean, "removed" if clean != content else "none"


class SummaryFilter:
    """Hold text after '<' until final cleanup, so fragments cannot reach SSE."""

    def __init__(self) -> None:
        self.held = ""

    def push(self, value: str) -> str:
        if self.held:
            self.held += value
            return ""
        index = value.find("<")
        if index < 0:
            return value
        self.held = value[index:]
        return value[:index]

    def finish(self) -> str:
        return strip(self.held) if self.held else ""
