"""Actual FastAPI model POST -> local relay -> local HTTP upstream; no real provider."""
import io
import json
import logging
import threading
from collections.abc import Iterator
from types import SimpleNamespace

import pytest
import real_model_relay as relay_module
from fastapi.testclient import TestClient
from langchain_core.messages import HumanMessage
from pydantic import SecretStr
from real_model_cases import MODEL
from real_model_relay import RealProviderRelay
from test_chat_api import parse_events, reply
from test_model_parameters import tool_reply
from test_model_protocol import Handler, Provider

from app.agent.json_capabilities import parse_capability_allowlist
from app.agent.model import CompatibleChatModel, completion_url
from app.agent.streaming import ModelStream
from app.agent.tools import RunTools
from app.agent.types import ChatRequest, Usage
from app.core.config import Settings
from app.models import Message
from app.services import context_compress, database_tools, model_config

pytest_plugins = ["test_chat_api"]
type WireCapture = tuple[RealProviderRelay, list[bytes], list[bytes]]


@pytest.fixture
def wire_relay(provider: Provider, monkeypatch: pytest.MonkeyPatch) -> Iterator[WireCapture]:
    host, port = provider.server_address
    upstream_wire: list[bytes] = []
    relay_wire: list[bytes] = []
    original_handler, original_body = Handler.do_POST, relay_module.request_body

    def capture_upstream(handler: Handler) -> None:
        body = handler.rfile.read(int(handler.headers["Content-Length"]))
        upstream_wire.append(body)
        previous = handler.rfile
        handler.rfile = io.BytesIO(body)
        try:
            original_handler(handler)
        finally:
            handler.rfile = previous

    def capture_relay(*args: object) -> bytes:
        body = original_body(*args)  # type: ignore[arg-type]
        relay_wire.append(body)
        return body

    monkeypatch.setattr(Handler, "do_POST", capture_upstream)
    monkeypatch.setattr(relay_module, "request_body", capture_relay)
    relay = RealProviderRelay(SecretStr("synthetic-only"), f"http://{host}:{port}")
    thread = threading.Thread(target=relay.serve_forever, daemon=True)
    thread.start()
    try:
        yield relay, relay_wire, upstream_wire
    finally:
        relay.shutdown()
        relay.server_close()
        thread.join(2)


def configure(monkeypatch: pytest.MonkeyPatch, wire: WireCapture, entries: list[dict[str, str]],
              actual_model: str = MODEL) -> None:
    import app.api.chat as chat_api

    relay = wire[0]
    base = f"http://127.0.0.1:{relay.server_port}/python"
    settings = Settings.model_construct(model_chat_json_capabilities=parse_capability_allowlist(json.dumps(entries)))
    monkeypatch.setattr(chat_api, "get_settings", lambda: settings)
    monkeypatch.setattr(model_config, "resolve_active_model", lambda *_: SimpleNamespace(
        base_url=base, api_key=relay.access_key, model_name=actual_model, context_window=8192))


def entry(endpoint: str, model: str = MODEL) -> dict[str, str]:
    return {"endpoint": endpoint, "model": model, "capability": "chat_json_object"}


def relay_endpoint(wire: WireCapture) -> str:
    return f"http://127.0.0.1:{wire[0].server_port}/python/v1/chat/completions"


def assert_wire(wire: WireCapture, provider: Provider, formats: list[object]) -> None:
    relay, received, forwarded = wire
    assert received == forwarded and len(received) == len(formats)
    assert [json.loads(body) for body in received] == provider.requests
    assert [request.get("response_format") for request in provider.requests] == formats
    assert [call["parameters"]["response_format"] for call in relay.evidence(0)] == formats


@pytest.mark.parametrize("scenario", ["default", "matched", "mismatched", "cross-model", "relay-override"])
def test_actual_chat_classifier_only_gets_explicit_json_capability(
    chat_client: tuple[object, ...], provider: Provider, wire_relay: WireCapture,
    monkeypatch: pytest.MonkeyPatch, scenario: str,
) -> None:
    client = chat_client[0]
    assert isinstance(client, TestClient)
    endpoint = relay_endpoint(wire_relay)
    rules = {"default": [], "matched": [entry(endpoint)],
             "mismatched": [entry(endpoint.replace("/python/", "/java/"))],
             "cross-model": [entry(endpoint, "another-model")],
             "relay-override": [entry("https://api.deepseek.com/v1/chat/completions")]}[scenario]
    configure(monkeypatch, wire_relay, rules)
    provider.replies = [reply(json.dumps({"intent": "simple_chat", "confidence": 0.95,
        "reasoning": "general", "needsClarification": False})), reply("answer")]
    response = client.post("/api/chat", json={"message": "question"})
    assert response.status_code == 200 and parse_events(response.text)[-1]["type"] == "done"
    assert_wire(wire_relay, provider, [{"type": "json_object"} if scenario == "matched" else None, None])
    assert "jsonShape" not in response.text


