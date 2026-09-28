"""Model streaming with token accounting and partial-answer capture."""
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

    async def call(self, messages: list[BaseMessage], step: int = 0,
                   event: str | None = "content", tools: list[BaseTool] | None = None,
                   json_mode: bool = False) -> AIMessage:
        self.partial = ""
        self.reasoning = ""
        aggregate: AIMessageChunk | None = None
        options: dict[str, object] = {}
        if tools:
            options["tools"] = [convert_to_openai_tool(tool) for tool in tools]
        if json_mode:
            options["response_format"] = {"type": "json_object"}
        try:
            async for chunk in self.model.astream(messages, **options):
                if not isinstance(chunk, AIMessageChunk):
                    raise TypeError("Model returned a non-assistant chunk")
                aggregate = chunk if aggregate is None else aggregate + chunk
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
            if aggregate is not None and aggregate.usage_metadata is not None:
                self.usage.record(dict(aggregate.usage_metadata))
        if aggregate is None:
            raise RuntimeError("Model returned an empty stream")
        message = message_chunk_to_message(aggregate)
        if not isinstance(message, AIMessage):
            raise TypeError("Expected an assistant message")
        if message.invalid_tool_calls:
            raise ValueError("Model returned invalid tool-call JSON")
        return message
