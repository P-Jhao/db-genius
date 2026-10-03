"""Local HTTP provider and typed graph inputs for controlled compare tests."""

import threading

from test_model_protocol import Provider, model

from app.agent.graph import RunContext
from app.agent.streaming import ModelStream
from app.agent.tools import RunTools
from app.agent.types import ChatRequest, Usage


def context(provider: Provider, *, signal: threading.Event | None = None,
            cancel_on: str | None = None) -> tuple[RunContext, list[tuple[str, object, int]]]:
    events: list[tuple[str, object, int]] = []

    async def emit(kind: str, content: object, step: int) -> None:
        events.append((kind, content, step))
        if cancel_on is not None and cancel_on in str(content):
            if signal is None:
                raise RuntimeError("Cancellation test requires a signal")
            signal.set()

    request = ChatRequest(message="Compare current to desired", preDbConfigId=12,
                          testDbConfigId=13, confirmedIntent="db_compare")
    return RunContext(request, [], "en", ModelStream(model(provider), emit, Usage(), signal),
                      RunTools(7, request, signal), emit, signal), events


def observations(provider: Provider, name: str) -> list[str]:
    messages = provider.requests[-1]["messages"]
    if not isinstance(messages, list):
        raise TypeError("Provider messages must be a list")
    prefix = f"Server preparation observation ({name}):\n"
    return [message["content"].removeprefix(prefix) for message in messages
            if message["role"] == "user" and isinstance(message["content"], str)
            and message["content"].startswith(prefix)]
