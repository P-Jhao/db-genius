"""OTLP export uses bounded attributes and never serializes exception content."""

import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import cast
from urllib.parse import quote, quote_plus

import pytest
from opentelemetry import trace
from opentelemetry.proto.collector.trace.v1 import trace_service_pb2
from opentelemetry.sdk.trace import TracerProvider

from app.core import observability_tracing
from app.core.config import Settings
from app.tasks import db_config as worker


class Collector(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self) -> None:
        self.received: list[tuple[str, bytes]] = []
        super().__init__(("127.0.0.1", 0), Handler)


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        server = self.server
        assert isinstance(server, Collector)
        body = self.rfile.read(int(self.headers["Content-Length"]))
        server.received.append((self.path, body))
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, _format: str, *_args: object) -> None:
        return None


@pytest.fixture
def collector() -> Iterator[Collector]:
    server = Collector()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def test_http_otlp_export_contains_task_id_but_no_exception_body(
    collector: Collector, monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[TracerProvider] = []
    monkeypatch.setattr(observability_tracing, "_provider", None)
    monkeypatch.setattr(trace, "set_tracer_provider", captured.append)
    host, port = cast(tuple[str, int], collector.server_address)
    settings = Settings(otlp_endpoint=f"http://{host}:{port}", otlp_sample_rate=1)
    observability_tracing.configure_tracing(settings, service_name="sqlchat-test")
    assert len(captured) == 1
    provider = captured[0]
    monkeypatch.setattr(trace, "get_tracer", provider.get_tracer)
    secret = "S14_TRACE_SECRET_SENTINEL"
    try:
        with pytest.raises(RuntimeError, match=secret), observability_tracing.span(
            "chat.run", task_id="task-123", attributes={"chat.locale": "en"},
        ):
            raise RuntimeError(secret)
        assert provider.force_flush(timeout_millis=5000)
        assert len(collector.received) == 1
        path, body = collector.received[0]
        assert path == "/v1/traces"
        assert b"chat.run" in body and b"task-123" in body
        assert secret.encode() not in body
    finally:
        provider.shutdown()


@pytest.mark.parametrize("encoding", ["raw", "percent", "plus"])
def test_http_publish_worker_otlp_never_exports_untrusted_state_or_baggage(
    collector: Collector, monkeypatch: pytest.MonkeyPatch, encoding: str,
) -> None:
    secret = "SYNTHETIC_TRACE_SECRET+/ VALUE"
    variant = {"raw": secret, "percent": quote(secret, safe=""), "plus": quote_plus(secret)}[encoding]
    captured: list[TracerProvider] = []
    monkeypatch.setattr(observability_tracing, "_provider", None)
    monkeypatch.setattr(trace, "set_tracer_provider", captured.append)
    monkeypatch.setenv("OTEL_RESOURCE_ATTRIBUTES", "private=" + variant)
    host, port = cast(tuple[str, int], collector.server_address)
    observability_tracing.configure_tracing(Settings(otlp_endpoint=f"http://{host}:{port}", otlp_sample_rate=1),
                                             service_name="sqlchat-test")
    provider = captured[0]
    monkeypatch.setattr(trace, "get_tracer", provider.get_tracer)
    monkeypatch.setattr(worker, "get_settings", lambda: Settings(otlp_endpoint=""))
    monkeypatch.setattr(worker, "verify_and_generate", lambda _id, _version: None)
    parent = "00-1234567890abcdef1234567890abcdef-1234567890abcdef-01"
    headers = {"traceparent": parent, "tracestate": "vendor=" + variant, "baggage": "secret=" + variant}
    carrier: dict[str, object] = {"locale": "fr", "TraceState": variant, "Baggage": variant}
    task = worker.verify_config
    try:
        with observability_tracing.span("http.request", parent=observability_tracing.extract_headers(headers)):
            with observability_tracing.span("queue.publish"):
                observability_tracing.inject_headers(carrier)
            assert set(carrier) == {"traceparent", "locale"}
            task.push_request(id="synthetic-task", headers=carrier)
            try:
                task.run(12, 1)
            finally:
                task.pop_request()
        assert provider.force_flush(timeout_millis=5000)
        assert len(collector.received) == 1
        body = collector.received[0][1]
        assert all(value.encode() not in body for value in (secret, quote(secret, safe=""), quote_plus(secret)))
        decoded = trace_service_pb2.ExportTraceServiceRequest()
        decoded.ParseFromString(body)
        records = {item.name: item for resource in decoded.resource_spans
                   for scope in resource.scope_spans for item in scope.spans}
        assert set(records) == {"http.request", "queue.publish", "celery.db_config.verify"}
        assert records["queue.publish"].parent_span_id == records["http.request"].span_id
        assert records["celery.db_config.verify"].parent_span_id == records["queue.publish"].span_id
        for record in records.values():
            assert record.trace_id == bytes.fromhex("1234567890abcdef1234567890abcdef")
            assert record.trace_state == "" and not record.events
    finally:
        provider.shutdown()
