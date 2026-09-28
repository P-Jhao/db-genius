"""Model streaming with token accounting and partial-answer capture."""

import json

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, message_chunk_to_message
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool

from app.agent.types import EventSink, Usage


class ModelStream:
    def __init__(self, model: BaseChatModel, emit: EventSink, usage: Usage) -> None:
        self.model = model
        self.emit = emit
        self.usage = usage
        self.partial = ""
        self.reasoning = ""

    async def call(
        self,
        messages: list[BaseMessage],
        step: int = 0,
        event: str | None = "content",
        tools: list[BaseTool] | None = None,
        json_mode: bool = False,
    ) -> AIMessage:
        self.partial = ""
        self.reasoning = ""
        aggregate: AIMessageChunk | None = None
        latest_usage: dict[str, int] | None = None
        options: dict[str, object] = {}
        if tools:
            options["tools"] = [convert_to_openai_tool(tool) for tool in tools]
        if json_mode:
            options["response_format"] = {"type": "json_object"}
        try:
            async for chunk in self.model.astream(messages, **options):
                if not isinstance(chunk, AIMessageChunk):
                    raise TypeError("Model returned a non-assistant chunk")
                if chunk.usage_metadata is not None:
                    latest_usage = dict(chunk.usage_metadata)
                content_chunk = chunk.model_copy(update={"usage_metadata": None})
                aggregate = content_chunk if aggregate is None else aggregate + content_chunk
                if isinstance(chunk.content, str):
                    self.partial += chunk.content
                    if chunk.content and event is not None:
                        await self.emit(event, chunk.content, step)
                reasoning = chunk.additional_kwargs.get("reasoning_content")
                if isinstance(reasoning, str):
                    self.reasoning += reasoning
                    if event is not None:
                        await self.emit("reasoning", reasoning, step)
        finally:
            self.usage.record(latest_usage)
        if aggregate is None:
            raise RuntimeError("Model returned an empty stream")
        for call in aggregate.tool_call_chunks:
            if not call.get("id") or not call.get("name"):
                raise ValueError("Model returned a tool call without ID or name")
            try:
                arguments = json.loads(call.get("args") or "")
            except json.JSONDecodeError as error:
                raise ValueError("Model returned invalid tool-call JSON") from error
            if not isinstance(arguments, dict):
                raise TypeError("Model tool-call arguments must be a JSON object")
        message = message_chunk_to_message(aggregate)
        if not isinstance(message, AIMessage):
            raise TypeError("Expected an assistant message")
        if message.invalid_tool_calls:
            raise ValueError("Model returned invalid tool-call JSON")
        if not message.content and not message.tool_calls:
            raise RuntimeError("Model returned no content or tool calls")
        additional = dict(message.additional_kwargs)
        if self.reasoning:
            additional["reasoning_content"] = self.reasoning
        return message.model_copy(update={"additional_kwargs": additional, "usage_metadata": latest_usage})
