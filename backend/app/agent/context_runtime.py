"""Single-run context governance and repeated tool-call detection."""

import json
from collections import Counter
from collections.abc import Awaitable, Callable

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from app.agent.output_guard import OutputArtifacts
from app.agent.prompts import language, load_prompt_template, render_prompt_template, split_prompt_sections
from app.agent.types import EventSink
from app.core.config import get_settings
from app.core.localization import _messages, select_locale


def _compact_message(key: str, locale: str, saved_tokens: int = 0) -> str:
    translated = _messages(select_locale(locale)).get(key, _messages("en").get(key))
    if translated is None:
        raise KeyError(f"Missing context compact translation: {key}")
    return translated.format(saved_tokens)


class RepeatedCalls:
    def __init__(self) -> None:
        self._counts: Counter[tuple[str, str]] = Counter()

    def record(self, name: str, args: dict[str, object]) -> tuple[bool, bool]:
        signature = (name, json.dumps(args, ensure_ascii=False, sort_keys=True,
                                      separators=(",", ":"), default=str))
        self._counts[signature] += 1
        settings = get_settings()
        count = self._counts[signature]
        return count == settings.repeated_tool_call_warning_count, count >= settings.repeated_tool_call_stop_count


def _steps(messages: list[BaseMessage]) -> list[tuple[int, int]]:
    starts = [index for index, message in enumerate(messages)
              if isinstance(message, AIMessage) and message.tool_calls]
    return [(start, starts[index + 1] if index + 1 < len(starts) else len(messages))
            for index, start in enumerate(starts)]


def _observation_stub(content: str, artifacts: OutputArtifacts | None) -> str:
    try:
        value = json.loads(content)
    except json.JSONDecodeError:
        value = None
    if not isinstance(value, dict):
        value = {}
    keys = ("success", "error", "rowCount", "affectedRows", "message", "truncated",
            "artifactId", "totalCharacters", "totalRows", "hasMore", "sourceTruncated",
            "sourceTotalRows", "sourceIncomplete")
    facts = {key: value[key] for key in keys if key in value}
    if "artifactId" not in facts and artifacts is not None:
        facts["artifactId"] = artifacts.add(content)
        facts["totalCharacters"] = len(content)
    facts["marker"] = "[ELIDED:STALE_OBSERVATION]"
    facts["observationElided"] = True
    return json.dumps(facts, ensure_ascii=False, default=str)


def _estimated_tokens(messages: list[BaseMessage]) -> int:
    total = 0
    for message in messages:
        size = len(str(message.content))
        if isinstance(message, AIMessage) and message.tool_calls:
            size += len(json.dumps(message.tool_calls, ensure_ascii=False, default=str))
        total += (size + 3) // 4 + 12
    return total


async def govern_messages(
    messages: list[BaseMessage], *, context_window: int | None,
    summarize: Callable[[list[BaseMessage]], Awaitable[str]],
    emit: EventSink | None = None, step: int = 0, locale: str = "en",
    artifacts: OutputArtifacts | None = None,
) -> list[BaseMessage]:
    """Elide old observations, then summarize old steps using an actual model summary."""
    if context_window is None:
        return messages
    if context_window <= 0:
        raise ValueError("Context window must be positive")
    settings = get_settings()
    governed = list(messages)
    steps = _steps(governed)
    ratio = _estimated_tokens(governed) / context_window
    if settings.observation_elision_enabled and ratio >= settings.observation_elision_threshold:
        older = steps[:-settings.observation_elision_keep_last_steps]
        replacements: dict[int, ToolMessage] = {}
        for start, end in older:
            for index in range(start, end):
                message = governed[index]
                if isinstance(message, ToolMessage):
                    replacement = ToolMessage(
                        content=_observation_stub(str(message.content), artifacts),
                        tool_call_id=message.tool_call_id,
                    )
                    if replacement.content != message.content:
                        replacements[index] = replacement
        if replacements:
            before = _estimated_tokens(governed)
            if emit is not None:
                await emit("context_compact", {"phase": "start", "tier": "elide",
                                               "message": _compact_message("chat.compacting", locale),
                                               "beforeTokens": before}, step)
            governed = [replacements.get(index, message) for index, message in enumerate(governed)]
            if emit is not None:
                await emit("context_compact", {"phase": "end", "tier": "elide",
                                               "message": _compact_message("chat.compacted.elide", locale,
                                                                           max(0, before - _estimated_tokens(governed))),
                                               "beforeTokens": before,
                                               "afterTokens": _estimated_tokens(governed),
                                               "affectedUnits": len(replacements)}, step)
    steps = _steps(governed)
    if (settings.step_summary_enabled and
            _estimated_tokens(governed) / context_window >= settings.step_summary_threshold and
            len(steps) > settings.step_summary_keep_last_steps):
        cutoff = steps[-settings.step_summary_keep_last_steps][0]
        first = steps[0][0]
        old = governed[first:cutoff]
        before = _estimated_tokens(governed)
        if emit is not None:
            await emit("context_compact", {"phase": "start", "tier": "summarize",
                                           "message": _compact_message("chat.compacting", locale),
                                           "beforeTokens": before}, step)
        summary = await summarize(old)
        if not summary.strip():
            raise ValueError("Step summary model returned empty text")
        governed = [*governed[:first], SystemMessage(content="Earlier execution steps summary: " + summary),
                    *governed[cutoff:]]
        if emit is not None:
            await emit("context_compact", {"phase": "end", "tier": "summarize",
                                           "message": _compact_message("chat.compacted.summarize", locale,
                                                                       max(0, before - _estimated_tokens(governed))),
                                           "beforeTokens": before,
                                           "afterTokens": _estimated_tokens(governed),
                                           "affectedUnits": len(steps) - settings.step_summary_keep_last_steps}, step)
    if settings.stale_reasoning_discard_enabled:
        steps = _steps(governed)
        for start, _end in steps[:-settings.step_summary_keep_last_steps]:
            message = governed[start]
            if isinstance(message, AIMessage) and "reasoning_content" in message.additional_kwargs:
                kwargs = dict(message.additional_kwargs)
                del kwargs["reasoning_content"]
                governed[start] = message.model_copy(update={"additional_kwargs": kwargs})
    return governed


def summary_request(messages: list[BaseMessage], locale: str = "en") -> list[BaseMessage]:
    """Render the source step-condenser prompt for the current request locale."""
    facts: list[dict[str, object]] = []
    for message in messages:
        fact: dict[str, object] = {"role": message.type, "content": message.content}
        if isinstance(message, AIMessage) and message.tool_calls:
            fact["toolCalls"] = message.tool_calls
        if isinstance(message, ToolMessage):
            fact["toolCallId"] = message.tool_call_id
        facts.append(fact)
    template = render_prompt_template(load_prompt_template("step-condenser", locale), {
        "transcript": json.dumps(facts, ensure_ascii=False, default=str),
    })
    sections = split_prompt_sections(template)
    if len(sections) != 2:
        raise ValueError("Step condenser prompt requires a user section")
    return [SystemMessage(content=f"{sections[0]}\n\nRespond in {language(locale)}."),
            HumanMessage(content=sections[1])]
