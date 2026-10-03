"""Model streaming with token accounting and partial-answer capture."""

import asyncio
import json
import logging
import threading
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import suppress
from typing import cast

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    SystemMessage,
    message_chunk_to_message,
)
from langchain_core.messages.tool import ToolCall
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import BaseModel

from app.agent.cancellation import check_cancelled
from app.agent.dsml import AllowedTool, StructuredCall, SummaryFilter, reconcile, strip
from app.agent.final_report import REPORT_CONTRACT, IncompleteFinalReport, ReportDecoder
from app.agent.types import EventSink, Usage

DEFAULT_TEMPERATURE = 0.7
logger = logging.getLogger(__name__)


def _append(old: str | None, new: str | None, *, identity: bool = False) -> str | None:
    if new is None:
        return old
    if old is None or (identity and old == new):
        return new
    return old + new


def _collect_calls(calls: dict[int, StructuredCall], chunk: AIMessageChunk) -> None:
    for part in chunk.tool_call_chunks:
        index = part.get("index")
        if type(index) is not int or index < 0:
            raise TypeError("Model tool-call fragment requires a nonnegative index")
        previous = calls.get(index, StructuredCall(None, None, None))
        calls[index] = StructuredCall(_append(previous.name, part.get("name")),
                                      _append(previous.args, part.get("args")),
                                      _append(previous.id, part.get("id"), identity=True))


