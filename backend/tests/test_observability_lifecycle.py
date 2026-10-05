"""Complete ASGI/HTTP graph spans and simulated Celery context boundaries."""

import json
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from sqlalchemy.orm import Session, sessionmaker
from starlette.types import Message, Receive, Scope, Send
from task_goal_fixtures import goal_reply
from test_db_config_partial import metadata
from test_model_protocol import Provider, frame

from app.core import observability_tracing as tracing
from app.core.config import Settings, get_settings
from app.core.request_locale import current_locale, locale_scope
from app.core.security import encrypt
from app.models import DbConfig, User
from app.services import chat_store, database_tools, db_config_worker
from app.tasks import db_config as worker

pytest_plugins = ["test_chat_api", "test_db_config_partial"]


@pytest.fixture
def spans(monkeypatch: pytest.MonkeyPatch) -> Iterator[InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider(shutdown_on_exit=False)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(trace, "get_tracer", provider.get_tracer)
    yield exporter
    provider.shutdown()


def one(exporter: InMemorySpanExporter, name: str) -> ReadableSpan:
    found = [item for item in exporter.get_finished_spans() if item.name == name]
    assert len(found) == 1
    return found[0]


@pytest.mark.asyncio
async def test_http_span_covers_final_sse_body_and_resets_locale(spans: InMemorySpanExporter) -> None:
    chunks: list[bytes] = []

    async def application(_scope: Scope, _receive: Receive, send: Send) -> None:
        assert current_locale() == "ja"
        assert not spans.get_finished_spans()
        assert callable(send)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"data: first\n\n", "more_body": True})
        assert not spans.get_finished_spans()
        await send({"type": "http.response.body", "body": b"data: done\n\n", "more_body": False})

    async def receive() -> Message:
        return {"type": "http.request", "body": b""}

    async def send(message: Message) -> None:
        assert not spans.get_finished_spans()
        if message["type"] == "http.response.body":
            chunks.append(message.get("body", b""))

    scope: Scope = {"type": "http", "method": "POST", "headers": [(b"accept-language", b"ja-JP")]}
    with locale_scope("fr"):
        await tracing.ObservabilityMiddleware(application)(scope, receive, send)
        assert current_locale() == "fr"
    assert current_locale() == "en" and chunks == [b"data: first\n\n", b"data: done\n\n"]
    assert one(spans, "http.request").attributes == {"http.method": "POST", "chat.locale": "ja"}


def test_http_model_tool_persistence_parent_chain(
    chat_client: tuple[TestClient, User, User, DbConfig], provider: Provider,
    monkeypatch: pytest.MonkeyPatch, spans: InMemorySpanExporter,
) -> None:
    client, owner, _outsider, _foreign = chat_client
    factory: sessionmaker[Session] = chat_store.SessionLocal  # type: ignore[attr-defined]  # fixture patch target
    monkeypatch.setattr(get_settings(), "encrypt_key", "0123456789abcdef0123456789abcdef")
    with factory() as session:
        target = DbConfig(user_id=owner.id, name="synthetic", db_type="mysql", host="localhost",
                          port=1, db_name="synthetic", username="fixture", status=1,
                          password_encrypted=encrypt("synthetic-password"))
        session.add(target)
        session.commit()
    monkeypatch.setattr(database_tools, "SessionLocal", factory)
    adapter = Mock()
    adapter.extract_metadata.return_value = metadata(False)
    adapter.execute.return_value = {"success": True, "rowCount": 1, "data": [{"id": 1}], "truncated": False}
    monkeypatch.setattr(database_tools, "get_adapter", lambda _type: adapter)
    provider.replies = [goal_reply([target.id]),
        [frame({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "synthetic-call",
            "function": {"name": "executeSql", "arguments": json.dumps({"db_id": target.id,
                                                        "statement": "SELECT id FROM items"})}}]}}]}),
         frame("[DONE]")],
        [frame({"choices": [{"delta": {"content": "One synthetic item."}}]}), frame("[DONE]")],
    ]
    response = client.post("/api/chat", json={"message": "SYNTHETIC_PROMPT",
        "dbConfigIds": [target.id], "confirmedIntent": "sql_query"}, headers={"Accept-Language": "fr",
        "traceparent": "00-1234567890abcdef1234567890abcdef-1234567890abcdef-01",
        "tracestate": "vendor=SYNTHETIC_CONTEXT_HEADER", "baggage": "token=SYNTHETIC_CONTEXT_HEADER"})
    assert not any(json.loads(line[6:]).get("type") == "error"
                   for line in response.text.splitlines() if line.startswith("data: "))
    assert response.status_code == 200 and '"type": "done"' in response.text
    root, run, graph = (one(spans, name) for name in ("http.request", "chat.run", "chat.graph"))
    assert root.context is not None and run.context is not None and graph.context is not None
    assert run.parent == root.context and graph.parent == run.context
    for item in spans.get_finished_spans():
        if item.name in {"model.call", "tool.call"}:
            assert item.parent == graph.context
        if item.name.startswith("persistence."):
            assert item.parent in (run.context, graph.context)
        assert "SYNTHETIC_PROMPT" not in str(item.attributes) and not item.events
        assert item.context is not None and not item.context.trace_state
    database_spans = [item for item in spans.get_finished_spans() if item.name.startswith("database.")]
    assert {item.name for item in database_spans} == {"database.schema", "database.execute"}
    tool_spans = [item for item in spans.get_finished_spans() if item.name == "tool.call"]
    for item in database_spans:
        assert item.parent in [tool.context for tool in tool_spans]
        assert item.attributes is not None and item.attributes["outcome"] == "done"
    assert adapter.extract_metadata.call_count == adapter.execute.call_count == 1
    assert len(provider.requests) == 3
    assert provider.requests[0]["thinking"] == {"type": "disabled"}
    assert all(request["temperature"] == 0.7 for request in provider.requests[1:])


