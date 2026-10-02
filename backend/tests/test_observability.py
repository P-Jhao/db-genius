"""S14 health, redaction, metrics, propagation, and SSE idle behavior."""

from __future__ import annotations

import asyncio
import io
import logging
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Self, cast
from unittest.mock import Mock

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags
from pydantic import SecretStr, ValidationError
from sqlalchemy import create_engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from starlette.types import Message, Scope

from app.agent.types import ChatRequest, Usage
from app.api import chat, system
from app.core.config import Settings
from app.core.observability_health import broker_ready, migration_ready, readiness
from app.core.observability_logging import SafeLogFilter
from app.core.observability_metrics import REGISTRY, metrics_text, model_call, run_finished, tool_call
from app.core.observability_runtime import ObservedModelStream
from app.core.observability_tracing import inject_headers
from app.core.request_locale import current_locale, locale_scope
from app.main import app
from app.models import User
from app.services import model_config
from app.tasks.celery_app import propagate_task_context


def test_health_contract_and_failure_is_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    client = TestClient(app)
    original = client.get("/api/health")
    assert original.status_code == 200
    assert original.json()["code"] == 200
    assert original.json()["data"]["status"] == "UP"
    assert client.get("/api/health/live").json() == {
        "code": 200, "message": "success", "data": {"status": "UP"}}
    monkeypatch.setattr(system, "readiness", lambda _settings: {"database": "UP", "broker": "UP"})
    ready = client.get("/api/health/ready")
    assert ready.status_code == 200 and ready.json()["data"]["checks"] == {
        "database": "UP", "broker": "UP"}
    monkeypatch.setattr(system, "readiness", lambda _settings: {"database": "DOWN", "broker": "UP"})
    failed = client.get("/api/health/ready")
    assert failed.status_code == 503 and failed.json()["code"] == 503
    assert failed.json()["data"] == {"status": "DOWN", "checks": {"database": "DOWN", "broker": "UP"}}
    assert "password" not in failed.text and "localhost" not in failed.text
    metrics = client.get("/api/metrics")
    assert metrics.status_code == 200
    assert "text/plain" in metrics.headers["content-type"]
    alias = client.get("/metrics")
    assert alias.headers["content-type"] == metrics.headers["content-type"]
    assert alias.content == metrics.content


def test_migration_requires_current_alembic_head(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from app.core import observability_health

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'migration.sqlite'}")
    monkeypatch.setattr(observability_health, "probe_engine", lambda _settings: engine)
    try:
        assert not migration_ready()
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
            connection.exec_driver_sql("INSERT INTO alembic_version VALUES ('old_revision')")
        assert not migration_ready()
        with engine.begin() as connection:
            connection.exec_driver_sql("UPDATE alembic_version SET version_num = '0001_initial'")
        assert migration_ready()
    finally:
        engine.dispose()


def test_broker_probe_uses_timeout_and_reports_independent_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import observability_health

    class BrokenBroker:
        def __init__(self, _url: str, *, connect_timeout: float, transport_options: dict[str, float]) -> None:
            assert connect_timeout == 0.25
            assert transport_options == {"read_timeout": 0.25, "write_timeout": 0.25}

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def ensure_connection(self, *, max_retries: int, timeout: float) -> None:
            assert max_retries == 0 and timeout == 0.25
            raise TimeoutError("secret-broker-url")

    settings = Settings(ready_broker_timeout_seconds=0.25)
    monkeypatch.setattr(observability_health, "Connection", BrokenBroker)
    monkeypatch.setattr(observability_health, "migration_ready", lambda _settings: True)
    with pytest.raises(TimeoutError):
        broker_ready(settings)
    assert readiness(settings) == {"database": "UP", "broker": "DOWN"}


