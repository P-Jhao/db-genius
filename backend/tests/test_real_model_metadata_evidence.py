"""Offline metadata projection and byte-transparent relay checks; no sockets."""

from __future__ import annotations

import copy
import hashlib
import json
import threading
from collections.abc import Iterator
from http.client import HTTPMessage
from io import BytesIO
from types import TracebackType
from typing import Self, cast

import httpx
import pytest
import real_model_metadata_evidence as metadata
from pydantic import SecretStr
from real_model_cases import MODEL
from real_model_relay import RealProviderRelay, RelayHandler


def schema() -> dict[str, object]:
    return {"dbType": "mysql", "incomplete": False, "errorMessage": None,
            "databaseName": "private-database", "host": "private-host", "port": 3306,
            "connection": {"password": "synthetic-secret"}, "comment": "private-comment",
            "tables": [{"name": "customers", "rowCount": 7, "comment": "private-comment",
                        "columns": [{"name": "region", "type": "varchar(20)", "nullable": False,
                                     "primaryKey": False, "comment": "private-comment", "default": "private-default"}],
                        "indexes": [{"name": "ix_customers_region", "columns": ["region"]}]}]}


def system(value: object, db_id: int = 8) -> dict[str, object]:
    return {"role": "system", "content": f"Database {db_id} schema:\n{json.dumps(value)}"}


def capture(messages: list[dict[str, object]]) -> dict[str, object]:
    return metadata.metadata_inputs({"messages": messages}, ("synthetic-secret",))


def first(result: dict[str, object]) -> dict[str, object]:
    return cast(list[dict[str, object]], result["sources"])[0]


def test_full_schema_is_actual_structural_projection_without_private_properties() -> None:
    request: dict[str, object] = {"messages": [system(schema())]}
    before = copy.deepcopy(request)
    result = metadata.metadata_inputs(request, ("synthetic-secret",))
    source = first(result)
    assert request == before and result["status"] == "observed"
    assert source["status"] == "complete" and source["dbId"] == 8 and source["messageIndex"] == 0
    assert source["inputBounded"] is False and source["metadataIncomplete"] is False
    assert source["metadataErrorPresent"] is False and source["missingFields"] == []
    projection = cast(dict[str, object], source["projection"])
    table = cast(list[dict[str, object]], projection["tables"])[0]
    assert table["rowCount"] == 7 and table["indexes"] == [{"name": "ix_customers_region", "columns": ["region"]}]
    assert table["columns"] == [{"name": "region", "type": "varchar(20)", "nullable": False, "primaryKey": False}]
    assert "foreignKeys" in cast(list[str], source["notCapturedProperties"])
    encoded = json.dumps(result)
    assert all(text not in encoded for text in ("private-host", "private-database", "private-comment", "private-default"))
    content = cast(str, system(schema())["content"]).split("\n", 1)[1]
    assert source["jsonUtf8Sha256"] == hashlib.sha256(content.encode()).hexdigest()


def test_independent_system_blocks_and_explicit_tool_result_keep_provenance() -> None:
    first_block = cast(str, system(schema(), 8)["content"])
    second_block = cast(str, system(schema(), 9)["content"])
    messages: list[dict[str, object]] = [{"role": "system", "content": first_block + "\n\n" + second_block},
                {"role": "assistant", "tool_calls": [{"id": "schema-call", "function": {
                    "name": "getDatabaseSchema", "arguments": '{"db_id":11,"host":"private-host"}'}}]},
                {"role": "tool", "tool_call_id": "unrelated", "content": json.dumps(schema())},
                {"role": "tool", "tool_call_id": "schema-call", "content": json.dumps(schema())}]
    sources = cast(list[dict[str, object]], capture(messages)["sources"])
    assert [(s["dbId"], s["messageIndex"]) for s in sources] == [(8, 0), (9, 0), (11, 3)]
    assert sources[2]["sourceType"] == "getDatabaseSchema_tool_result"
    assert sources[2]["toolCallId"] == "schema-call" and sources[2]["status"] == "complete"
    assert "private-host" not in json.dumps(sources)


def test_documentation_narrative_and_unpaired_tool_content_are_absent() -> None:
    content = cast(str, system(schema())["content"])
    result = capture([{"role": "system", "content": "# Database documentation\n" + content},
                      {"role": "user", "content": content}, {"role": "assistant", "content": content},
                      {"role": "tool", "tool_call_id": "unknown", "content": json.dumps(schema())}])
    assert result["status"] == "absent" and result["sources"] == []
    assert capture([])["status"] == "absent"


