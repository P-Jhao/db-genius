"""Local HTTP provider and typed graph inputs for controlled compare tests."""

import threading

import pytest
from langchain_core.messages import BaseMessage
from test_model_protocol import Provider, model

from app.agent import compare_preflight
from app.agent.context_runtime import _estimated_tokens
from app.agent.graph import RunContext, RunState
from app.agent.graph_sql import SQLNodes
from app.agent.streaming import ModelStream
from app.agent.tools import RunTools
from app.agent.types import ChatRequest, Usage
from app.core.config import get_settings


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


async def complete_preparation_estimates(provider: Provider) -> list[int]:
    """Measure real preparation only, with no window restriction or provider decision."""
    run, _ = context(provider)
    estimates: list[int] = []
    original = compare_preflight._context_limit_reached

    def record(run: RunContext, messages: list[BaseMessage]) -> bool:
        estimates.append(_estimated_tokens(messages))
        return original(run, messages)

    state: RunState = {"messages": [], "intent": "db_compare", "clarification": None,
                      "step": 0, "decision": None, "answer": "", "finished": False}
    nodes = SQLNodes(run, get_settings().compare_agent_max_steps)
    calls_before = len(provider.requests)
    try:
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(compare_preflight, "_context_limit_reached", record)
            await nodes.prepare(state)
        if nodes.comparison.output_truncated or nodes.comparison.must_stop:
            raise RuntimeError("Capacity calibration requires complete, unrestricted preparation")
        if len(estimates) < 2 or estimates[-2] >= estimates[-1]:
            raise RuntimeError("Capacity calibration requires distinct final observation estimates")
        if len(provider.requests) != calls_before:
            raise RuntimeError("Preparation calibration must not call the report provider")
        return estimates
    finally:
        run.tools.close()
