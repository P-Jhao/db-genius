"""SSE transport disconnect signals the running chat producer."""

import asyncio
import threading
from types import SimpleNamespace
from typing import cast

import pytest
from fastapi import Request
from pydantic import SecretStr
from sqlalchemy.orm import Session
from starlette.types import Message, Scope

from app.agent.types import ChatRequest
from app.api import chat
from app.models import User
from app.services import model_config


@pytest.mark.asyncio
async def test_transport_disconnect_sets_shared_event(monkeypatch: pytest.MonkeyPatch) -> None:
    scope: Scope = {"type": "http", "method": "POST", "path": "/api/chat", "headers": [],
                    "query_string": b"", "http_version": "1.1", "scheme": "http",
                    "server": ("localhost", 80), "client": ("localhost", 12345), "root_path": ""}
    disconnected = asyncio.Event()
    producer_saw_cancel = asyncio.Event()
    first_receive = True

    async def receive() -> Message:
        nonlocal first_receive
        if first_receive:
            first_receive = False
            return {"type": "http.request", "body": b"", "more_body": False}
        await disconnected.wait()
        return {"type": "http.disconnect"}

    async def send(message: Message) -> None:
        if message["type"] == "http.response.body" and message.get("body"):
            disconnected.set()

    async def fake_produce(queue: asyncio.Queue[bytes | None], _user_id: int, _body: ChatRequest,
                           _history: list[object], _locale: str, _model: object,
                           _context_window: int | None, cancel_event: threading.Event) -> None:
        await queue.put(b'data: {"type":"thinking"}\n\n')
        while not cancel_event.is_set():
            await asyncio.sleep(0.01)
        producer_saw_cancel.set()
        await queue.put(None)

    monkeypatch.setattr(chat, "_produce", fake_produce)
    monkeypatch.setattr(model_config, "resolve_active_model", lambda _session, _user_id: SimpleNamespace(
        base_url="http://localhost:1", api_key=SecretStr("local-test"), model_name="test",
        context_window=None,
    ))
    user = User(id=1, username="owner", password_hash="unused", status=1)
    request = Request(scope, receive)
    response = await chat.chat(ChatRequest.model_validate({"message": "hello"}), request,
                               user, cast(Session, object()))
    await asyncio.wait_for(response(scope, receive, send), timeout=2)
    await asyncio.wait_for(producer_saw_cancel.wait(), timeout=2)
