"""Model-backed cross-turn summary compression."""

import logging
from importlib.resources import files

from langchain_core.messages import HumanMessage, SystemMessage

from app.agent.cancellation import RunAborted
from app.agent.model import CompatibleChatModel
from app.agent.prompts import language, load_prompt_template, render_prompt_template, split_prompt_sections
from app.agent.streaming import ModelStream
from app.core.config import get_settings
from app.core.localization import SUPPORTED_LOCALES, select_locale
from app.models import Message
from app.schemas.context_compress import CompressResult
from app.services import chat_store

logger = logging.getLogger(__name__)


def _estimate(text: str) -> int:
    """Approximate display value, never provider billing usage."""
    return (len(text.encode("utf-8")) + 3) // 4


def _message(key: str, locale: str, *args: object) -> str:
    selected = select_locale(locale)
    suffix = SUPPORTED_LOCALES[selected]
    resource = files("app").joinpath("resources", "i18n", f"messages{suffix}.properties")
    for line in resource.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{key}="):
            return line.partition("=")[2].format(*args)
    raise KeyError(f"Missing compression message: {key} ({selected})")


def _transcript(rows: list[Message], locale: str) -> str:
    chinese = select_locale(locale) == "zh-CN"
    parts: list[str] = []
    for row in rows:
        if row.type == "context_summary" or (row.type == "summary" and row.step == -2):
            role = "此前摘要" if chinese else "previous summary"
        elif row.role == "user":
            role = "用户" if chinese else "user"
        else:
            role = "助手" if chinese else "assistant"
        parts.append(f"[{role}] {row.content}")
    return "\n\n".join(parts)


async def _summarize(model: CompatibleChatModel, rows: list[Message],
                     target_tokens: int | None, locale: str, stream: ModelStream | None = None) -> str:
    sections = split_prompt_sections(load_prompt_template("summary-compressor", locale))
    if len(sections) != 2:
        raise ValueError("Summary compressor prompt requires system and user sections")
    system = f"{sections[0]}\n\nYou MUST respond in {language(locale)}."
    user_template = sections[1]
    if target_tokens is None:
        user_template = "\n".join(line for line in user_template.splitlines()
                                  if "{targetTokens}" not in line)
    prompt = render_prompt_template(user_template, {
        "transcript": _transcript(rows, locale),
        "targetTokens": "" if target_tokens is None else str(target_tokens),
    })
    messages = [SystemMessage(content=system), HumanMessage(content=prompt)]
    if stream is not None:
        answer = await stream.call(messages, event=None)
        if answer.tool_calls or not isinstance(answer.content, str):
            raise ValueError("Compression model must return text without tools")
        summary = answer.content.strip()
    else:
        content: list[str] = []
        async for chunk in model.astream(messages):
            if not isinstance(chunk.content, str) or chunk.tool_call_chunks:
                raise ValueError("Compression model must return text without tools")
            content.append(chunk.content)
        summary = "".join(content).strip()
    if not summary:
        raise ValueError("Compression model returned an empty summary")
    return summary


async def compress(user_id: int, conversation_id: int, model: CompatibleChatModel,
                   locale: str, target_tokens: int | None = None,
                   stream: ModelStream | None = None) -> CompressResult:
    if target_tokens is not None and target_tokens <= 0:
        raise ValueError("targetTokens must be positive")
    rows, context_tokens = chat_store.context_snapshot(user_id, conversation_id)
    keep_count = get_settings().context_keep_last_messages
    if len(rows) <= keep_count:
        return CompressResult(conversation_id=conversation_id, compressed=False,
                              before_tokens=context_tokens, after_tokens=context_tokens,
                              summary_message_id=None,
                              message=_message("compress.summary.skip", locale, len(rows), keep_count))
    older, recent = rows[:-keep_count], rows[-keep_count:]
    before = sum(_estimate(row.content) for row in rows)
    try:
        summary = await _summarize(model, older, target_tokens, locale, stream)
        after = _estimate(summary) + sum(_estimate(row.content) for row in recent)
        summary_id = chat_store.apply_compression(
            user_id, conversation_id, [row.id for row in rows], [row.id for row in older],
            summary, after,
        )
    except RunAborted:
        raise
    except Exception as error:  # noqa: BLE001 - failed compression must preserve original context
        logger.warning("Context compression failed conversationId=%s errorType=%s",
                       conversation_id, type(error).__name__)
        return CompressResult(conversation_id=conversation_id, compressed=False,
                              before_tokens=context_tokens, after_tokens=context_tokens,
                              summary_message_id=None,
                              message=_message("compress.summary.failed", locale, type(error).__name__))
    return CompressResult(conversation_id=conversation_id, compressed=True,
                          before_tokens=before, after_tokens=after,
                          summary_message_id=summary_id,
                          message=_message("compress.summary.done", locale, len(older), max(0, before - after)))


async def compress_if_needed(user_id: int, conversation_id: int, model: CompatibleChatModel,
                             context_window: int | None, locale: str,
                             stream: ModelStream | None = None) -> CompressResult | None:
    settings = get_settings()
    if not settings.context_auto_compress_enabled or context_window is None:
        return None
    _, context_tokens = chat_store.context_snapshot(user_id, conversation_id)
    if context_tokens is None or context_tokens < settings.context_auto_compress_threshold * context_window:
        return None
    return await compress(user_id, conversation_id, model, locale, stream=stream)