def test_bounding_and_adapter_incompleteness_are_separate_partial_facts() -> None:
    bounded = {"marker": metadata.MARKER, "truncated": True, "sourceIncomplete": False, "preview": schema()}
    source = first(capture([system(bounded)]))
    assert source["status"] == "partial" and source["inputBounded"] is True
    assert source["metadataIncomplete"] is False
    incomplete = {**schema(), "incomplete": True, "errorMessage": "private-error", "schemaInferred": True, "sampleSize": 50}
    source = first(capture([system(incomplete)]))
    assert source["status"] == "partial" and source["inputBounded"] is False
    assert source["metadataIncomplete"] is True and source["metadataErrorPresent"] is True
    projection = cast(dict[str, object], source["projection"])
    assert projection["schemaInferred"] is True and projection["sampleSize"] == 50
    assert "private-error" not in json.dumps(source)
    empty = first(capture([system({**bounded, "preview": {}})]))
    assert empty["status"] == "partial" and empty["projection"] == {}
    assert "/tables" in cast(list[str], empty["missingFields"])


def test_missing_fields_remain_missing_without_inferred_empty_indexes() -> None:
    value = schema()
    table = cast(list[dict[str, object]], value["tables"])[0]
    del table["indexes"]
    del cast(list[dict[str, object]], table["columns"])[0]["nullable"]
    del value["incomplete"]
    del value["errorMessage"]
    source = first(capture([system(value)]))
    assert source["status"] == "partial" and source["metadataIncomplete"] is None
    projected_table = cast(list[dict[str, object]], cast(dict[str, object], source["projection"])["tables"])[0]
    assert "indexes" not in projected_table
    assert set(cast(list[str], source["missingFields"])) == {
        "/incomplete", "/errorMessage", "/tables/0/indexes", "/tables/0/columns/0/nullable"}


@pytest.mark.parametrize("content", [
    pytest.param('{"dbType":"mysql","dbType":"x"}', id="duplicate-key"),
    pytest.param('{"tables":', id="unfinished-json"),
    pytest.param('{"dbType":"mysql","tables":{},"incomplete":false}', id="invalid-tables"),
    pytest.param('{"dbType":"mysql","tables":[],"incomplete":NaN}', id="nonfinite-json"),
    pytest.param('{"dbType":"mysql","tables":[],"incomplete":false,"sampleSize":true}', id="boolean-count"),
    pytest.param('[' * 1100 + '0' + ']' * 1100, id="deep-json"),
    pytest.param('{"number":' + '9' * 5000 + '}', id="long-integer"),
])
def test_malformed_json_and_shapes_only_retain_fixed_diagnostic(content: str) -> None:
    result = capture([{"role": "system", "content": "Database 8 schema:\n" + content}])
    assert result["status"] == "malformed"
    source = first(result)
    assert source["status"] == "malformed" and "projection" not in source
    assert source["diagnostic"] in {"duplicate_json_key", "malformed_schema_json", "invalid_array",
                                     "invalid_json_number", "invalid_schema_field", "schema_nesting_limit", "invalid_object"}
    assert content not in json.dumps(result)


@pytest.mark.parametrize("suffix", ["\nprivate-tail", "\n\n"])
def test_schema_block_trailing_content_is_diagnosed(suffix: str) -> None:
    result = capture([{"role": "system", "content": cast(str, system(schema())["content"]) + suffix}])
    assert result["status"] == "malformed" and result["diagnostic"] == "schema_block_trailing_content"
    assert "private-tail" not in json.dumps(result)


@pytest.mark.parametrize("arguments", ['{"db_id":true}', '{"db_id":"8"}', '{"db_id":8,"db_id":9}', "private-invalid"])
def test_bad_explicit_tool_links_are_nonthrowing(arguments: str) -> None:
    result = capture([{"role": "assistant", "tool_calls": [{"id": "call", "function": {
        "name": "getDatabaseSchema", "arguments": arguments}}]}])
    assert result["status"] == "malformed" and "private-invalid" not in json.dumps(result)
    assert metadata.metadata_inputs({}, ())["status"] == "malformed"


def test_known_secrets_are_redacted_in_allowed_names() -> None:
    value = schema()
    cast(list[dict[str, object]], value["tables"])[0]["name"] = "synthetic-secret_table"
    encoded = json.dumps(capture([system(value)]))
    assert "synthetic-secret" not in encoded and "[omitted]_table" in encoded


@pytest.mark.parametrize("call_id", ["", "\ud800"])
def test_invalid_tool_identity_is_diagnosed(call_id: str) -> None:
    result = capture([{"role": "assistant", "tool_calls": [{"id": call_id, "function": {
        "name": "getDatabaseSchema", "arguments": '{"db_id":8}'}}]}])
    assert result["status"] == "malformed"
    json.dumps(result, ensure_ascii=False).encode("utf-8")


@pytest.mark.parametrize("value,diagnostic", [
    ({"marker": metadata.MARKER, "truncated": False, "preview": {}}, "invalid_bound_marker"),
    ({"marker": metadata.MARKER, "truncated": True, "sourceIncomplete": True, "preview": schema()},
     "conflicting_incomplete_flags"),
    ({**schema(), "errorMessage": {"private-error": "do not retain"}}, "invalid_schema_error_flag"),
    ({**schema(), "tables": [{"name": "customers", "columns": [], "indexes": [{"name": "ix", "columns": [9]}]}]},
     "invalid_index_columns"),
])
def test_malformed_flags_and_indexes_keep_no_error_text(value: dict[str, object], diagnostic: str) -> None:
    source = first(capture([system(value)]))
    assert source["status"] == "malformed" and source["diagnostic"] == diagnostic
    assert "projection" not in source and "private-error" not in json.dumps(source)


