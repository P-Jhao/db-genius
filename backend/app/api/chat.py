"""Authenticated REST history and cancellable POST SSE chat endpoint."""

import asyncio
import json
import logging
import threading
from collections.abc import AsyncIterator
from time import monotonic, time_ns
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from langchain_core.messages import BaseMessage
from sqlalchemy import select

from app.adapters.safety import UnsafeStatement
from app.agent.cancellation import RunAborted, check_cancelled
from app.agent.graph import RunContext, run_graph
from app.agent.model import CompatibleChatModel
from app.agent.streaming import ModelStream
from app.agent.tools import RunTools
from app.agent.types import ChatRequest, Usage
from app.api.auth import CurrentUser, DatabaseSession
from app.core.errors import BusinessError, success
from app.core.localization import translate
from app.models import DbConfig, UploadedFile
from app.services import chat_store, model_config

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat")
CHAT_REQUEST_TIMEOUT_SECONDS = 300
SSE_KEEPALIVE_SECONDS = 15
_active_producers: set[asyncio.Task[None]] = set()


def _check_resources(session: DatabaseSession, user_id: int, body: ChatRequest) -> None:
    db_ids = set(body.db_config_ids or [])
    db_ids.update(i for i in (body.pre_db_config_id, body.test_db_config_id) if i is not None)
    for db_id in db_ids:
        row = session.scalar(select(DbConfig).where(DbConfig.id == db_id, DbConfig.user_id == user_id))
        if row is None:
            raise BusinessError(404, "Database not found", 404)
        if row.status != 1:
            raise BusinessError(400, "Database is not connected")
    for file_id in set(body.file_ids or []):
        uploaded = session.scalar(select(UploadedFile).where(
            UploadedFile.id == file_id, UploadedFile.user_id == user_id,
        ))
        if uploaded is None:
            raise BusinessError(404, "File not found", 404)


