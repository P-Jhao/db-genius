"""Bound JSON tool observations and retain full results for scoped paging."""

import json
from dataclasses import dataclass
from time import monotonic
from uuid import uuid4

from app.core.config import get_settings
from app.core.errors import BusinessError


def output_limit(tool_name: str | None = None) -> int:
    settings = get_settings()
    if tool_name is None:
        return settings.tool_output_max_characters
    return settings.tool_output_per_tool_max_characters.get(tool_name, settings.tool_output_max_characters)


@dataclass(frozen=True)
class Artifact:
    user_id: int
    task_id: str
    content: str
    expires_at: float


class OutputArtifacts:
    def __init__(self, user_id: int, task_id: str) -> None:
        self.user_id = user_id
        self.task_id = task_id
        self._items: dict[str, Artifact] = {}

    def _purge_expired(self) -> None:
        now = monotonic()
        for artifact_id, artifact in list(self._items.items()):
            if artifact.expires_at <= now:
                del self._items[artifact_id]

    def add(self, content: str) -> str:
        self._purge_expired()
        settings = get_settings()
        if len(self._items) >= settings.tool_artifact_max_per_task:
            raise BusinessError(413, "Tool output artifact capacity exceeded")
        artifact_id = uuid4().hex
        self._items[artifact_id] = Artifact(
            self.user_id, self.task_id, content, monotonic() + settings.tool_artifact_ttl_seconds,
        )
        return artifact_id

    def read(self, artifact_id: str, *, user_id: int, task_id: str,
             offset: int, length: int) -> str:
        self._purge_expired()
        artifact = self._items.get(artifact_id)
        if artifact is None or artifact.user_id != user_id or artifact.task_id != task_id:
            raise BusinessError(404, "Output artifact is not part of this task", 404)
        if offset < 0 or length < 1 or length > 16000:
            raise BusinessError(400, "Invalid output page")
        if offset > len(artifact.content):
            raise BusinessError(400, "Offset exceeds output length")
        limit = output_limit("readToolOutput")
        low, high = 0, min(length, len(artifact.content) - offset)
        chosen = ""
        while low <= high:
            size = (low + high) // 2
            page = json.dumps({
                "content": artifact.content[offset:offset + size],
                "offset": offset,
                "nextOffset": offset + size,
                "totalCharacters": len(artifact.content),
                "hasMore": offset + size < len(artifact.content),
            }, ensure_ascii=False)
            if len(page) <= limit:
                chosen = page
                low = size + 1
            else:
                high = size - 1
        if not chosen or (len(artifact.content) > offset and
                          json.loads(chosen)["nextOffset"] == offset):
            raise ValueError("Tool output limit cannot fit a page")
        return chosen

    def clear(self) -> None:
        self._items.clear()

    def discard(self, artifact_id: str) -> None:
        self._items.pop(artifact_id, None)


def _preview(value: object, *, breadth: int, string_size: int,
             depth: int = 0) -> object:
    if depth >= 12:
        return "[nested value omitted]"
    if isinstance(value, dict):
        return {str(key): _preview(item, breadth=breadth, string_size=string_size,
                                   depth=depth + 1)
                for key, item in list(value.items())[:breadth]}
    if isinstance(value, (list, tuple)):
        return [_preview(item, breadth=breadth, string_size=string_size,
                         depth=depth + 1)
                for item in value[:breadth]]
    if isinstance(value, str):
        return value[:string_size]
    return value


def _row_set(normalized: object, metadata: dict[str, object], limit: int) -> str | None:
    if not isinstance(normalized, dict):
        return None
    field = next((key for key in ("data", "result", "rows", "values")
                  if isinstance(normalized.get(key), list)), None)
    if field is None:
        return None
    source = normalized[field]
    if not source:
        return None
    envelope = {key: value for key, value in normalized.items() if key != field}
    envelope.update(metadata)
    envelope["totalItems"] = len(source)
    low, high = 0, min(get_settings().tool_output_max_rows, len(source) - 1)
    chosen: str | None = None
    while low <= high:
        count = (low + high) // 2
        envelope.update({field: source[:count], "returnedItems": count})
        candidate = json.dumps(envelope, ensure_ascii=False, allow_nan=False)
        if len(candidate) <= limit:
            chosen = candidate
            low = count + 1
        else:
            high = count - 1
    return chosen


def bound_json(value: object, artifacts: OutputArtifacts, *, tool_name: str | None = None) -> str:
    """Return valid JSON within configured limits, with a scoped full-result reference."""
    full = json.dumps(value, ensure_ascii=False, default=str, allow_nan=False)
    normalized = json.loads(full)
    limit = output_limit(tool_name)
    if len(full) <= limit:
        return full
    artifact_id = artifacts.add(full)
    breadth = 12
    string_size = 512
    source_markers: dict[str, object] = {}
    if isinstance(normalized, dict):
        for key in ("truncated", "totalRows", "incomplete"):
            if key in normalized:
                source_markers[f"source{key[0].upper()}{key[1:]}"] = normalized[key]
    metadata: dict[str, object] = {
        "marker": "[TRUNCATED:TOOL_OUTPUT_TOO_LONG]", "artifactId": artifact_id,
        "totalCharacters": len(full), "truncated": True, **source_markers,
        "instruction": (
            "0→returned nextOffset, not offset+length; length cap may shrink; hasMore=false: tail≠no gaps"
        ),
    }
    row_set = _row_set(normalized, metadata, limit)
    if row_set is not None:
        return row_set
    while True:
        preview = _preview(normalized, breadth=breadth, string_size=string_size)
        bounded = json.dumps({
            **metadata, "preview": preview,
        }, ensure_ascii=False, default=str, allow_nan=False)
        if len(bounded) <= limit:
            return bounded
        if breadth == 0 and string_size == 0:
            artifacts.discard(artifact_id)
            raise ValueError("Tool output limit cannot fit artifact metadata")
        breadth = breadth // 2
        string_size = string_size // 2