@pytest.mark.parametrize("error", [RecursionError("private-error"), ValueError("private-error")])
def test_parser_resource_errors_become_safe_diagnostics(monkeypatch: pytest.MonkeyPatch, error: Exception) -> None:
    class FailedDecoder:
        def raw_decode(self, text: str, index: int = 0) -> tuple[object, int]:
            raise error

        def decode(self, text: str) -> object:
            raise error

    monkeypatch.setattr(metadata, "DECODER", FailedDecoder())
    source = first(capture([system(schema())]))
    assert source["diagnostic"] == ("schema_nesting_limit" if isinstance(error, RecursionError) else "malformed_schema_json")
    assert "private-error" not in json.dumps(source)


class LocalHandler(RelayHandler):
    def __init__(self, body: bytes, server: RealProviderRelay) -> None:
        self.server = server
        self.rfile, self.wfile = BytesIO(body), BytesIO()
        self.headers = HTTPMessage()
        self.headers["Content-Length"] = str(len(body))
        self.observation = {}

    def _route(self) -> tuple[RealProviderRelay, str, str]:
        return cast(RealProviderRelay, self.server), "python", "/v1/chat/completions"

    def send_response(self, code: int, message: str | None = None) -> None:
        assert code == 200

    def send_header(self, keyword: str, value: str) -> None:
        pass

    def end_headers(self) -> None:
        pass

    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
        raise AssertionError(f"Unexpected local HTTP error: {code}")


class LocalResponse:
    status_code = 200

    def __init__(self, wire: bytes) -> None:
        self.wire = wire
        self.headers = {"content-type": "text/event-stream"}

    def __enter__(self) -> Self:
        return self

    def __exit__(self, kind: type[BaseException] | None, error: BaseException | None,
                 trace: TracebackType | None) -> None:
        pass

    def iter_raw(self) -> Iterator[bytes]:
        split = self.wire.index("已".encode()) + 1
        yield self.wire[:split]
        yield self.wire[split:]


@pytest.mark.parametrize("enabled,malformed", [(False, False), (True, False), (True, True)])
def test_metadata_gate_and_failures_preserve_actual_http_body_sse_and_usage(
    monkeypatch: pytest.MonkeyPatch, enabled: bool, malformed: bool,
) -> None:
    server = object.__new__(RealProviderRelay)
    server.upstream_key, server.access_key = SecretStr("synthetic-upstream"), SecretStr("synthetic-access")
    server.upstream, server.label, server.capture_synthetic = "https://offline.invalid", "offline", enabled
    server.lock, server.records, server.requests = threading.Lock(), [], []
    message = system(schema()) if not malformed else {"role": "system", "content": 'Database 8 schema:\n{"private":'}
    body = json.dumps({"model": MODEL, "stream": True, "messages": [message]}, indent=2).encode()
    packet = {"choices": [{"delta": {"content": "已完成"}, "finish_reason": "stop"}],
              "usage": {"prompt_tokens": 3, "completion_tokens": 5, "total_tokens": 8}}
    wire = ("data: " + json.dumps(packet, ensure_ascii=False) + "\r\n\r\ndata: [DONE]\r\n\r\n").encode()
    forwarded: list[bytes] = []

    class LocalClient:
        def __init__(self, **kwargs: object) -> None:
            pass

        def __enter__(self) -> Self:
            return self

        def __exit__(self, kind: type[BaseException] | None, error: BaseException | None,
                     trace: TracebackType | None) -> None:
            pass

        def stream(self, method: str, url: str, *, content: bytes, headers: dict[str, str]) -> LocalResponse:
            assert method == "POST" and url == "https://offline.invalid/v1/chat/completions"
            assert headers["Authorization"] == "Bearer synthetic-upstream"
            forwarded.append(content)
            return LocalResponse(wire)

    monkeypatch.setattr(httpx, "Client", LocalClient)
    calls: list[dict[str, object]] = []
    original_capture = metadata.metadata_inputs

    def observe(request: dict[str, object], secrets: tuple[str, ...]) -> dict[str, object]:
        calls.append(copy.deepcopy(request))
        return original_capture(request, secrets)

    monkeypatch.setattr(metadata, "metadata_inputs", observe)
    handler = LocalHandler(body, server)
    handler.do_POST()
    assert forwarded == [body] and cast(BytesIO, handler.wfile).getvalue() == wire
    report = server.records[0]
    assert report["providerDone"] is True and report["usage"] == packet["usage"]
    assert report["transportError"] is None and report["evidenceError"] is None
    assert report["finishReason"] == "stop" and report["finishReasonPresent"] is True
    assert len(calls) == int(enabled)
    assert ("syntheticMetadataInputs" in report) == enabled
    if enabled:
        evidence = cast(dict[str, object], report["syntheticMetadataInputs"])
        assert evidence["status"] == ("malformed" if malformed else "observed")
