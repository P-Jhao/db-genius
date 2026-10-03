"""Credential-free completion reasons and final-report framing observations."""

import hashlib
import re
from typing import cast

from app.agent.final_report import REPORT_CONTRACT, ReportDecoder

FINISH_REASONS = {"stop", "length", "tool_calls", "function_call", "content_filter"}
COUNTS = {"wireCharacters", "rawReportCharacters", "cleanedReportCharacters", "structuredToolCallCount"}
HASHES = {"wireUtf8Sha256", "rawReportUtf8Sha256", "cleanedReportUtf8Sha256", "finishReasonUtf8Sha256"}
FLAGS = {"envelopeComplete", "framingVerified"}
ERRORS = {"invalid_json_escape", "invalid_unicode_escape", "invalid_unicode_surrogate",
          "invalid_json_character", "invalid_report_envelope", "empty_report", "incomplete_protocol",
          "unexpected_summary_tool_call", "unexpected_summary_protocol", "provider_length", "provider_content_filter",
          "provider_other_finish", "provider_stream_incomplete"}


def record_finish_reason(choice: dict[str, object], report: dict[str, object]) -> None:
    if "finish_reason" in choice:
        report["finishReasonPresent"] = True
    reason = choice.get("finish_reason")
    if reason is None:
        return
    if not isinstance(reason, str):
        raise TypeError("Provider finish reason must be text")
    report["finishReason"] = reason if reason in FINISH_REASONS else "other"
    if reason not in FINISH_REASONS:
        report["finishReasonUtf8Sha256"] = hashlib.sha256(reason.encode("utf-8", errors="surrogatepass")).hexdigest()


def safe_observation(raw: dict[str, object]) -> dict[str, object]:
    safe: dict[str, object] = {}
    for key, value in raw.items():
        if key in COUNTS:
            if type(value) is not int or value < 0:
                raise TypeError("Summary observation count must be nonnegative")
        elif key in HASHES:
            if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
                raise TypeError("Summary observation hash must be SHA256")
        elif key in FLAGS | {"streamComplete"}:
            if type(value) is not bool:
                raise TypeError("Summary observation flag must be boolean")
        elif key == "finishReason":
            if value is not None and value not in FINISH_REASONS | {"other"}:
                raise ValueError("Unknown summary finish reason")
        elif key == "protocolCleanup":
            if value not in {"none", "removed", "incomplete"}:
                raise ValueError("Unknown summary cleanup classification")
        elif key == "errorCode":
            if value is not None and value not in ERRORS:
                raise ValueError("Unknown summary framing error")
        else:
            continue
        safe[str(key)] = value
    return safe


class ProviderTextObserver:
    """Inspect received text in memory; retain only lengths, hashes and enums."""

    def __init__(self, request: dict[str, object]) -> None:
        self.characters = 0
        self.digest = hashlib.sha256()
        self.reason: str | None = None
        self.tool_indexes: set[int] = set()
        messages = request.get("messages")
        last = messages[-1] if isinstance(messages, list) and messages else None
        framed = (isinstance(last, dict) and last.get("role") == "system" and
                  last.get("content") == REPORT_CONTRACT)
        self.decoder = ReportDecoder() if framed else None

    def consume(self, choice: dict[str, object]) -> None:
        reason = choice.get("finish_reason")
        if reason is not None:
            if not isinstance(reason, str):
                raise TypeError("Provider finish reason must be text")
            self.reason = reason
        delta = choice.get("delta", {})
        if delta is None:
            delta = {}
        if not isinstance(delta, dict):
            raise TypeError("Provider delta must be an object")
        content = delta.get("content")
        if content is not None:
            if not isinstance(content, str):
                raise TypeError("Provider text must be a string")
            self.characters += len(content)
            self.digest.update(content.encode("utf-8", errors="surrogatepass"))
            if self.decoder is not None:
                self.decoder.push(content)
        calls = delta.get("tool_calls", [])
        if not isinstance(calls, list):
            raise TypeError("Provider tool fragments must be a list")
        for call in calls:
            if not isinstance(call, dict) or type(call.get("index")) is not int:
                raise TypeError("Provider tool fragments require an index")
            self.tool_indexes.add(cast(int, call["index"]))

    def finish(self, report: dict[str, object]) -> None:
        report["providerText"] = {"characters": self.characters, "utf8Sha256": self.digest.hexdigest()}
        if self.decoder is None:
            return
        complete = self.decoder.finish(self.reason, len(self.tool_indexes))
        observation = dict(complete.observation)
        stream_complete = (report.get("providerDone") is True and report.get("transportError") is None and
                           report.get("evidenceError") is None)
        observation["streamComplete"] = stream_complete
        if not stream_complete:
            observation["framingVerified"] = False
            observation["errorCode"] = "provider_stream_incomplete"
        report["finalReport"] = safe_observation(observation)


def summary_delivery(events: list[dict[str, object]]) -> dict[str, object]:
    def text(kind: str) -> str:
        values = [event.get("content") for event in events if event.get("type") == kind]
        if not all(isinstance(value, str) for value in values):
            raise TypeError("Summary SSE content must be text")
        return "".join(cast(list[str], values))

    streamed, authoritative = text("summary_delta"), text("summary")
    return {
        "streamedCharacters": len(streamed),
        "streamedUtf8Sha256": hashlib.sha256(streamed.encode("utf-8")).hexdigest(),
        "authoritativeSummaryCount": sum(event.get("type") == "summary" for event in events),
        "authoritativeCharacters": len(authoritative),
        "authoritativeUtf8Sha256": hashlib.sha256(authoritative.encode("utf-8")).hexdigest(),
        "streamedMatchesAuthoritative": streamed == authoritative,
    }
