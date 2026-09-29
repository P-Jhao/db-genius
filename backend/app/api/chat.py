"""Authenticated REST history and POST SSE chat endpoints."""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from time import time_ns
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from langchain_core.messages import BaseMessage
from sqlalchemy import select

from app.adapters.safety import UnsafeStatement
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
                   context_window: int | None) -> None:
    task_id = uuid4().hex
    usage = Usage(contextWindow=context_window)
    conversation_id: int | None = None

    async def emit(kind: str, content: object, step: int = 0) -> None:
        if kind == "step" and conversation_id is not None:
            await asyncio.to_thread(chat_store.save, conversation_id, "tool", str(content), "step", step)
        await queue.put(_frame(task_id, kind, content, step))

    try:
        conversation_id = await asyncio.to_thread(chat_store.prepare, user_id, body)
        await emit("conversation", conversation_id)
        await asyncio.to_thread(chat_store.save, conversation_id, "user", body.message, "user")
        stream = ModelStream(model, emit, usage)
        context = RunContext(body, history, locale, stream, RunTools(user_id, body), emit)
        result = await run_graph(context)
        if result["intent"] is not None:
            await asyncio.to_thread(chat_store.set_intent, user_id, conversation_id, result["intent"])
        if result["clarification"] is not None:
            await asyncio.to_thread(chat_store.save, conversation_id, "assistant",
                                    json.dumps(result["clarification"], ensure_ascii=False), "clarify")
        elif result["answer"]:
            kind = "content" if result["intent"] == "simple_chat" else "summary"
            await asyncio.to_thread(chat_store.save, conversation_id, "assistant", result["answer"], kind)
        await asyncio.to_thread(chat_store.update_usage, user_id, conversation_id, usage)
        await emit("usage", usage.model_dump())
        await emit("done", None)
    except asyncio.CancelledError:
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
                await asyncio.to_thread(chat_store.save, conversation_id, "assistant", public_error, "error")
                await asyncio.to_thread(chat_store.update_usage, user_id, conversation_id, usage)
                await emit("usage", usage.model_dump())
            except Exception:
                logger.exception("Chat failure persistence failed taskId=%s", task_id)
        await emit("error", public_error)
        await emit("done", None)
    finally:
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

    async def events() -> AsyncIterator[bytes]:
        producer = asyncio.create_task(_produce(queue, user.id, body, previous, locale,
                                                model, active.context_window))
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield item
        finally:
            if not producer.done():
                producer.cancel()
            try:
                await producer
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
