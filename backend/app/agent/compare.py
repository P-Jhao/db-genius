"""Evidence and safety boundaries for the database comparison branch."""

import json
from dataclasses import dataclass, field

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from app.agent.compare_locale import compare_text
from app.agent.prompts import system_prompt
from app.agent.types import ChatRequest


def prepare_compare(request: ChatRequest, history: list[BaseMessage], locale: str) -> list[BaseMessage]:
    return [SystemMessage(content=system_prompt("db_compare", request, locale)),
            *history, HumanMessage(content=request.message)]


@dataclass
class CompareProgress:
    report: dict[str, object] | None = None
    output_truncated: bool = False
    artifact_id: str | None = None
    full_text: str = ""
    read_ranges: list[tuple[int, int]] = field(default_factory=list)

    def observe(self, output: str, report: dict[str, object] | None) -> None:
        if report is None:
            raise RuntimeError("Comparison tool returned without an authoritative report")
        try:
            value = json.loads(output)
        except json.JSONDecodeError as error:
            raise ValueError("Comparison tool output is invalid JSON") from error
        if not isinstance(value, dict):
            raise TypeError("Comparison tool output must be an object")
        self.output_truncated = value.get("marker") == "[TRUNCATED:TOOL_OUTPUT_TOO_LONG]"
        self.report = report
        self.full_text = json.dumps(report, ensure_ascii=False, default=str, allow_nan=False)
        self.read_ranges.clear()
        artifact_id = value.get("artifactId")
        if self.output_truncated and not isinstance(artifact_id, str):
            raise TypeError("Truncated comparison report lacks artifactId")
        self.artifact_id = artifact_id if isinstance(artifact_id, str) else None

    def observe_page(self, args: dict[str, object], result: object) -> None:
        if self.artifact_id is None or args.get("artifact_id") != self.artifact_id:
            return
        if not isinstance(result, dict):
            raise TypeError("Comparison report page must be an object")
        offset, end, content = result.get("offset"), result.get("nextOffset"), result.get("content")
        if (not isinstance(offset, int) or isinstance(offset, bool) or
                not isinstance(end, int) or isinstance(end, bool) or not isinstance(content, str)):
            raise TypeError("Comparison report page has invalid offsets or content")
        if (not 0 <= offset <= end <= len(self.full_text) or end != offset + len(content) or
                result.get("totalCharacters") != len(self.full_text) or
                self.full_text[offset:end] != content):
            raise ValueError("Comparison report page does not match the authoritative result")
        self.read_ranges.append((offset, end))
        covered = 0
        for start, stop in sorted(self.read_ranges):
            if start > covered:
                break
            covered = max(covered, stop)
        if covered == len(self.full_text):
            self.output_truncated = False

    @property
    def must_stop(self) -> bool:
        return self.report is not None and self.status(include_output=False) is not None

    def status(self, *, include_output: bool = True, locale: str = "en") -> str | None:
        report = self.report
        if report is None:
            return compare_text("missing", locale)
        reasons: list[str] = []
        if report.get("complete") is not True or report.get("success") is not True:
            reasons.append(compare_text("incomplete", locale))
        pre_type, test_type = report.get("preDbType"), report.get("testDbType")
        if not isinstance(pre_type, str) or not isinstance(test_type, str):
            raise TypeError("Comparison report lacks database types")
        if pre_type != test_type:
            reasons.append(compare_text("cross", locale, pre=pre_type, test=test_type))
        for side in ("pre", "test"):
            inferred = report.get(f"{side}SchemaInferred", False)
            if not isinstance(inferred, bool):
                raise TypeError("Schema inference flag must be a boolean")
            if inferred:
                count = report.get(f"{side}SampleSize")
                key = "sampled" if isinstance(count, int) and not isinstance(count, bool) else "inferred"
                reasons.append(compare_text(key, locale, side=side, size=count))
        if include_output and self.output_truncated:
            reasons.append(compare_text("truncated", locale))
        return "; ".join(reasons) if reasons else None

    def safe_report(self, locale: str = "en") -> str | None:
        limitation = self.status(locale=locale)
        if limitation is None:
            return None
        report = self.report
        if report is None:
            return limitation
        pre, test = report.get("preDatabase"), report.get("testDatabase")
        if not isinstance(pre, str) or not isinstance(test, str):
            raise TypeError("Comparison report lacks database names")
        lines = [compare_text("direction", locale, pre=pre, test=test), limitation,
                 compare_text("observations", locale), compare_text("no_sql", locale)]
        for side in ("pre", "test"):
            error = report.get(f"{side}Error")
            if isinstance(error, str) and error:
                lines.append(compare_text("metadata", locale, side=side, error=error))
        details_limited = False
        for key, label in (("newTables", "new"), ("droppedTables", "dropped"), ("alteredTables", "changed")):
            items = report.get(key)
            if not isinstance(items, list):
                raise TypeError(f"Comparison report lacks {key}")
            names = [item.get("table") for item in items if isinstance(item, dict)]
            lines.append(compare_text("count", locale, label=compare_text(label, locale), count=len(items)) +
                         (f" ({', '.join(str(name) for name in names[:20])})" if names else ""))
            details_limited = details_limited or len(items) > 20
        remaining = 20
        altered = report.get("alteredTables")
        if not isinstance(altered, list):
            raise TypeError("Comparison report lacks alteredTables")
        for table in altered:
            if not isinstance(table, dict) or not isinstance(table.get("changes"), list):
                raise TypeError("Comparison report contains invalid column changes")
            changes = table["changes"]
            shown = changes[:remaining]
            if shown:
                facts = json.dumps({"table": table["table"], "changes": shown}, ensure_ascii=False, allow_nan=False)
                lines.append(f"```json\n{facts}\n```")
                remaining -= len(shown)
            details_limited = details_limited or len(changes) > len(shown)
        if details_limited:
            lines.append(compare_text("details_limited", locale))
        return "\n".join(lines)
