"""Final-report framing; completion is not a factuality judgment."""

import hashlib
import json
import re
from dataclasses import dataclass

from app.agent.dsml import summary_cleanup

REPORT_CONTRACT = (
    "For this final-report call only, return exactly one JSON object, with no code fence: "
    '{"report":"the complete user-facing Markdown report","complete":true}. '
    "Put report first and complete last. Escape the report as a JSON string. Write the "
    "report in the user's language. The complete flag means the entire report was "
    "transmitted, not that every requested operation succeeded. Report actual verified "
    "successes, failures and unfinished work. Do not call tools."
)

_PREFIX = re.compile(r'\A\s*\{\s*"report"\s*:\s*"')
_ESCAPES = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f",
            "n": "\n", "r": "\r", "t": "\t"}
_FINISH_REASONS = {"stop", "length", "tool_calls", "function_call", "content_filter"}


class IncompleteFinalReport(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"Final report incomplete ({code}); prior tool results remain recorded")


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="surrogatepass")).hexdigest()


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate final-report field")
        result[key] = value
    return result


@dataclass(frozen=True)
class ReportCompletion:
    content: str
    observation: dict[str, object]
    error: str | None


class ReportDecoder:
    """Decode only the first report string; keep JSON framing out of SSE."""

    def __init__(self) -> None:
        self.wire = ""
        self.text = ""
        self.position: int | None = None
        self.closed = False
        self.error: str | None = None

    def _escape(self, start: int) -> tuple[str, int] | None:
        if len(self.wire) < start + 2:
            return None
        escape = self.wire[start + 1]
        if escape in _ESCAPES:
            return _ESCAPES[escape], start + 2
        if escape != "u":
            self.error = "invalid_json_escape"
            return None
        if len(self.wire) < start + 6:
            return None
        digits = self.wire[start + 2:start + 6]
        if re.fullmatch(r"[0-9a-fA-F]{4}", digits) is None:
            self.error = "invalid_unicode_escape"
            return None
        code = int(digits, 16)
        if 0xD800 <= code <= 0xDBFF:
            if len(self.wire) < start + 12:
                return None
            low_digits = self.wire[start + 8:start + 12]
            if (self.wire[start + 6:start + 8] != "\\u" or
                    re.fullmatch(r"[0-9a-fA-F]{4}", low_digits) is None):
                self.error = "invalid_unicode_surrogate"
                return None
            low = int(low_digits, 16)
            if not 0xDC00 <= low <= 0xDFFF:
                self.error = "invalid_unicode_surrogate"
                return None
            return chr(0x10000 + ((code - 0xD800) << 10) + low - 0xDC00), start + 12
        if 0xDC00 <= code <= 0xDFFF:
            self.error = "invalid_unicode_surrogate"
            return None
        return chr(code), start + 6

    def push(self, value: str) -> str:
        self.wire += value
        if self.closed or self.error is not None:
            return ""
        if self.position is None:
            match = _PREFIX.match(self.wire)
            if match is None:
                return ""
            self.position = match.end()
        pieces: list[str] = []
        while self.position < len(self.wire):
            character = self.wire[self.position]
            if character == '"':
                self.closed = True
                self.position += 1
                break
            if character == "\\":
                decoded = self._escape(self.position)
                if decoded is None:
                    break
                character, self.position = decoded
            elif ord(character) < 0x20 or 0xD800 <= ord(character) <= 0xDFFF:
                self.error = "invalid_json_character"
                break
            else:
                self.position += 1
            pieces.append(character)
        result = "".join(pieces)
        self.text += result
        return result

    def finish(self, reason: str | None, tool_calls: int) -> ReportCompletion:
        clean, protocol = summary_cleanup(self.text)
        envelope_complete = False
        error = self.error
        try:
            value = json.loads(self.wire, object_pairs_hook=_unique_object)
        except (json.JSONDecodeError, ValueError):
            error = "invalid_report_envelope"
        else:
            if (not isinstance(value, dict) or set(value) != {"report", "complete"} or
                    not isinstance(value["report"], str) or value["complete"] is not True or
                    not self.closed or value["report"] != self.text):
                error = "invalid_report_envelope"
            else:
                envelope_complete = True
        if not clean.strip() and error is None:
            error = "empty_report"
        if protocol == "incomplete":
            error = "incomplete_protocol"
        elif protocol == "removed":
            error = "unexpected_summary_protocol"
        if tool_calls or reason in {"tool_calls", "function_call"}:
            error = "unexpected_summary_tool_call"
        elif reason is not None and reason != "stop":
            error = "provider_" + reason if reason in _FINISH_REASONS else "provider_other_finish"
        observation: dict[str, object] = {
            "wireCharacters": len(self.wire), "wireUtf8Sha256": _digest(self.wire),
            "rawReportCharacters": len(self.text), "rawReportUtf8Sha256": _digest(self.text),
            "cleanedReportCharacters": len(clean), "cleanedReportUtf8Sha256": _digest(clean),
            "finishReason": reason if reason is None or reason in _FINISH_REASONS else "other",
            "structuredToolCallCount": tool_calls, "protocolCleanup": protocol,
            "envelopeComplete": envelope_complete, "framingVerified": error is None,
            "errorCode": error,
        }
        if reason is not None and reason not in _FINISH_REASONS:
            observation["finishReasonUtf8Sha256"] = _digest(reason)
        return ReportCompletion(clean, observation, error)
