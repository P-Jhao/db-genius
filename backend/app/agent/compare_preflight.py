"""Server-controlled comparison evidence before any report decision."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_core.tools import BaseTool

from app.agent.cancellation import check_cancelled
from app.agent.compare import CompareProgress
from app.agent.context_runtime import _estimated_tokens
from app.core.localization import select_locale

if TYPE_CHECKING:
    from app.agent.graph import RunContext


_CONTEXT_LIMITS = {
    "en": "Comparison preparation reached the configured model context budget; "
          "no report model reviewed the full evidence.",
    "zh-CN": "对比准备达到已配置的模型上下文预算；未调用报告模型审核完整证据。",
    "zh-TW": "比較準備達到已設定的模型上下文預算；未呼叫報告模型審核完整證據。",
    "es": "La preparación alcanzó el presupuesto de contexto del modelo; "
          "ningún modelo de informe revisó la evidencia completa.",
    "fr": "La préparation a atteint le budget de contexte du modèle ; "
          "aucun modèle de rapport n'a examiné toutes les preuves.",
    "ja": "比較準備が設定済みモデルのコンテキスト予算に達しました。レポートモデルは完全な証拠を確認していません。",
    "ms": "Persediaan mencapai bajet konteks model yang dikonfigurasi; "
          "tiada model laporan menyemak bukti penuh.",
}


@dataclass
class PreparedComparison(CompareProgress):
    context_limited: bool = False

    def status(self, *, include_output: bool = True, locale: str = "en") -> str | None:
        status = super().status(include_output=include_output, locale=locale)
        if not self.context_limited:
            return status
        limit = _CONTEXT_LIMITS[select_locale(locale)]
        return limit if status is None else f"{status}; {limit}"


def _context_limit_reached(context: RunContext, messages: list[BaseMessage]) -> bool:
    window = context.model_stream.usage.contextWindow
    if window is None:
        return False
    if window <= 0:
        raise ValueError("Context window must be positive")
    # Governance thresholds trigger elision/summary, not a smaller context capacity.
    # Preparation observations have no provider AI steps to elide; preserve them all
    # and limit report review only when their existing estimate reaches the window.
    return _estimated_tokens(messages) >= window


async def limited_context_report(context: RunContext, progress: PreparedComparison,
                                 messages: list[BaseMessage], step: int) -> str | None:
    """Check the actual compare model input, including any summary instructions."""
    if not _context_limit_reached(context, messages):
        return None
    progress.context_limited = True
    safe = progress.safe_report(context.locale)
    if safe is None:
        raise RuntimeError("Context-limited comparison lacks a safe report")
    check_cancelled(context.cancel_event)
    await context.emit("summary", safe, step)
    check_cancelled(context.cancel_event)
    return safe


async def _invoke(context: RunContext, tool: BaseTool, args: dict[str, object]) -> str:
    check_cancelled(context.cancel_event)
    context.tools.last_output = None
    context.tools.last_result = None
    result = await tool.ainvoke(args)
    check_cancelled(context.cancel_event)
    if not isinstance(result, str):
        raise TypeError("Controlled comparison tool output must be text")
    return result


async def _observe(context: RunContext, messages: list[BaseMessage], name: str,
                   output: str, step: int) -> None:
    # These are server observations, never invented provider tool decisions.
    messages.append(HumanMessage(content=f"Server preparation observation ({name}):\n{output}"))
    display = output if context.tools.last_output is None else context.tools.last_output
    await context.emit("step", f"{name}: {display}", step)
    check_cancelled(context.cancel_event)


async def prepare_comparison(context: RunContext, progress: PreparedComparison,
                             messages: list[BaseMessage], step: int,
                             max_steps: int) -> dict[str, object]:
    """Use the existing observed tools and scoped pages within the compare budget."""
    pre_id, test_id = context.tools.comparison_ids
    if pre_id is None or test_id is None:
        raise RuntimeError("Controlled comparison requires a selected pre/test pair")
    if step >= max_steps:
        return {"messages": messages, "step": step, "finished": True}
    available = {tool.name: tool for tool in context.tools.for_intent("db_compare")}
    messages.append(SystemMessage(content=(
        "The server runs compareDatabases for the authorized pre→test pair before your first "
        "report decision. Following server preparation observations are actual tool results; "
        "they are not provider-selected tool calls. Use them without repeating the comparison "
        "unless new evidence is needed. Migration SQL remains for manual review only."
    )))
    output = await _invoke(context, available["compareDatabases"], {"pre_id": pre_id, "test_id": test_id})
    step += 1
    report = context.tools.last_result
    if not isinstance(report, dict):
        raise TypeError("Comparison service result must be an object")
    progress.observe(output, report)
    await _observe(context, messages, "compareDatabases", output, step)
    progress.context_limited = _context_limit_reached(context, messages)
    offset = 0
    while progress.output_truncated and not progress.must_stop and step < max_steps:
        artifact_id = progress.artifact_id
        if artifact_id is None:
            raise RuntimeError("Truncated comparison lacks a scoped artifact")
        args: dict[str, object] = {"artifact_id": artifact_id, "offset": offset, "length": 16000}
        step += 1
        try:
            output = await _invoke(context, available["readToolOutput"], args)
        except ValueError as error:
            # The existing artifact API reports an unusably small output limit explicitly.
            # Other validation failures must remain visible rather than becoming a safe report.
            if str(error) != "Tool output limit cannot fit a page":
                raise
            check_cancelled(context.cancel_event)
            break
        page = context.tools.last_result
        if not isinstance(page, dict):
            raise TypeError("Comparison report page must be an object")
        end, has_more = page.get("nextOffset"), page.get("hasMore")
        if (page.get("offset") != offset or not isinstance(end, int) or isinstance(end, bool)
                or end <= offset or not isinstance(has_more, bool)
                or has_more != (end < len(progress.full_text))):
            raise ValueError("Comparison report page does not continue the requested range")
        progress.observe_page(args, page)
        await _observe(context, messages, "readToolOutput", output, step)
        progress.context_limited = _context_limit_reached(context, messages)
        offset = end
    return {"messages": messages, "step": step,
            "finished": progress.safe_report(context.locale) is not None}
