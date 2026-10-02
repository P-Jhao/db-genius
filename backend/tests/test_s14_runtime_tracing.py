"""Root starts the receiver before Compose; live tests never restart services."""

from __future__ import annotations

import base64
import json
import sys
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock
from time import monotonic, sleep
from typing import Protocol, cast
from urllib.parse import quote, quote_plus, urlsplit
from uuid import uuid4

import httpx
from opentelemetry.proto.collector.trace.v1 import trace_service_pb2
from pydantic import SecretStr
from real_model_database import isolated_database
from test_s14_runtime_support import Runtime, obj, required, safe_live
from test_s14_runtime_trace_schedule import cover_reset_channels

pytest_plugins = ("test_s14_runtime_support",)


class Value(Protocol):
    string_value: str


class Attribute(Protocol):
    key: str
    value: Value


class WireSpan(Protocol):
    name: str
    trace_id: bytes
    span_id: bytes
    parent_span_id: bytes
    trace_state: str
    attributes: Sequence[Attribute]
    events: Sequence[object]
    start_time_unix_nano: int
    end_time_unix_nano: int


class ScopeSpans(Protocol):
    spans: Sequence[WireSpan]


class Resource(Protocol):
    attributes: Sequence[Attribute]


class ResourceSpans(Protocol):
    scope_spans: Sequence[ScopeSpans]
    resource: Resource


class Packet(Protocol):
    resource_spans: Sequence[ResourceSpans]
    def ParseFromString(self, data: bytes) -> int: ...


@dataclass(repr=False)
class Record:
    channel: int
    span: WireSpan = field(repr=False)
    resource: dict[str, str] = field(repr=False)


def attributes(span: WireSpan) -> dict[str, str]:
    return {a.key: a.value.string_value for a in span.attributes}


class Capture(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, host: str, port: int) -> None:
        super().__init__((host, port), Handler)
        self.frames: list[tuple[int, bytes]] = []
        self.lock = Lock()
        self.channels = 0
        self.key = SecretStr(required("SQLCHAT_S14_RUNTIME_CAPTURE_KEY"))

    def __repr__(self) -> str:
        return "<OTLP capture protected>"


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def setup(self) -> None:
        super().setup()
        server = cast(Capture, self.server)
        with server.lock:
            self.channel = server.channels
            server.channels += 1

    def respond(self, code: int, packet: object) -> None:
        body = json.dumps(packet).encode()
        self.send_response(code)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        server = cast(Capture, self.server)
        size = int(self.headers.get("Content-Length", "0"))
        if self.path != "/v1/traces" or not 0 < size <= 4_000_000:
            self.respond(400, {"accepted": False})
            return
        payload = self.rfile.read(size)
        with server.lock:
            if len(server.frames) >= 1000:
                self.respond(503, {"accepted": False})
                return
            server.frames.append((self.channel, payload))
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.send_header("Content-Type", "application/x-protobuf")
        self.end_headers()

    def do_GET(self) -> None:
        server = cast(Capture, self.server)
        if self.path == "/health":
            self.respond(200, {"ready": True})
            return
        if self.path != "/_s14_capture" or self.headers.get("Authorization") != "Bearer " + server.key.get_secret_value():
            self.respond(403, {"allowed": False})
            return
        with server.lock:
            frames = [(channel, base64.b64encode(body).decode()) for channel, body in server.frames]
        self.respond(200, {"frames": frames})

    def log_message(self, _format: str, *_args: object) -> None:
        return None


def endpoint() -> tuple[str, int]:
    parsed = urlsplit(required("SQLCHAT_S14_RUNTIME_OTLP_EXPORT_URL"))
    host = required("SQLCHAT_S14_RUNTIME_OTLP_BIND")
    if parsed.scheme != "http" or parsed.hostname not in {"host.docker.internal", "localhost", "127.0.0.1"} or \
            parsed.port is None or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path:
        raise ValueError("Root must inject a temporary local OTLP HTTP base URL/port")
    if host not in {"0.0.0.0", "127.0.0.1"}:
        raise ValueError("Root must choose an explicit local receiver bind")
    return host, parsed.port


def snapshot() -> tuple[list[Record], bytes]:
    _, port = endpoint()
    with httpx.Client(trust_env=False, timeout=10) as client:
        response = client.get(f"http://127.0.0.1:{port}/_s14_capture", headers={
            "Authorization": "Bearer " + required("SQLCHAT_S14_RUNTIME_CAPTURE_KEY")})
    if response.status_code != 200:
        raise RuntimeError("Root-started receiver unavailable")
    frames = obj(response.json()).get("frames")
    if not isinstance(frames, list):
        raise TypeError("Receiver frames must be a list")
    records: list[Record] = []
    bodies: list[bytes] = []
    for frame in frames:
        if not isinstance(frame, list) or len(frame) != 2 or type(frame[0]) is not int or not isinstance(frame[1], str):
            raise TypeError("Invalid receiver frame")
        body = base64.b64decode(frame[1], validate=True)
        bodies.append(body)
        packet = cast(Packet, trace_service_pb2.ExportTraceServiceRequest())
        packet.ParseFromString(body)
        for resource in packet.resource_spans:
            attrs = {a.key: a.value.string_value for a in resource.resource.attributes}
            records.extend(Record(frame[0], span, attrs) for scope in resource.scope_spans for span in scope.spans)
    return records, b"".join(bodies)