@pytest.mark.parametrize("valid_report", [False, True])
def test_actual_write_and_termination_keep_tools_then_one_json_report_without_replay(
    chat_client: tuple[object, ...], provider: Provider, wire_relay: WireCapture,
    monkeypatch: pytest.MonkeyPatch, valid_report: bool,
) -> None:
    import app.api.chat as chat_api

    client = chat_client[0]
    assert isinstance(client, TestClient)
    configure(monkeypatch, wire_relay, [entry(relay_endpoint(wire_relay))])
    monkeypatch.setattr(chat_api, "_check_resources", lambda *_: None)
    monkeypatch.setattr(database_tools, "get_schema", lambda *_: {"tables": []})
    statements: list[str] = []

    def execute(_user: int, _db: int, statement: str, **_kwargs: object) -> dict[str, object]:
        statements.append(statement)
        return {"success": True, "affectedRows": 1}

    monkeypatch.setattr(database_tools, "execute_statement", execute)
    report: dict[str, object] = {"report": "Verified one write.", "complete": True}
    if not valid_report:
        report["SYNTHETIC_PRIVATE_FIELD"] = "SYNTHETIC_PRIVATE_VALUE"
    provider.replies = [tool_reply("executeSql", {"db_id": 12, "statement": "INSERT INTO demo (value) VALUES (1)"}),
                        tool_reply("doTerminate", {"reason": "done"}), reply(json.dumps(report))]
    response = client.post("/api/chat", json={"message": "Insert one", "dbConfigIds": [12], "confirmedIntent": "sql_query"})
    assert response.status_code == 200
    assert statements == ["INSERT INTO demo (value) VALUES (1)"]
    assert_wire(wire_relay, provider, [None, None, {"type": "json_object"}])
    assert any(event["type"] == "error" for event in parse_events(response.text)) is not valid_report
    assert "jsonShape" not in response.text and "SYNTHETIC_PRIVATE" not in response.text
    assert len(provider.requests) == 3


def test_failed_api_classifier_keeps_private_shape_with_its_public_task_identity(
    chat_client: tuple[object, ...], provider: Provider, wire_relay: WireCapture,
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    client = chat_client[0]
    assert isinstance(client, TestClient)
    configure(monkeypatch, wire_relay, [entry(relay_endpoint(wire_relay))])
    caplog.set_level(logging.INFO, logger="app.agent.graph")
    provider.replies = [reply(json.dumps({"intent": "invalid", "SYNTHETIC_PRIVATE_FIELD": "SYNTHETIC_PRIVATE_VALUE"}))]
    response = client.post("/api/chat", json={"message": "question"})
    events = parse_events(response.text)
    assert [event["type"] for event in events].count("error") == 1
    assert [event["type"] for event in events].count("usage") == 1 and events[-1]["type"] == "done"
    assert not any(event["type"] in {"classified", "clarify", "routing", "thinking", "step"} for event in events)
    prefix = "Intent classification validation "
    row = next(json.loads(record.getMessage().removeprefix(prefix)) for record in caplog.records
               if record.name == "app.agent.graph" and record.getMessage().startswith(prefix))
    assert row["taskId"] == events[-1]["taskId"]
    assert row["jsonShape"]["unexpectedFieldCount"] == 1
    assert_wire(wire_relay, provider, [{"type": "json_object"}])
    conversation = events[0]["content"]
    history = client.get(f"/api/chat/conversations/{conversation}/messages").json()
    assert all(value not in response.text + json.dumps(history) + caplog.text for value in (
        "SYNTHETIC_PRIVATE_FIELD", "SYNTHETIC_PRIVATE_VALUE"))
    assert "jsonShape" not in response.text + json.dumps(history)


@pytest.mark.asyncio
async def test_matched_mode_keeps_step_summary_and_both_context_compression_calls_plain(
    provider: Provider, wire_relay: WireCapture,
) -> None:
    base = relay_endpoint(wire_relay).removesuffix("/v1/chat/completions")
    model = CompatibleChatModel(base_url=base, api_key=wire_relay[0].access_key, model_name=MODEL)
    assert completion_url(model.base_url) == relay_endpoint(wire_relay)
    provider.replies = [reply("step summary"), reply("stream compression"), reply("direct compression")]

    async def emit(_kind: str, _content: object, _step: int) -> None:
        pass

    stream = ModelStream(model, emit, Usage(), chat_json_object=True)
    await stream.call([HumanMessage(content="summarize steps")], event=None)
    rows = [Message(role="user", type="user", content="earlier")]
    await context_compress._summarize(model, rows, None, "en", stream)
    await context_compress._summarize(model, rows, None, "en")
    assert_wire(wire_relay, provider, [None, None, None])


@pytest.mark.asyncio
async def test_json_contract_with_tools_stops_before_transport_or_usage(
    provider: Provider, wire_relay: WireCapture,
) -> None:
    model = CompatibleChatModel(base_url=relay_endpoint(wire_relay), api_key=wire_relay[0].access_key, model_name=MODEL)
    usage = Usage()

    async def emit(_kind: str, _content: object, _step: int) -> None:
        pass

    tools = RunTools(7, ChatRequest(message="question", dbConfigIds=[12]))
    try:
        with pytest.raises(ValueError, match="JSON contract calls cannot carry execution tools"):
            await ModelStream(model, emit, usage, chat_json_object=True).call(
                [HumanMessage(content="classify")], classification=True, tools=tools.for_intent("sql_query"))
    finally:
        tools.close()
    assert_wire(wire_relay, provider, [])
    assert usage.callCount == 0 and tools.statements_executed == 0