def test_database_probe_limits_connect_pool_and_query(monkeypatch: pytest.MonkeyPatch) -> None:
    from sqlalchemy.pool import NullPool

    from app.core import observability_health

    engine = object()
    factory = Mock(return_value=engine)
    monkeypatch.setattr(observability_health, "create_engine", factory)
    settings = Settings(database_url="postgresql+psycopg://dummy:dummy@127.0.0.1:5432/db",
                        ready_database_timeout_seconds=4)
    assert observability_health.probe_engine(settings) is engine
    kwargs = factory.call_args.kwargs
    assert kwargs["poolclass"] is NullPool
    assert kwargs["connect_args"]["connect_timeout"] == 4
    assert "statement_timeout=4000" in kwargs["connect_args"]["options"]
    assert "lock_timeout=4000" in kwargs["connect_args"]["options"]
    observability_health.probe_engine(Settings(database_url="sqlite:///isolated-test.sqlite",
                                               ready_database_timeout_seconds=4))
    sqlite_kwargs = factory.call_args.kwargs
    assert sqlite_kwargs["poolclass"] is NullPool
    assert sqlite_kwargs["connect_args"]["timeout"] == 4.0


def test_content_collection_and_credentialed_otlp_are_rejected() -> None:
    with pytest.raises(ValidationError, match="Content collection is not supported"):
        Settings(observe_content=True)
    with pytest.raises(ValidationError, match="without credentials"):
        Settings(otlp_endpoint="https://user:secret@example.test")


def test_log_filter_drops_exception_payload_and_known_secrets() -> None:
    sentinel = "S14_PRIVATE_SENTINEL"
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    configured = Settings()
    configured.default_model_api_key = sentinel
    handler.addFilter(SafeLogFilter(configured))
    logger = logging.getLogger("s14.redaction.test")
    logger.addHandler(handler)
    logger.setLevel(logging.ERROR)
    logger.propagate = False
    try:
        failure = DBAPIError("SELECT :secret", {"secret": sentinel}, RuntimeError(sentinel))
        logger.error("Database failed: %s", failure)
        logger.error("provider api_key=%s", sentinel)
        logger.error("[SQL: SELECT '%s'] [parameters: ('%s',)]", sentinel, sentinel)
    finally:
        logger.removeHandler(handler)
    content = output.getvalue()
    assert sentinel not in content
    assert "SELECT" not in content
    assert "DBAPIError" in content


def test_metrics_have_fixed_labels_and_do_not_expose_task_ids() -> None:
    sentinel = "s14-task-unique-private-id"
    run_finished(sentinel, 0.2)
    tool_call(sentinel, "done")
    before = REGISTRY.get_sample_value("sqlchat_model_tokens_total", {"kind": "prompt"})
    model_call("done", 0, 0)
    payload, content_type = metrics_text()
    text = payload.decode()
    assert "text/plain" in content_type
    assert sentinel not in text
    assert 'sqlchat_chat_runs_total{outcome="other"}' in text
    assert 'sqlchat_tool_calls_total{outcome="done",tool="other"}' in text
    assert REGISTRY.get_sample_value("sqlchat_model_tokens_total", {"kind": "prompt"}) == before


@pytest.mark.asyncio
async def test_model_metrics_count_calls_and_only_reported_tokens() -> None:
    from langchain_core.messages import HumanMessage
    from test_model_protocol import Provider, frame, model

    provider = Provider([
        [frame({"choices": [{"delta": {"content": "first"}}]}), frame("[DONE]")],
        [frame({"choices": [{"delta": {"content": "second"}}]}),
         frame({"choices": [], "usage": {"prompt_tokens": 4, "completion_tokens": 2,
                                           "total_tokens": 6}}), frame("[DONE]")],
    ])
    thread = threading.Thread(target=provider.serve_forever, daemon=True)
    thread.start()
    calls_before = REGISTRY.get_sample_value("sqlchat_model_calls_total", {"outcome": "done"}) or 0
    prompt_before = REGISTRY.get_sample_value("sqlchat_model_tokens_total", {"kind": "prompt"}) or 0
    completion_before = REGISTRY.get_sample_value("sqlchat_model_tokens_total", {"kind": "completion"}) or 0

    async def emit(_kind: str, _content: object, _step: int) -> None:
        return None

    try:
        stream = ObservedModelStream(model(provider), emit, Usage(), task_id="opaque-task")
        assert (await stream.call([HumanMessage(content="test")])).content == "first"
        assert (await stream.call([HumanMessage(content="test")])).content == "second"
    finally:
        provider.shutdown()
        provider.server_close()
        thread.join(timeout=2)
    assert REGISTRY.get_sample_value("sqlchat_model_calls_total", {"outcome": "done"}) == calls_before + 2
    assert REGISTRY.get_sample_value("sqlchat_model_tokens_total", {"kind": "prompt"}) == prompt_before + 4
    assert REGISTRY.get_sample_value("sqlchat_model_tokens_total", {"kind": "completion"}) == \
        completion_before + 2