def _frame(task_id: str, kind: str, content: object, step: int) -> bytes:
    event = {"taskId": task_id, "step": step, "type": kind, "content": content,
             "timestamp": time_ns() // 1_000_000}
    return f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n".encode()


async def _produce(queue: asyncio.Queue[bytes | None], user_id: int, body: ChatRequest,
                   history: list[BaseMessage], locale: str, model: CompatibleChatModel,
                   context_window: int | None, cancel_event: threading.Event) -> None:
    task_id = uuid4().hex
    usage = Usage(contextWindow=context_window)
    conversation_id: int | None = None
    partial_content = ""
    partial_summary = ""
    complete_summary: str | None = None
    tools = RunTools(user_id, body, cancel_event)
    timeout_fired = False

    async def expire() -> None:
        nonlocal timeout_fired
        await asyncio.sleep(CHAT_REQUEST_TIMEOUT_SECONDS)
        timeout_fired = True
        cancel_event.set()

    timer = asyncio.create_task(expire())

    async def emit(kind: str, content: object, step: int = 0) -> None:
        nonlocal partial_content, partial_summary, complete_summary
        check_cancelled(cancel_event)
        if kind == "content" and isinstance(content, str):
            partial_content += content
        elif kind == "summary_delta" and isinstance(content, str):
            partial_summary += content
        elif kind == "summary" and isinstance(content, str):
            complete_summary = content
        if kind == "step" and conversation_id is not None:
            await asyncio.to_thread(chat_store.save, conversation_id, "tool", str(content), "step", step)
        await queue.put(_frame(task_id, kind, content, step))

    try:
        conversation_id = await asyncio.to_thread(chat_store.prepare, user_id, body)
        await asyncio.to_thread(chat_store.save, conversation_id, "user", body.message, "user")
        await emit("conversation", conversation_id)
        stream = ModelStream(model, emit, usage, cancel_event)
        context = RunContext(body, history, locale, stream, tools, emit, cancel_event)
        result = await run_graph(context)
        check_cancelled(cancel_event)
        if result["intent"] is not None:
            await asyncio.to_thread(chat_store.set_intent, user_id, conversation_id, result["intent"])
        if result["clarification"] is not None:
            kind = "clarify"
            content = json.dumps(result["clarification"], ensure_ascii=False)
        else:
            kind = "content" if result["intent"] == "simple_chat" else "summary"
            content = result["answer"]
        check_cancelled(cancel_event)
        await asyncio.to_thread(chat_store.finalize_run, user_id, conversation_id, task_id,
                                usage, "done", content, kind,
                                {"completedWriteCount": tools.completed_write_count})
        await queue.put(_frame(task_id, "usage", usage.model_dump(), 0))
        await queue.put(_frame(task_id, "done", None, 0))
    except RunAborted as error:
        reason = "timeout" if timeout_fired else error.reason
        logger.info("Chat run aborted taskId=%s reason=%s", task_id, reason)
        if conversation_id is not None:
            content = complete_summary if complete_summary is not None else partial_summary or partial_content
            kind = "summary" if complete_summary is not None else "aborted"
            details: dict[str, object] = {"reason": reason, "completedWriteCount": tools.completed_write_count}
            if tools.interruption is not None:
                details["databaseInterruption"] = tools.interruption
            try:
                await asyncio.to_thread(chat_store.finalize_run, user_id, conversation_id, task_id,
                                        usage, "aborted", content, kind, details)
                await queue.put(_frame(task_id, "usage", usage.model_dump(), 0))
            except Exception as persistence_error:  # noqa: BLE001 - terminal SSE must still be sent
                logger.error("Chat abort persistence failed taskId=%s errorType=%s",
                             task_id, type(persistence_error).__name__)
        await queue.put(_frame(task_id, "aborted", None, 0))
    except asyncio.CancelledError:
        cancel_event.set()
        raise
    except Exception as error:  # noqa: BLE001 - stream errors need an SSE terminal event
        logger.error("Chat run failed taskId=%s errorType=%s", task_id, type(error).__name__)
        if isinstance(error, BusinessError):
            public_error = translate(error.message, locale, *error.message_args)
        elif isinstance(error, UnsafeStatement):
            public_error = str(error)
        elif isinstance(error, (ValueError, TypeError)):
            public_error = "The model returned an invalid response."
        else:
            public_error = f"Chat request failed (taskId: {task_id})."
        if conversation_id is not None:
            try:
                await asyncio.to_thread(chat_store.finalize_run, user_id, conversation_id, task_id,
                                        usage, "error", public_error, "error",
                                        {"completedWriteCount": tools.completed_write_count})
                await queue.put(_frame(task_id, "usage", usage.model_dump(), 0))
            except Exception as persistence_error:  # noqa: BLE001 - terminal SSE must still be sent
                logger.error("Chat failure persistence failed taskId=%s errorType=%s",
                             task_id, type(persistence_error).__name__)
        await queue.put(_frame(task_id, "error", public_error, 0))
        await queue.put(_frame(task_id, "done", None, 0))
    finally:
        timer.cancel()
        await queue.put(None)


@router.post("")
async def chat(body: ChatRequest, request: Request, user: CurrentUser,
               session: DatabaseSession) -> StreamingResponse:
    _check_resources(session, user.id, body)
    if body.conversation_id is not None:
        previous = await asyncio.to_thread(chat_store.history, user.id, body.conversation_id)
    else:
        previous = []
    active = model_config.resolve_active_model(session, user.id)
    model = CompatibleChatModel(base_url=active.base_url, api_key=active.api_key,
                                model_name=active.model_name)
    locale = request.headers.get("accept-language", "en")
    queue: asyncio.Queue[bytes | None] = asyncio.Queue()
    cancel_event = threading.Event()

    async def events() -> AsyncIterator[bytes]:
        producer = asyncio.create_task(_produce(queue, user.id, body, previous, locale,
                                                model, active.context_window, cancel_event))
        _active_producers.add(producer)
        producer.add_done_callback(_active_producers.discard)
        last_sent = monotonic()
        try:
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=0.1)
                except TimeoutError:
                    if await request.is_disconnected():
                        break
                    if monotonic() - last_sent >= SSE_KEEPALIVE_SECONDS:
                        yield b": keepalive\n\n"
                        last_sent = monotonic()
                    continue
                if item is None:
                    break
                yield item
                last_sent = monotonic()
        finally:
            cancel_event.set()
            try:
                await asyncio.shield(producer)
            except asyncio.CancelledError:
                pass

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/conversations")
def conversations(user: CurrentUser) -> dict[str, object]:
    return success(chat_store.conversations(user.id))


@router.get("/conversations/{conversation_id}/messages")
def messages(conversation_id: int, user: CurrentUser) -> dict[str, object]:
    return success(chat_store.messages(user.id, conversation_id))


@router.delete("/conversations/{conversation_id}")
def delete_conversation(conversation_id: int, user: CurrentUser) -> dict[str, object]:
    chat_store.remove(user.id, conversation_id)
    return success()
