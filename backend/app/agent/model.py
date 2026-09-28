"""LangChain model retaining provider reasoning on tool-call round trips."""
import json
from collections.abc import AsyncIterator
from typing import cast

import httpx
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGenerationChunk, ChatResult
from pydantic import SecretStr


def wire_message(message: BaseMessage) -> dict[str, object]:
    roles = {"human": "user", "ai": "assistant", "system": "system", "tool": "tool"}
    result: dict[str, object] = {"role": roles[message.type], "content": message.content}
    if isinstance(message, ToolMessage):
        result["tool_call_id"] = message.tool_call_id
    if isinstance(message, AIMessage):
        if message.tool_calls:
            result["tool_calls"] = [
                {"id": call["id"], "type": "function", "function": {
                    "name": call["name"], "arguments": json.dumps(call["args"], ensure_ascii=False)}}
                for call in message.tool_calls
            ]
        reasoning = message.additional_kwargs.get("reasoning_content")
        if reasoning is not None:
            result["reasoning_content"] = reasoning
    return result


class CompatibleChatModel(BaseChatModel):
    base_url: str
    api_key: SecretStr
    model_name: str

    @property
    def _llm_type(self) -> str:
        return "sqlchat-openai-compatible"

    def _generate(self, messages: list[BaseMessage], stop: list[str] | None = None,
                  run_manager: object = None, **kwargs: object) -> ChatResult:
        raise RuntimeError("Use the async chat interface")

    async def _astream(self, messages: list[BaseMessage], stop: list[str] | None = None,
                       run_manager: object = None, **kwargs: object) -> AsyncIterator[ChatGenerationChunk]:
        payload: dict[str, object] = {
            "model": self.model_name, "messages": [wire_message(m) for m in messages],
            "stream": True, "stream_options": {"include_usage": True},
        }
        payload.update(kwargs)
        if stop is not None:
            payload["stop"] = stop
        headers = {"Authorization": f"Bearer {self.api_key.get_secret_value()}"}
        async with httpx.AsyncClient(timeout=httpx.Timeout(180, connect=15)) as client:
            async with client.stream("POST", self.base_url.rstrip("/") + "/chat/completions",
                                     headers=headers, json=payload) as response:
                if response.status_code >= 400:
                    await response.aread()
                    raise RuntimeError(f"Model provider returned HTTP {response.status_code}")
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    packet = json.loads(data)
                    if "error" in packet:
                        raise RuntimeError("Model provider returned a stream error")
                    usage = packet.get("usage")
                    if usage:
                        yield ChatGenerationChunk(message=AIMessageChunk(content="", usage_metadata={
                            "input_tokens": usage["prompt_tokens"],
                            "output_tokens": usage["completion_tokens"],
                            "total_tokens": usage["total_tokens"],
                        }))
                    choices = packet.get("choices", [])
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {})
                    additional = {}
                    if delta.get("reasoning_content"):
                        additional["reasoning_content"] = delta["reasoning_content"]
                    chunks = [{"name": c.get("function", {}).get("name"),
                               "args": c.get("function", {}).get("arguments"),
                               "id": c.get("id"), "index": c["index"], "type": "tool_call_chunk"}
                              for c in delta.get("tool_calls", [])]
                    yield ChatGenerationChunk(message=AIMessageChunk(
                        content=delta.get("content") or "", additional_kwargs=additional,
                        tool_call_chunks=cast(list, chunks),
                    ))