@pytest.mark.parametrize("locale", ["fr", "ja", None])
def test_publish_to_worker_keeps_locale_and_parent(
    locale: str | None, monkeypatch: pytest.MonkeyPatch, spans: InMemorySpanExporter,
) -> None:
    seen: list[str] = []
    monkeypatch.setattr(worker, "get_settings", lambda: Settings(otlp_endpoint=""))
    monkeypatch.setattr(worker, "verify_and_generate", lambda _id, _version: seen.append(current_locale()))
    headers: dict[str, object] = {} if locale is None else {"locale": locale}
    with tracing.span("queue.publish"):
        tracing.inject_headers(headers)
    task = worker.verify_config
    task.push_request(id=uuid4().hex, headers=headers)
    try:
        with locale_scope("es"):
            task.run(12, 1)
            assert current_locale() == "es"
    finally:
        task.pop_request()
    assert seen == ["en" if locale is None else locale] and current_locale() == "en"
    parent, published = one(spans, "celery.db_config.verify").parent, one(spans, "queue.publish").context
    assert parent is not None and published is not None
    assert (parent.trace_id, parent.span_id) == (published.trace_id, published.span_id)
    assert "sqlchat-locale" not in headers and "sqlchat-user-id" not in headers


def test_exception_has_type_only_and_scope_resets(spans: InMemorySpanExporter) -> None:
    with pytest.raises(RuntimeError), locale_scope("fr"), tracing.span("queue.publish"):
        raise RuntimeError("SYNTHETIC_PRIVATE_BODY")
    record = one(spans, "queue.publish")
    assert record.attributes == {"error.type": "RuntimeError"} and not record.events
    assert current_locale() == "en"


def test_arbitrary_content_attribute_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unsupported telemetry field"), tracing.span(
        "model.call", attributes={"prompt": "SYNTHETIC_PROMPT"},
    ):
        pytest.fail("content attribute must not enter a span")


def test_concurrent_workers_have_separate_locale_and_trace_parents(
    monkeypatch: pytest.MonkeyPatch, spans: InMemorySpanExporter,
) -> None:
    barrier = Barrier(2)
    seen: list[tuple[str, int]] = []
    monkeypatch.setattr(worker, "get_settings", lambda: Settings(otlp_endpoint=""))

    def verify(_id: int, _version: int) -> None:
        barrier.wait(timeout=5)
        seen.append((current_locale(), trace.get_current_span().get_span_context().trace_id))

    monkeypatch.setattr(worker, "verify_and_generate", verify)
    pairs: list[tuple[str, dict[str, object], int]] = []
    for locale in ("fr", "ja"):
        headers: dict[str, object] = {"locale": locale}
        with tracing.span("queue.publish") as parent:
            tracing.inject_headers(headers)
            pairs.append((locale, headers, parent.get_span_context().trace_id))

    def consume(pair: tuple[str, dict[str, object], int]) -> None:
        _locale, headers, _trace_id = pair
        task = worker.verify_config
        task.push_request(id=uuid4().hex, headers=headers)
        try:
            with locale_scope("es"):
                task.run(12, 1)
                assert current_locale() == "es"
        finally:
            task.pop_request()
        assert current_locale() == "en"

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(consume, pairs))
    assert set(seen) == {(locale, trace_id) for locale, _headers, trace_id in pairs}
    records = [record for record in spans.get_finished_spans() if record.name == "celery.db_config.verify"]
    assert len(records) == 2
    for record in records:
        assert record.attributes is not None and record.parent is not None
        assert (record.attributes["chat.locale"], record.parent.trace_id) in set(seen)
    assert current_locale() == "en"


def test_publish_worker_metadata_child_is_a_single_read(
    store: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch, spans: InMemorySpanExporter,
) -> None:
    adapter = Mock()
    adapter.test_connection.return_value = True
    adapter.extract_metadata.return_value = metadata(True)
    monkeypatch.setattr(db_config_worker, "get_adapter", lambda _type: adapter)
    monkeypatch.setattr(worker, "get_settings", lambda: Settings(otlp_endpoint=""))
    carrier: dict[str, object] = {"locale": "ja"}
    with tracing.span("http.request"):
        with tracing.span("queue.publish"):
            tracing.inject_headers(carrier)
        task = worker.verify_config
        task.push_request(id=uuid4().hex, headers=carrier)
        try:
            task.run(12, 1)
        finally:
            task.pop_request()
    parent, schema = one(spans, "celery.db_config.verify"), one(spans, "database.schema")
    assert schema.parent == parent.context and schema.attributes == {"outcome": "partial"}
    assert parent.attributes is not None and parent.attributes["chat.locale"] == "ja"
    assert parent.attributes["outcome"] == "partial"
    adapter.test_connection.assert_called_once()
    adapter.extract_metadata.assert_called_once()
    with store() as session:
        config = session.get(DbConfig, 12)
        assert config is not None and config.status == 1 and config.doc_content is not None
        assert "indexes unavailable" in config.doc_content
    assert current_locale() == "en"