def trace_headers(secret: str) -> tuple[bytes, dict[str, str]]:
    identifier, parent = uuid4().hex, uuid4().hex[:16]
    return bytes.fromhex(identifier), {"traceparent": f"00-{identifier}-{parent}-01",
                                      "tracestate": "vendor=" + quote(secret, safe=""),
                                      "baggage": "private=" + quote_plus(secret)}


def chain(records: list[Record], identifier: bytes) -> Record | None:
    own = {r.span.name: r for r in records if r.span.trace_id == identifier}
    if not {"http.request", "queue.publish", "celery.db_config.verify", "database.schema"}.issubset(own):
        return None
    request, publish, worker, schema = (own[name].span for name in
                                       ("http.request", "queue.publish", "celery.db_config.verify", "database.schema"))
    assert publish.parent_span_id == request.span_id
    assert worker.parent_span_id == publish.span_id
    assert schema.parent_span_id == worker.span_id
    return own["celery.db_config.verify"]


@safe_live
def test_real_http_worker_parent_chain_and_locale_reset(runtime: Runtime) -> None:
    endpoint()
    script = ("import json,sys; from app.core.config import get_settings; from requests.utils import get_environ_proxies; "
              "s=get_settings(); print(json.dumps({'configured':s.otlp_endpoint==sys.argv[1],"
              "'sample_all':s.otlp_sample_rate==1,'direct':not bool(get_environ_proxies(s.otlp_endpoint))}))")
    for container in (runtime.session.container, runtime.worker):
        packet = obj(json.loads(runtime.deploy.runtime_script(container, script,
                                 required("SQLCHAT_S14_RUNTIME_OTLP_EXPORT_URL"))))
        assert packet == {"configured": True, "sample_all": True, "direct": True}
    snapshot()  # receiver must already be running; no spawn/restart in this test
    sentinel = "SYNTHETIC_S14_UNTRUSTED_TRACE+/ VALUE"
    pairs = [trace_headers(sentinel) for _ in range(2)]
    with isolated_database("postgresql", "test") as target:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(runtime.create, target, locale, headers=headers)
                       for locale, (_, headers) in zip(("fr", "ja"), pairs, strict=True)]
            identifiers = [future.result() for future in futures]
        assert all(runtime.completed(identifier).status == 1 for identifier in identifiers)
        deadline = monotonic() + 60
        localized: list[Record] = []
        while len(localized) != 2:
            records, _ = snapshot()
            localized = [worker for identifier, _ in pairs if (worker := chain(records, identifier)) is not None]
            if monotonic() >= deadline:
                raise TimeoutError("Actual parent chain was not exported")
            sleep(0.2)
        for record, locale in zip(localized, ("fr", "ja"), strict=True):
            assert attributes(record.span).get("chat.locale") == locale
            assert record.resource == {"service.name": "sqlchat-worker"}
        reset = cover_reset_channels(runtime, identifiers, localized, sentinel, snapshot, attributes, trace_headers)
        records, payload = reset.records, reset.payload
        default_ids, reset_channels = reset.default_ids, reset.reset_channels
        own_ids = {identifier for identifier, _ in pairs} | default_ids
        selected = [r for r in records if r.span.trace_id in own_ids]
        assert all(r.span.trace_state == "" and not r.span.events for r in selected)
        assert runtime.absent(payload, target.password, SecretStr(required("SQLCHAT_S14_RUNTIME_CAPTURE_KEY")))
        assert all(value.encode() not in payload for value in (sentinel, quote(sentinel, safe=""), quote_plus(sentinel)))
        runtime.report("worker_trace_locale", {"passed": True, "final_image_checked": True,
                       "real_http_parent_chains": 2, "fr_ja_concurrent_headers": True,
                       "old_no_locale_callbacks": reset.callbacks, "default_publish_waves": reset.waves,
                        "same_export_channel_reset_count": len(reset_channels),
                       "direct_otlp_transport": True, "default_locale_en": True,
                       "untrusted_state_absent": True, "credentials_absent": True})


if __name__ == "__main__":
    if sys.argv[1:] != ["--collector"]:
        raise SystemExit("Only explicit --collector mode is supported")
    server = Capture(*endpoint())
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
