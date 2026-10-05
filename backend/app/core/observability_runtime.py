"""Model-call accounting without collecting prompts or responses."""

import asyncio
import threading
from collections.abc import Awaitable, Callable, Coroutine
from contextvars import ContextVar
from dataclasses import dataclass
from functools import wraps
from time import monotonic
from typing import Protocol
from uuid import uuid4

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.tools import BaseTool
from opentelemetry.trace import Status, StatusCode

from app.adapters.cancellation import DatabaseExecutionInterrupted, DatabaseWriteOutcomeUnknown
from app.agent.cancellation import RunAborted
from app.agent.json_capabilities import JsonContract
from app.agent.streaming import ModelStream
from app.agent.types import EventSink, Usage
from app.core.observability_metrics import (
    database_call,
    first_chunk,
    model_call,
    persistence_call,
    result_outcome,
    run_finished,
    tool_call,
)
from app.core.observability_tracing import span


class ObservedModelStream(ModelStream):
    def __init__(self, model: BaseChatModel, emit: EventSink, usage: Usage,
                 cancel_event: threading.Event | None = None, *, task_id: str,
                 chat_json_object: bool = False) -> None:
        super().__init__(model, emit, usage, cancel_event, chat_json_object=chat_json_object)
        self.task_id = task_id

    async def call(self, messages: list[BaseMessage], step: int = 0, event: str | None = "content",
                   tools: list[BaseTool] | None = None, classification: bool = False,
                   final_report: bool = False, emit_reasoning: bool | None = None,
                   json_contract: JsonContract | None = None) -> AIMessage:
        prompt_before = self.usage.promptTokens
        completion_before = self.usage.completionTokens
        outcome = "error"
        try:
            with span("model.call", task_id=self.task_id, attributes={"model.step": step}):
                result = await super().call(messages, step=step, event=event,
                                            tools=tools, classification=classification,
                                            final_report=final_report, emit_reasoning=emit_reasoning,
                                            json_contract=json_contract)
            outcome = "done"
            return result
        except RunAborted as error:
            outcome = interruption_outcome(error.reason)
            raise
        except asyncio.CancelledError:
            outcome = "cancelled"
            raise
        finally:
            model_call(outcome, self.usage.promptTokens - prompt_before,
                       self.usage.completionTokens - completion_before)


def interruption_outcome(reason: str) -> str:
    return reason if reason in {"timeout", "write_outcome_unknown"} else "cancelled"


def observe_tool(task_id: str, name: str, function: Callable[..., Awaitable[str]],
                 result: Callable[[], object]) -> Callable[..., Awaitable[str]]:
    async def invoke(**kwargs: object) -> str:
        outcome = "error"
        try:
            with span("tool.call", task_id=task_id, attributes={"tool.name": name}) as current:
                output = await function(**kwargs)
                outcome = "done" if name == "doTerminate" else result_outcome(result())
                current.set_attribute("outcome", outcome)
                if outcome == "error":
                    current.set_status(Status(StatusCode.ERROR))
            return output
        except RunAborted as error:
            outcome = interruption_outcome(error.reason)
            raise
        except asyncio.CancelledError:
            outcome = "cancelled"
            raise
        finally:
            tool_call(name, outcome)
    return invoke


@dataclass
class RunAccounting:
    task_id: str
    started: float
    first_seen: bool = False
    outcome: str = "error"


_run: ContextVar[RunAccounting | None] = ContextVar("sqlchat_accounting", default=None)


def accounting() -> RunAccounting:
    current = _run.get()
    if current is None:
        raise RuntimeError("Chat accounting requires an active producer")
    return current


def visible_chunk(kind: str, content: object) -> None:
    current = accounting()
    if not current.first_seen and kind in {"content", "reasoning", "summary_delta"} and content:
        first_chunk(monotonic() - current.started)
        current.first_seen = True


def observe_chat[**P](function: Callable[P, Coroutine[object, object, None]]) -> Callable[P, Coroutine[object, object, None]]:
    @wraps(function)
    async def invoke(*args: P.args, **kwargs: P.kwargs) -> None:
        current = RunAccounting(uuid4().hex, monotonic())
        token = _run.set(current)
        try:
            with span("chat.run", task_id=current.task_id):
                await function(*args, **kwargs)
        except asyncio.CancelledError:
            current.outcome = "cancelled"
            raise
        finally:
            run_finished(current.outcome, monotonic() - current.started)
            _run.reset(token)
    return invoke


async def persist[**P, T](task_id: str, operation: str, function: Callable[P, T],
                         *args: P.args, **kwargs: P.kwargs) -> T:
    outcome = "error"
    try:
        with span("persistence." + operation, task_id=task_id):
            value = await asyncio.to_thread(function, *args, **kwargs)
        outcome = "done"
        return value
    finally:
        persistence_call(operation, outcome)


class DatabaseObserver(Protocol):
    def __call__[**P, T](self, function: Callable[P, T]) -> Callable[P, T]: ...


def observe_database(operation: str) -> DatabaseObserver:
    def decorate[**P, T](function: Callable[P, T]) -> Callable[P, T]:
        @wraps(function)
        def invoke(*args: P.args, **kwargs: P.kwargs) -> T:
            active = _run.get()
            with span("database." + operation, task_id=None if active is None else active.task_id) as current:
                outcome = "error"
                try:
                    result = function(*args, **kwargs)
                    outcome = result_outcome(result)
                    if outcome == "error":
                        current.set_status(Status(StatusCode.ERROR))
                    return result
                except DatabaseExecutionInterrupted as error:
                    outcome = "write_outcome_unknown" if error.write_outcome_unknown else error.reason
                    raise
                except DatabaseWriteOutcomeUnknown:
                    outcome = "write_outcome_unknown"
                    raise
                except TimeoutError:
                    outcome = "timeout"
                    raise
                finally:
                    current.set_attribute("outcome", outcome)
                    database_call(operation, outcome)
        return invoke
    return decorate