class ModelStream:
    def __init__(self, model: BaseChatModel, emit: EventSink, usage: Usage,
                 cancel_event: threading.Event | None = None) -> None:
        self.model = model
        self.emit = emit
        self.usage = usage
        self.partial = ""
        self.reasoning = ""
        self.cancel_event = cancel_event

    async def call(
        self,
        messages: list[BaseMessage],
        step: int = 0,
        event: str | None = "content",
        tools: list[BaseTool] | None = None,
        classification: bool = False,
        final_report: bool = False,
    ) -> AIMessage:
        self.partial = ""
        self.reasoning = ""
        aggregate: AIMessageChunk | None = None
        latest_usage: dict[str, int] | None = None
        call_fragments: dict[int, StructuredCall] = {}
        if final_report and (tools or classification):
            raise ValueError("Final-report framing cannot be used for a tool or classification call")
        report_decoder = ReportDecoder() if final_report else None
        output_filter = SummaryFilter() if event == "summary_delta" or final_report else None
        if final_report:
            messages = [*messages, SystemMessage(content=REPORT_CONTRACT)]
        options: dict[str, object] = (
            {"thinking": {"type": "disabled"}} if classification
            else {"temperature": DEFAULT_TEMPERATURE}
        )
        if tools:
            options["tools"] = [convert_to_openai_tool(tool) for tool in tools]
        check_cancelled(self.cancel_event)
        iterator = self.model.astream(messages, **options).__aiter__()  # type: ignore[arg-type]

        async def next_chunk(source: AsyncIterator[AIMessageChunk]) -> AIMessageChunk:
            return await anext(source)

        pending: asyncio.Task[AIMessageChunk] | None = None
        try:
            while True:
                check_cancelled(self.cancel_event)
                pending = asyncio.create_task(next_chunk(iterator))
                while not pending.done():
                    await asyncio.wait({pending}, timeout=0.05)
                    check_cancelled(self.cancel_event)
                try:
                    chunk = await pending
                except StopAsyncIteration:
                    break
                finally:
                    pending = None
                check_cancelled(self.cancel_event)
                if not isinstance(chunk, AIMessageChunk):
                    raise TypeError("Model returned a non-assistant chunk")
                _collect_calls(call_fragments, chunk)
                if chunk.usage_metadata is not None:
                    metadata = chunk.usage_metadata
                    latest_usage = {
                        "input_tokens": int(metadata["input_tokens"]),
                        "output_tokens": int(metadata["output_tokens"]),
                        "total_tokens": int(metadata["total_tokens"]),
                    }
                content_chunk = chunk.model_copy(update={"usage_metadata": None})
                aggregate = content_chunk if aggregate is None else aggregate + content_chunk
                if isinstance(chunk.content, str):
                    decoded = (report_decoder.push(chunk.content) if report_decoder is not None
                               else chunk.content)
                    text = output_filter.push(decoded) if output_filter else decoded
                    self.partial += text
                    if text and event is not None:
                        await self.emit(event, text, step)
                reasoning = chunk.additional_kwargs.get("reasoning_content")
                if isinstance(reasoning, str):
                    self.reasoning += reasoning
                    if event is not None:
                        await self.emit("reasoning", reasoning, step)
                check_cancelled(self.cancel_event)
        finally:
            if pending is not None:
                pending.cancel()
                with suppress(asyncio.CancelledError):
                    await pending
            if isinstance(iterator, AsyncGenerator):
                with suppress(Exception):
                    await iterator.aclose()
            self.usage.record(latest_usage)
        check_cancelled(self.cancel_event)
        if aggregate is None:
            raise RuntimeError("Model returned an empty stream")
        report_observation: dict[str, object] | None = None
        if report_decoder is not None:
            reason = aggregate.response_metadata.get("finish_reason")
            if reason is not None and not isinstance(reason, str):
                raise TypeError("Summary finish reason must be text")
            completion = report_decoder.finish(reason, len(call_fragments))
            report_observation = completion.observation
            logger.info("Final report framing " + json.dumps(
                {"step": step, **report_observation}, sort_keys=True,
            ))
            check_cancelled(self.cancel_event)
            if completion.error is not None:
                raise IncompleteFinalReport(completion.error)
        if output_filter is not None:
            tail = output_filter.finish()
            self.partial += tail
            if tail and event is not None:
                await self.emit(event, tail, step)
        recovered: list[dict[str, object]] | None = None
        structured = [call_fragments[index] for index in sorted(call_fragments)]
        content = aggregate.content
        if report_decoder is not None:
            content = completion.content
        if tools and isinstance(content, str):
            allowed = {}
            schemas: dict[str, type[BaseModel]] = {}
            for tool in tools:
                schema = tool.get_input_schema()
                if not issubclass(schema, BaseModel):
                    raise TypeError("DSML recovery requires a Pydantic 2 tool schema")
                schemas[tool.name] = schema
                fields = schema.model_fields
                allowed[tool.name] = AllowedTool(
                    frozenset(name for name, field in fields.items() if field.is_required()),
                    frozenset(fields),
                )
            content, recovered = reconcile(content, structured, allowed)
            if recovered is not None:
                for recovered_call in recovered:
                    schemas[str(recovered_call["name"])].model_validate(recovered_call["args"], strict=True)
        elif not classification and event != "content" and isinstance(content, str):
            content = strip(content)
        validated: list[ToolCall] = []
        for call in structured:
            if recovered is not None:
                break
            if not call.id or not call.name:
                raise ValueError("Model returned a tool call without ID or name")
            try:
                arguments = json.loads("" if call.args is None else call.args)
            except json.JSONDecodeError as error:
                raise ValueError("Model returned invalid tool-call JSON") from error
            if not isinstance(arguments, dict):
                raise TypeError("Model tool-call arguments must be a JSON object")
            validated.append({"name": call.name, "args": arguments, "id": call.id, "type": "tool_call"})
        if len({call["id"] for call in validated}) != len(validated):
            raise ValueError("Duplicate tool-call IDs")
        message = message_chunk_to_message(aggregate)
        if not isinstance(message, AIMessage):
            raise TypeError("Expected an assistant message")
        message = message.model_copy(update={"content": content, "invalid_tool_calls": [],
            "tool_calls": validated if recovered is None else cast(list[ToolCall], recovered)})
        if not message.content and not message.tool_calls:
            raise RuntimeError("Model returned no content or tool calls")
        additional = dict(message.additional_kwargs)
        if self.reasoning:
            additional["reasoning_content"] = self.reasoning
        response_metadata: dict[str, object] = dict(message.response_metadata)
        if report_observation is not None:
            response_metadata["summary_observation"] = report_observation
        return message.model_copy(update={"additional_kwargs": additional, "usage_metadata": latest_usage,
                                          "response_metadata": response_metadata})