def test_celery_headers_carry_trace_user_and_locale_without_secret() -> None:
    context = SpanContext(trace_id=0x123456789ABCDEF0123456789ABCDEF0,
                          span_id=0x123456789ABCDEF0, is_remote=False,
                          trace_flags=TraceFlags(TraceFlags.SAMPLED))
    token = otel_context.attach(trace.set_span_in_context(NonRecordingSpan(context)))
    try:
        with locale_scope("zh-CN"):
            headers: dict[str, object] = {"locale": current_locale()}
            propagate_task_context(sender="sqlchat.db_config.verify", headers=headers)
    finally:
        otel_context.detach(token)
    assert str(headers["traceparent"]).startswith("00-123456789abcdef0123456789abcdef0-")
    assert headers["locale"] == "zh-CN"
    assert "sqlchat-locale" not in headers and current_locale() == "en"
    assert "password" not in str(headers)
    unselected: dict[str, object] = {}
    inject_headers(unselected)
    assert "sqlchat-user-id" not in unselected


@pytest.mark.asyncio
async def test_idle_sse_comment_keeps_connection_and_disconnect_cancels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope: Scope = {"type": "http", "method": "POST", "path": "/api/chat", "headers": [],
                    "query_string": b"", "http_version": "1.1", "scheme": "http",
                    "server": ("localhost", 80), "client": ("localhost", 12345), "root_path": ""}
    disconnected = asyncio.Event()
    cancelled = asyncio.Event()
    first_receive = True
    chunks: list[bytes] = []

    async def receive() -> Message:
        nonlocal first_receive
        if first_receive:
            first_receive = False
            return {"type": "http.request", "body": b"", "more_body": False}
        await disconnected.wait()
        return {"type": "http.disconnect"}

    async def send(message: Message) -> None:
        if message["type"] == "http.response.body" and message.get("body"):
            chunk = cast(bytes, message["body"])
            chunks.append(chunk)
            if chunk.startswith(b": keepalive"):
                disconnected.set()

    async def fake_produce(queue: asyncio.Queue[bytes | None], _user_id: int, _body: ChatRequest,
                           _history: list[object], _locale: str, _model: object,
                           _context_window: int | None, cancel_event: threading.Event) -> None:
        while not cancel_event.is_set():
            await asyncio.sleep(0.01)
        cancelled.set()
        await queue.put(None)

    monkeypatch.setattr(chat, "_produce", fake_produce)
    monkeypatch.setattr(chat, "get_settings", lambda: SimpleNamespace(sse_keepalive_seconds=0.02))
    monkeypatch.setattr(model_config, "resolve_active_model", lambda _session, _user_id: SimpleNamespace(
        base_url="http://localhost:1", api_key=SecretStr("local-test"), model_name="test",
        context_window=None,
    ))
    request = Request(scope, receive)
    user = User(id=1, username="owner", password_hash="unused", status=1)
    response = await chat.chat(ChatRequest.model_validate({"message": "hello"}), request,
                               user, cast(Session, object()))
    await asyncio.wait_for(response(scope, receive, send), timeout=2)
    await asyncio.wait_for(cancelled.wait(), timeout=2)
    assert chunks == [b": keepalive\n\n"]
