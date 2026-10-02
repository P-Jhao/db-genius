"""Content-free spans, complete ASGI lifetime, and W3C task propagation."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, MutableMapping
from contextlib import contextmanager
from threading import Lock

from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
from opentelemetry.trace import Span, Status, StatusCode
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import Settings
from app.core.request_locale import current_locale, locale_scope

_lock = Lock()
_propagator = TraceContextTextMapPropagator()
_provider: TracerProvider | None = None
_NAMES = frozenset({"http.request", "chat.run", "chat.graph", "model.call", "tool.call", "database.schema",
                    "database.execute", "queue.publish", "celery.db_config.verify",
                    "persistence.prepare", "persistence.save", "persistence.set_intent", "persistence.finalize"})
_ATTRIBUTES = frozenset({"http.method", "chat.locale", "model.step", "tool.name", "outcome"})


def configure_tracing(settings: Settings, *, service_name: str) -> None:
    global _provider
    if not settings.otlp_endpoint:
        return
    with _lock:
        if _provider is not None:
            return
        provider = TracerProvider(resource=Resource({"service.name": service_name}),
                                  sampler=ParentBased(TraceIdRatioBased(settings.otlp_sample_rate)),
                                  shutdown_on_exit=False)
        exporter = OTLPSpanExporter(endpoint=f"{settings.otlp_endpoint}/v1/traces", timeout=3)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        _provider = provider


def flush_tracing() -> bool:
    """Best effort, bounded wait; telemetry must never extend business shutdown."""
    return _provider is None or _provider.force_flush(timeout_millis=1000)


@contextmanager
def span(name: str, *, task_id: str | None = None,
         attributes: Mapping[str, str | int | float | bool] | None = None,
         parent: Context | None = None) -> Iterator[Span]:
    if name not in _NAMES or (attributes is not None and not set(attributes).issubset(_ATTRIBUTES)):
        raise ValueError("Unsupported telemetry field")
    with trace.get_tracer("sqlchat").start_as_current_span(
        name, context=parent, record_exception=False, set_status_on_exception=False,
    ) as current:
        if task_id is not None:
            current.set_attribute("sqlchat.task_id", task_id)
        for key, value in ({} if attributes is None else attributes).items():
            current.set_attribute(key, value)
        try:
            yield current
        except BaseException as error:
            current.set_attribute("error.type", type(error).__name__)
            current.set_status(Status(StatusCode.ERROR))
            raise


def inject_headers(headers: MutableMapping[str, object]) -> None:
    for key in list(headers):
        if key.lower() in {"tracestate", "baggage"}:
            del headers[key]
    carrier: dict[str, str] = {}
    _propagator.inject(carrier)
    if "traceparent" in carrier:
        headers["traceparent"] = carrier["traceparent"]


def extract_headers(headers: Mapping[str, object]) -> Context:
    value = headers.get("traceparent")
    carrier = {"traceparent": value} if isinstance(value, str) else {}
    return _propagator.extract(carrier, context=Context())


class ObservabilityMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {key.decode("latin-1"): value.decode("latin-1") for key, value in scope["headers"]}
        with locale_scope(headers.get("accept-language")), span(
            "http.request", attributes={"http.method": scope["method"], "chat.locale": current_locale()},
            parent=extract_headers(headers),
        ):
            await self.app(scope, receive, send)


def verification_outcome(outcome: str, *, error_type: str | None = None) -> None:
    current = trace.get_current_span()
    current.set_attribute("outcome", outcome)
    if error_type is not None:
        current.set_attribute("error.type", error_type)
    if outcome == "error":
        current.set_status(Status(StatusCode.ERROR))
