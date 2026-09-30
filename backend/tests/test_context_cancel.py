"""Automatic compression uses S08 cancellation and known-usage accounting."""

import asyncio
import json
import threading
from collections.abc import AsyncIterator

import pytest
from langchain_core.messages import AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGenerationChunk
from pydantic import SecretStr

from app.agent.model import CompatibleChatModel
from app.agent.types import ChatRequest
from app.api import chat
from app.core.config import Settings
from app.models import Conversation, DbConfig, User
from app.services import chat_store, context_compress

pytest_plugins = ["test_chat_api"]


@pytest.mark.asyncio
async def test_cancel_stalled_automatic_summary_preserves_history_and_usage(
    chat_client: tuple[object, User, User, DbConfig], monkeypatch: pytest.MonkeyPatch,
) -> None:
    _client, owner, _, _ = chat_client
    conversation_id = chat_store.prepare(owner.id, ChatRequest(message="previous"))
    for index in range(8):
        role, kind = ("user", "user") if index % 2 == 0 else ("assistant", "summary")
        chat_store.save(conversation_id, role, f"previous {index}", kind)
    with chat_store.SessionLocal() as session:
        row = session.get(Conversation, conversation_id)
        assert row is not None
        row.context_tokens = 9000
        session.commit()
    monkeypatch.setattr(context_compress, "get_settings", lambda: Settings(context_auto_compress_enabled=True))
    started, closed = asyncio.Event(), asyncio.Event()

    class StallingModel(CompatibleChatModel):
        async def _astream(self, messages: list[BaseMessage], stop: list[str] | None = None,
                           run_manager: object = None, **kwargs: object) -> AsyncIterator[ChatGenerationChunk]:
            yield ChatGenerationChunk(message=AIMessageChunk(
                content="", usage_metadata={"input_tokens": 3, "output_tokens": 1, "total_tokens": 4},
            ))
            started.set()
            try:
                await asyncio.Event().wait()
                yield ChatGenerationChunk(message=AIMessageChunk(content="late summary"))
            finally:
                closed.set()

    model = StallingModel(base_url="http://localhost:1", api_key=SecretStr("local-test"), model_name="test")
    queue: asyncio.Queue[bytes | None] = asyncio.Queue()
    cancel = threading.Event()
    body = ChatRequest(message="new request", conversationId=conversation_id, confirmedIntent="simple_chat")
    task = asyncio.create_task(chat._produce(queue, owner.id, body, [], "en", model, 8192, cancel))
    await asyncio.wait_for(started.wait(), timeout=2)
    cancel.set()
    await asyncio.wait_for(task, timeout=2)
    assert closed.is_set()
    events = []
    while not queue.empty():
        frame = queue.get_nowait()
        if frame is not None:
            events.append(json.loads(frame.decode().removeprefix("data: ")))
    assert [event["type"] for event in events] == ["usage", "aborted"]
    assert events[0]["content"]["totalTokens"] == 4
    replay = chat_store.messages(owner.id, conversation_id)
    assert replay[0]["type"] == "user" and replay[-2]["content"] == "new request"
    assert replay[-1]["type"] == "aborted"
    assert not any(row["type"] == "compressed" for row in replay)
