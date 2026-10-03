"""Authenticated byte-preserving provider relay with credential-free numeric evidence."""

from __future__ import annotations

import hashlib
import json
import math
import re
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from time import monotonic
from typing import cast

import httpx
from pydantic import SecretStr
from real_model_cases import MODEL
from real_model_observations import ProviderTextObserver, record_finish_reason
from real_model_relay_body import request_body


def object_value(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise TypeError("Expected a JSON object")
    return cast(dict[str, object], value)


def generation_parameters(request: dict[str, object]) -> dict[str, object]:
    result: dict[str, object] = {"model": MODEL}
    for key in ("temperature", "top_p", "max_tokens", "max_completion_tokens", "frequency_penalty", "presence_penalty", "seed"):
        value = request.get(key)
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))):
            raise TypeError("Generation controls must be numeric")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("Generation controls must be finite")
        result[key] = value
    thinking = request.get("thinking")
    if thinking is not None:
        thinking = object_value(thinking)
        if set(thinking) != {"type"} or thinking["type"] not in {"enabled", "disabled"}:
            raise ValueError("Unsupported thinking controls")
    result["thinking"] = thinking
    effort = request.get("reasoning_effort")
    if effort is not None and effort not in {"none", "minimal", "low", "medium", "high", "xhigh"}:
        raise ValueError("Unsupported reasoning effort")
    result["reasoning_effort"] = effort
    raw_format = request.get("response_format")
    if raw_format is None:
        result["response_format"] = None
    else:
        raw_format = object_value(raw_format)
        if raw_format.get("type") not in {"text", "json_object", "json_schema"}:
            raise ValueError("Unsupported structured response format")
        result["response_format"] = {"type": raw_format["type"]}
        if raw_format["type"] == "json_schema":
            result["response_format"] = {"type": "json_schema", "schemaSha256": hashlib.sha256(
                json.dumps(raw_format.get("json_schema"), sort_keys=True).encode()).hexdigest()}
    return result


class RealProviderRelay(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, key: SecretStr, upstream: str = "https://api.deepseek.com", *,
                 capture_synthetic: bool = False) -> None:
        if not key.get_secret_value():
            raise ValueError("The actual provider key is required")
        self.upstream_key = key
        self.access_key = SecretStr(secrets.token_urlsafe(32))
        self.upstream = upstream.rstrip("/")
        self.capture_synthetic = capture_synthetic
        self.records: list[dict[str, object]] = []
        self.requests: list[dict[str, object]] = []
        self.label = "unassigned"
        self.lock = threading.Lock()
        super().__init__(("0.0.0.0", 0), RelayHandler)

    def begin(self, label: str) -> int:
        with self.lock:
            self.label = label
            return len(self.records)

    def evidence(self, offset: int) -> list[dict[str, object]]:
        with self.lock:
            return [dict(record) for record in self.records[offset:]]

    def request_evidence(self, label: str, variant: str) -> list[dict[str, object]]:
        with self.lock:
            return [dict(record) for record in self.requests
                    if record["label"] == label and record["variant"] == variant]


def _usage(packet: dict[str, object], report: dict[str, object]) -> None:
    raw = packet.get("usage")
    if raw is not None:
        value = object_value(raw)
        totals = {}
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            count = value.get(key)
            if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                raise TypeError("Provider usage must contain nonnegative integers")
            totals[key] = count
        report["usage"] = totals


def _packet(data: bytes, report: dict[str, object], started: float,
            observer: ProviderTextObserver | None = None) -> None:
    lines = [line[5:].removeprefix(" ") for line in data.decode("utf-8").splitlines()
             if line.startswith("data:")]
    if not lines:
        return
    content = "\n".join(lines).strip()
    if content == "[DONE]":
        report["providerDone"] = True
        return
    packet = object_value(json.loads(content))
    _usage(packet, report)
    choices = packet.get("choices")
    if isinstance(choices, list):
        for index, choice in enumerate(choices):
            record_finish_reason(object_value(choice), report)
            if index == 0 and observer is not None:
                observer.consume(object_value(choice))
            raw_delta = object_value(choice).get("delta", {})
            if raw_delta is None:
                raw_delta = {}
            delta = object_value(raw_delta)
            if report["firstDeltaSeconds"] is None and any(
                delta.get(key) for key in ("content", "reasoning_content", "tool_calls")
            ):
                report["firstDeltaSeconds"] = monotonic() - started


def consume_frames(pending: bytes, part: bytes, report: dict[str, object], started: float,
                   observer: ProviderTextObserver | None = None) -> bytes:
    pending += part
    # Match only after joining raw chunks: neither UTF-8 nor CRLF is chunk-aligned.
    while delimiter := re.search(rb"\r\n\r\n|\n\n|\r\r", pending):
        packet, pending = pending[:delimiter.start()], pending[delimiter.end():]
        try:
            _packet(packet, report, started, observer)
        except (UnicodeDecodeError, ValueError, TypeError) as error:
            # Evidence parsing must never rewrite or interrupt the actual response.
            report["evidenceError"] = type(error).__name__
    return pending


class RelayHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    observation: dict[str, object] | None = None

    def send_response(self, code: int, message: str | None = None) -> None:
        if self.observation is not None:
            self.observation["httpStatus"] = code
        super().send_response(code, message)

    def _route(self) -> tuple[RealProviderRelay, str, str] | None:
        server = self.server
        assert isinstance(server, RealProviderRelay)
        pieces = self.path.split("/", 2)
        valid = len(pieces) == 3 and pieces[1] in {"python", "java"}
        path = "/" + pieces[2] if valid else None
        self.observation = {"method": self.command, "variant": pieces[1] if valid else "unknown",
                            "path": path if path in {"/models", "/v1/models", "/chat/completions", "/v1/chat/completions"}
                            else "unknown", "label": server.label, "bodyBytes": None, "httpStatus": None,
                            "authorizationPresent": self.headers.get("Authorization") is not None,
                            "contentLengthPresent": self.headers.get("Content-Length") is not None,
                            "transferEncodingPresent": self.headers.get("Transfer-Encoding") is not None}
        with server.lock:
            server.requests.append(self.observation)
        if self.headers.get("Authorization") != "Bearer " + server.access_key.get_secret_value():
            self.send_error(401, "Relay authentication required")
            return None
        if not valid:
            self.send_error(404, "Unknown acceptance route")
            return None
        return server, pieces[1], "/" + pieces[2]

    def do_GET(self) -> None:
        route = self._route()
        if route is None:
            return
        server, _variant, path = route
        if path not in {"/models", "/v1/models"}:
            self.send_error(404, "Unknown acceptance endpoint")
            return
        with httpx.Client(timeout=30) as client:
            response = client.get(server.upstream + path, headers={
                "Authorization": "Bearer " + server.upstream_key.get_secret_value(),
            })
        self.send_response(response.status_code)
        self.send_header("Content-Type", response.headers.get("content-type", "application/json"))
        self.send_header("Content-Length", str(len(response.content)))
        self.end_headers()
        self.wfile.write(response.content)

    def do_POST(self) -> None:
        route = self._route()
        if route is None:
            return
        server, variant, path = route
        if path not in {"/chat/completions", "/v1/chat/completions"}:
            self.send_error(404, "Unknown acceptance endpoint")
            return
        try:
            body = request_body(self.rfile, self.headers.get("Content-Length"), self.headers.get("Transfer-Encoding"))
            if self.observation is None:
                raise RuntimeError("Acceptance request observation is missing")
            self.observation["bodyBytes"] = len(body)
            request = object_value(json.loads(body))
            if request.get("model") != MODEL:
                raise ValueError("Fixed acceptance model differs")
            # Capture only explicit generation controls, never messages/tools/headers.
            parameters = generation_parameters(request)
        except (ValueError, TypeError):
            self.send_error(400, "Invalid acceptance request controls")
            return
        started = monotonic()
        report: dict[str, object] = {
            "variant": variant, "label": server.label, "parameters": parameters,
            "stream": request.get("stream") is True, "usage": None, "providerDone": False,
            "firstDeltaSeconds": None, "elapsedSeconds": None, "httpStatus": None, "transportError": None,
            "evidenceError": None,
            "finishReason": None, "finishReasonPresent": False,
        }
        text_observer = ProviderTextObserver(request)
        if server.capture_synthetic:
            from real_model_metadata_evidence import metadata_inputs
            from real_model_synthetic_evidence import executed_tools

            report["syntheticMetadataInputs"] = metadata_inputs(
                request, (server.upstream_key.get_secret_value(), server.access_key.get_secret_value()),
            )
            try:
                report["syntheticExecutedTools"] = executed_tools(
                    request, (server.upstream_key.get_secret_value(), server.access_key.get_secret_value()),
                )
            except (ValueError, TypeError) as error:
                report["evidenceError"] = type(error).__name__
        with server.lock:
            server.records.append(report)
        try:
            with (
                httpx.Client(timeout=httpx.Timeout(240, connect=20)) as client,
                client.stream("POST", server.upstream + path, content=body, headers={
                    "Authorization": "Bearer " + server.upstream_key.get_secret_value(),
                    "Content-Type": "application/json",
                    "Accept-Encoding": "identity",
                }) as upstream,
            ):
                report["httpStatus"] = upstream.status_code
                self.send_response(upstream.status_code)
                self.send_header("Content-Type", upstream.headers.get("content-type", "application/json"))
                encoding = upstream.headers.get("content-encoding")
                if encoding is not None:
                    self.send_header("Content-Encoding", encoding)
                self.send_header("Connection", "close")
                self.end_headers()
                if request.get("stream") is not True or upstream.status_code >= 400:
                    content = b"".join(upstream.iter_raw())
                    self.wfile.write(content)
                    self.wfile.flush()
                    if encoding is not None:
                        report["evidenceError"] = "UnsupportedContentEncoding"
                    elif upstream.status_code < 400:
                        _usage(object_value(json.loads(content)), report)
                        report["providerDone"] = True
                else:
                    pending = b""
                    for part in upstream.iter_raw():
                        self.wfile.write(part)
                        self.wfile.flush()
                        if encoding is not None:
                            report["evidenceError"] = "UnsupportedContentEncoding"
                            continue
                        if report["evidenceError"] == "FrameLimitExceeded":
                            continue
                        pending = consume_frames(pending, part, report, started, text_observer)
                        if len(pending) > 4 * 1024 * 1024:
                            report["evidenceError"] = "FrameLimitExceeded"
                            pending = b""
                    if pending:
                        report["evidenceError"] = "IncompleteSseFrame"
        except (httpx.HTTPError, BrokenPipeError, ConnectionResetError, ValueError, TypeError) as error:
            report["transportError"] = type(error).__name__
        finally:
            try:
                text_observer.finish(report)
            except (ValueError, TypeError) as error:
                report["evidenceError"] = type(error).__name__
            report["elapsedSeconds"] = monotonic() - started
            self.close_connection = True

    def log_message(self, format: str, *args: object) -> None:
        pass
