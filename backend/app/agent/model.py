"""OpenAI-compatible LangChain chat model with reasoning and tool streaming."""

import json
from collections.abc import AsyncIterator, Iterable
from typing import cast
from urllib.parse import urlsplit, urlunsplit

import httpx
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, ToolMessage
from langchain_core.messages.tool import ToolCallChunk
from langchain_core.outputs import ChatGenerationChunk, ChatResult
from pydantic import SecretStr

from app.agent.protocol_errors import ProtocolCode, mark


def completion_url(base_url: str) -> str:
    """Keep an explicit endpoint, or append the compatible API path once."""
    parsed = urlsplit(base_url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Model base URL must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Model base URL must not contain credentials, query, or fragment")
    path = parsed.path.rstrip("/")
    if path.endswith("/chat/completions"):
        pass
    elif path.endswith("/v1"):
        path += "/chat/completions"
    else:
        path += "/v1/chat/completions"
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def wire_message(message: BaseMessage) -> dict[str, object]:
    roles = {"human": "user", "ai": "assistant", "system": "system", "tool": "tool"}
    if message.type not in roles:
        raise TypeError(f"Unsupported model message type: {message.type}")
    result: dict[str, object] = {"role": roles[message.type], "content": message.content}
    if isinstance(message, ToolMessage):
        if not message.tool_call_id:
            raise ValueError("Tool response requires tool_call_id")
        result["tool_call_id"] = message.tool_call_id
    if isinstance(message, AIMessage):
        if message.tool_calls:
            result["tool_calls"] = [
                {
                    "id": call["id"],
                    "type": "function",
                    "function": {
                        "name": call["name"],
                        "arguments": json.dumps(call["args"], ensure_ascii=False),
                    },
                }
                for call in message.tool_calls
            ]
        reasoning = message.additional_kwargs.get("reasoning_content")
        if isinstance(reasoning, str) and reasoning:
            result["reasoning_content"] = reasoning
    return result


def _sse_data(lines: Iterable[str]) -> str | None:
    parts = [line[5:].lstrip(" ") for line in lines if line.startswith("data:")]
    return "\n".join(parts) if parts else None


def _usage_chunk(value: object) -> ChatGenerationChunk | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise mark(TypeError("Invalid model usage packet"), ProtocolCode.USAGE_PACKET_TYPE)
    prompt = value.get("prompt_tokens")
    completion = value.get("completion_tokens")
    total = value.get("total_tokens")
    if type(prompt) is not int or type(completion) is not int:
        raise mark(TypeError("Model usage requires prompt and completion token counts"), ProtocolCode.USAGE_COUNTS_TYPE)
    if total is None:
        total = prompt + completion
    if type(total) is not int or min(prompt, completion, total) < 0:
        raise mark(ValueError("Invalid model usage values"), ProtocolCode.USAGE_VALUES_INVALID)
    return ChatGenerationChunk(
        message=AIMessageChunk(
            content="",
            usage_metadata={
                "input_tokens": prompt,
                "output_tokens": completion,
                "total_tokens": total,
            },
        )
    )


def _delta_chunk(packet: dict[str, object]) -> ChatGenerationChunk | None:
    choices = packet.get("choices")
    if choices is None:
        return None
    if not isinstance(choices, list):
        raise mark(TypeError("Invalid model choices"), ProtocolCode.CHOICES_TYPE)
    if not choices:
        return None
    first = choices[0]
    if not isinstance(first, dict):
        raise mark(TypeError("Invalid model choice"), ProtocolCode.CHOICE_TYPE)
    finish = first.get("finish_reason")
    if finish is not None and not isinstance(finish, str):
        raise mark(TypeError("Model finish reason must be text"), ProtocolCode.FINISH_REASON_TYPE)
    delta = first.get("delta")
    if delta is None and finish is not None:
        delta = {}
    if not isinstance(delta, dict):
        return None
    content = delta.get("content")
    reasoning = delta.get("reasoning_content")
    if content is not None and not isinstance(content, str):
        raise mark(ValueError("Invalid model content delta"), ProtocolCode.CONTENT_TYPE)
    if reasoning is not None and not isinstance(reasoning, str):
        raise mark(ValueError("Invalid model reasoning delta"), ProtocolCode.REASONING_TYPE)
    additional: dict[str, object] = {}
    if reasoning:
        additional["reasoning_content"] = reasoning
    chunks: list[dict[str, object]] = []
    calls = delta.get("tool_calls")
    if calls is not None:
        if not isinstance(calls, list):
            raise mark(ValueError("Invalid model tool calls"), ProtocolCode.TOOL_CALLS_TYPE)
        for call in calls:
            if not isinstance(call, dict) or type(call.get("index")) is not int:
                raise mark(TypeError("Model tool call requires an index"), ProtocolCode.TOOL_INDEX_TYPE)
            if call["index"] < 0:
                raise mark(ValueError("Model tool-call index must be nonnegative"), ProtocolCode.TOOL_INDEX_NEGATIVE)
            if call.get("id") is not None and not isinstance(call["id"], str):
                raise mark(TypeError("Model tool-call ID must be text"), ProtocolCode.TOOL_ID_TYPE)
            function = call.get("function")
            if function is not None and not isinstance(function, dict):
                raise mark(ValueError("Invalid model tool function"), ProtocolCode.TOOL_FUNCTION_TYPE)
            function = function or {}
            if function.get("name") is not None and not isinstance(function["name"], str):
                raise mark(ValueError("Invalid model tool name"), ProtocolCode.TOOL_NAME_TYPE)
            if function.get("arguments") is not None and not isinstance(function["arguments"], str):
                raise mark(ValueError("Invalid model tool arguments"), ProtocolCode.TOOL_ARGUMENTS_TYPE)
            chunks.append(
                {
                    "name": function.get("name"),
                    "args": function.get("arguments"),
                    "id": call.get("id"),
                    "index": call["index"],
                    "type": "tool_call_chunk",
                }
            )
    if not content and not reasoning and not chunks and finish is None:
        return None
    return ChatGenerationChunk(
        message=AIMessageChunk(
            content=content or "",
            additional_kwargs=additional,
            response_metadata={} if finish is None else {"finish_reason": finish},
            tool_call_chunks=cast(list[ToolCallChunk], chunks),
        )
    )


class CompatibleChatModel(BaseChatModel):
    base_url: str
    api_key: SecretStr
    model_name: str

    @property
    def _llm_type(self) -> str:
        return "sqlchat-openai-compatible"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: object = None,
        **kwargs: object,
    ) -> ChatResult:
        raise RuntimeError("Use the async chat interface")

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: object = None,
        **kwargs: object,
    ) -> AsyncIterator[ChatGenerationChunk]:
        payload: dict[str, object] = {
            "model": self.model_name,
            "messages": [wire_message(message) for message in messages],
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        payload.update(kwargs)
        if stop is not None:
            payload["stop"] = stop
        headers = {"Authorization": f"Bearer {self.api_key.get_secret_value()}"}
        async with (
            httpx.AsyncClient(timeout=httpx.Timeout(180, connect=15)) as client,
            client.stream("POST", completion_url(self.base_url), headers=headers, json=payload) as response,
        ):
            if response.status_code >= 400:
                raise RuntimeError(f"Model provider returned HTTP {response.status_code}")
            frame: list[str] = []
            async for line in response.aiter_lines():
                if line:
                    frame.append(line)
                    continue
                data = _sse_data(frame)
                frame.clear()
                if data is None:
                    continue
                if data == "[DONE]":
                    return
                for chunk in self._parse_packet(data):
                    yield chunk
            data = _sse_data(frame)
            if data and data != "[DONE]":
                for chunk in self._parse_packet(data):
                    yield chunk

    @staticmethod
    def _parse_packet(data: str) -> list[ChatGenerationChunk]:
        try:
            packet = json.loads(data)
        except json.JSONDecodeError as error:
            mark(error, ProtocolCode.PACKET_JSON_INVALID)
            raise
        if not isinstance(packet, dict):
            raise mark(TypeError("Invalid model stream packet"), ProtocolCode.PACKET_NOT_OBJECT)
        if "error" in packet:
            raise mark(RuntimeError("Model provider returned a stream error"), ProtocolCode.PROVIDER_STREAM_ERROR)
        result: list[ChatGenerationChunk] = []
        delta = _delta_chunk(packet)
        if delta is not None:
            result.append(delta)
        usage = _usage_chunk(packet.get("usage"))
        if usage is not None:
            result.append(usage)
        return result
