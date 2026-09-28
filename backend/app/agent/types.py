"""Typed chat protocol, shared by the API and graph."""

from collections.abc import Awaitable, Callable, Mapping
from typing import Literal, TypedDict

from langchain_core.messages import BaseMessage
from pydantic import BaseModel, ConfigDict, Field

type Intent = Literal["simple_chat", "sql_query", "workflow", "db_compare"]
type EventSink = Callable[[str, object, int], Awaitable[None]]


class ChatRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    message: str = Field(min_length=1, max_length=100_000)
    conversation_id: int | None = Field(None, alias="conversationId")
    db_config_ids: list[int] | None = Field(None, alias="dbConfigIds")
    pre_db_config_id: int | None = Field(None, alias="preDbConfigId")
    test_db_config_id: int | None = Field(None, alias="testDbConfigId")
    file_ids: list[int] | None = Field(None, alias="fileIds")
    confirmed_intent: Intent | None = Field(None, alias="confirmedIntent")


class Classification(BaseModel):
    intent: Intent
    confidence: float = Field(ge=0, le=1)
    reasoning: str
    needsClarification: bool


class GraphState(TypedDict):
    messages: list[BaseMessage]
    intent: Intent
    clarify: bool
    step: int
    finished: bool


class Usage(BaseModel):
    promptTokens: int = 0
    completionTokens: int = 0
    totalTokens: int = 0
    contextTokens: int = 0
    callCount: int = 0
    contextWindow: int | None = None
    conversationTotalTokens: int | None = None

    def record(self, usage: Mapping[str, int] | None) -> None:
        """Count a model call once; unknown provider usage is not an estimate."""
        self.callCount += 1
        if usage is None:
            return
        prompt = usage.get("input_tokens", 0)
        completion = usage.get("output_tokens", 0)
        total = usage.get("total_tokens", 0)
        if min(prompt, completion, total) < 0:
            raise ValueError("Model usage cannot be negative")
        self.promptTokens += prompt
        self.completionTokens += completion
        self.totalTokens += total
        self.contextTokens = prompt
