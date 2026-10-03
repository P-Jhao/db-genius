"""S08 cancellation and terminal accounting at the graph and persistence boundaries."""

import asyncio
import json
import sqlite3
import threading
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import cast

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGenerationChunk, ChatResult
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from test_model_protocol import Provider, frame, model

from app.adapters.cancellation import DatabaseExecutionInterrupted
from app.agent.cancellation import RunAborted
from app.agent.graph import RunContext, run_graph
from app.agent.model import CompatibleChatModel
from app.agent.streaming import ModelStream
from app.agent.tools import RunTools
from app.agent.types import ChatRequest, Usage
from app.api import chat
from app.core.database import Base
from app.models import Conversation, Message, User
from app.services import chat_store, database_tools


@pytest.fixture
def provider() -> Iterator[Provider]:
    service = Provider([])
    thread = threading.Thread(target=service.serve_forever, daemon=True)
    thread.start()
    yield service
    service.shutdown()
    service.server_close()
    thread.join(timeout=2)


def reply(content: str, *, usage: bool = True) -> list[bytes]:
    packets = [frame({"choices": [{"delta": {"content": content}}]})]
    if usage:
        packets.append(frame({"usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6}}))
    return [*packets, frame("[DONE]")]


def tool_reply(name: str, args: dict[str, object]) -> list[bytes]:
    return [frame({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": name,
             "function": {"name": name, "arguments": json.dumps(args)}}]}}]}), frame("[DONE]")]


@pytest.mark.asyncio
async def test_abort_during_classification_stops_model_call(provider: Provider) -> None:
    cancel = threading.Event()
    kinds: list[str] = []

    async def emit(kind: str, _content: object, _step: int) -> None:
        kinds.append(kind)
        if kind == "classifying":
            cancel.set()

    request = ChatRequest.model_validate({"message": "query"})
    context = RunContext(request, [], "en", ModelStream(model(provider), emit, Usage(), cancel),
                         RunTools(1, request, cancel), emit, cancel)
    with pytest.raises(RunAborted):
        await run_graph(context)
    assert kinds == ["classifying"]
    assert provider.requests == []


@pytest.mark.asyncio
async def test_abort_during_model_stream_closes_upstream(provider: Provider) -> None:
    cancel = threading.Event()
    provider.replies = [reply("partial", usage=False)]
    usage = Usage()
    kinds: list[str] = []

    async def emit(kind: str, _content: object, _step: int) -> None:
        kinds.append(kind)
        if kind == "content":
            cancel.set()

    request = ChatRequest.model_validate({"message": "hello", "confirmedIntent": "simple_chat"})
    context = RunContext(request, [], "en", ModelStream(model(provider), emit, usage, cancel),
                         RunTools(1, request, cancel), emit, cancel)
    with pytest.raises(RunAborted):
        await run_graph(context)
    assert kinds == ["routing", "thinking", "content"]
    assert len(provider.requests) == 1
    assert usage.callCount == 1
    assert usage.totalTokens == 0


@pytest.mark.asyncio
async def test_cancel_while_provider_is_stalled_closes_stream() -> None:
    started = asyncio.Event()
    closed = asyncio.Event()
    cancel = threading.Event()

    class StallingModel(BaseChatModel):
        @property
        def _llm_type(self) -> str:
            return "stalling-test-model"

        def _generate(self, messages: list[BaseMessage], stop: list[str] | None = None,
                      run_manager: object = None, **kwargs: object) -> ChatResult:
            raise RuntimeError("Only streaming is supported")

        async def _astream(self, messages: list[BaseMessage], stop: list[str] | None = None,
                           run_manager: object = None, **kwargs: object) -> AsyncIterator[ChatGenerationChunk]:
            started.set()
            try:
                await asyncio.Event().wait()
                yield ChatGenerationChunk(message=AIMessageChunk(content="late"))
            finally:
                closed.set()

    async def emit(_kind: str, _content: object, _step: int) -> None:
        pass

    usage = Usage()
    stream = ModelStream(StallingModel(), emit, usage, cancel)
    task = asyncio.create_task(stream.call([]))
    await asyncio.wait_for(started.wait(), 2)
    cancel.set()
    with pytest.raises(RunAborted):
        await asyncio.wait_for(task, 2)
    assert closed.is_set()
    assert usage.totalTokens == 0


@pytest.mark.asyncio
async def test_abort_in_sql_tool_records_uncertain_write_and_skips_summary(
    provider: Provider, monkeypatch: pytest.MonkeyPatch,
) -> None:
    cancel = threading.Event()
    provider.replies = [tool_reply("executeSql", {"db_id": 12, "statement": "UPDATE t SET a=1"})]
    monkeypatch.setattr(database_tools, "get_schema", lambda _user, _db: {"tables": []})
    observed: list[threading.Event | None] = []

    def interrupted(_user: int, _db: int, _sql: str,
                    cancel_event: threading.Event | None = None) -> dict[str, object]:
        observed.append(cancel_event)
        raise DatabaseExecutionInterrupted("cancelled", cancel_request_sent=True,
                                           server_termination_confirmed=False, write_outcome_unknown=True)

    monkeypatch.setattr(database_tools, "execute_statement", interrupted)

    async def emit(_kind: str, _content: object, _step: int) -> None:
        pass

    request = ChatRequest.model_validate({"message": "update", "dbConfigIds": [12],
                                          "confirmedIntent": "sql_query"})
    tools = RunTools(1, request, cancel)
    context = RunContext(request, [], "en", ModelStream(model(provider), emit, Usage(), cancel),
                         tools, emit, cancel)
    with pytest.raises(RunAborted):
        await run_graph(context)
    assert observed == [cancel]
    assert cancel.is_set()
    assert tools.interruption is not None
    assert tools.interruption["writeOutcomeUnknown"] is True
    assert len(provider.requests) == 1


@pytest.mark.asyncio
async def test_abort_during_summary_preserves_only_partial(provider: Provider,
                                                            monkeypatch: pytest.MonkeyPatch) -> None:
    cancel = threading.Event()
    provider.replies = [tool_reply("executeSql", {"db_id": 12, "statement": "SELECT 1"}),
                        tool_reply("doTerminate", {"reason": "done"}),
                        reply('{"report":"partial conclusion', usage=False)]
    monkeypatch.setattr(database_tools, "get_schema", lambda _user, _db: {"tables": []})
    monkeypatch.setattr(database_tools, "execute_statement", lambda _user, _db, _sql, **_kwargs:
                        {"success": True, "rowCount": 1, "data": [{"value": 1}]})
    kinds: list[str] = []

    async def emit(kind: str, _content: object, _step: int) -> None:
        kinds.append(kind)
        if kind == "summary_delta":
            cancel.set()

    request = ChatRequest.model_validate({"message": "select", "dbConfigIds": [12],
                                          "confirmedIntent": "sql_query"})
    context = RunContext(request, [], "en", ModelStream(model(provider), emit, Usage(), cancel),
                         RunTools(1, request, cancel), emit, cancel)
    with pytest.raises(RunAborted):
        await run_graph(context)
    assert len(provider.requests) == 3
    assert kinds.count("summary_delta") == 1
    assert "summary" not in kinds


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[int, sessionmaker[Session]]]:
    engine = create_engine(f"sqlite:///{tmp_path / 'chat.db'}", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def attach(dbapi_connection: object, _record: object) -> None:
        if not isinstance(dbapi_connection, sqlite3.Connection):
            raise TypeError("Expected SQLite connection")
        dbapi_connection.execute("ATTACH DATABASE ? AS app", (str(tmp_path / "app.db"),))

    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(chat_store, "SessionLocal", factory)
    with factory() as session:
        user = User(username="owner", password_hash="unused", status=1)
        session.add(user)
        session.commit()
        user_id = user.id
    yield user_id, factory
    engine.dispose()


@pytest.mark.asyncio
async def test_abort_persists_partial_once_and_known_usage_only(
    store: tuple[int, sessionmaker[Session]], monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id, factory = store
    cancel = threading.Event()
    usage_seen: Usage | None = None

    async def interrupted(context: RunContext) -> dict[str, object]:
        nonlocal usage_seen
        await context.emit("content", "partial answer", 0)
        context.model_stream.usage.record({"input_tokens": 3, "output_tokens": 2, "total_tokens": 5})
        usage_seen = context.model_stream.usage
        cancel.set()
        raise RunAborted("cancelled")

    monkeypatch.setattr(chat, "run_graph", interrupted)
    queue: asyncio.Queue[bytes | None] = asyncio.Queue()
    await chat._produce(queue, user_id, ChatRequest.model_validate({"message": "hello"}), [], "en",
                        cast(CompatibleChatModel, object()), None, cancel)
    frames: list[dict[str, object]] = []
    while (item := await queue.get()) is not None:
        frames.append(json.loads(item.decode().removeprefix("data: ")))
    assert [item["type"] for item in frames] == ["conversation", "content", "usage", "aborted"]
    assert usage_seen is not None and usage_seen.totalTokens == 5
    task_id = str(frames[0]["taskId"])
    conversation_id = frames[0]["content"]
    assert isinstance(conversation_id, int)
    assert not chat_store.finalize_run(user_id, conversation_id, task_id, usage_seen,
                                       "aborted", "duplicate", "aborted")
    with factory() as session:
        conversation = session.get(Conversation, conversation_id)
        assert conversation is not None and conversation.total_tokens == 5
        rows = list(session.query(Message).filter_by(conversation_id=conversation_id).order_by(Message.id))
        assert [(row.type, row.content) for row in rows] == [
            ("user", "hello"), ("aborted", "partial answer"),
        ]
        assert rows[-1].metadata_json["runStatus"] == "aborted"


@pytest.mark.parametrize(("status", "kind"), [("done", "content"), ("error", "error")])
def test_normal_and_error_terminal_are_idempotent(
    store: tuple[int, sessionmaker[Session]], status: str, kind: str,
) -> None:
    user_id, factory = store
    conversation_id = chat_store.prepare(user_id, ChatRequest.model_validate({"message": "hello"}))
    usage = Usage()
    usage.record({"input_tokens": 7, "output_tokens": 3, "total_tokens": 10})
    assert chat_store.finalize_run(user_id, conversation_id, "same-task", usage, status, "answer", kind)
    assert not chat_store.finalize_run(user_id, conversation_id, "same-task", usage, status, "again", kind)
    with factory() as session:
        conversation = session.get(Conversation, conversation_id)
        assert conversation is not None and conversation.total_tokens == 10
        rows = list(session.query(Message).filter_by(conversation_id=conversation_id))
        assert len(rows) == 1 and rows[0].content == "answer"


@pytest.mark.asyncio
async def test_request_timeout_sets_shared_signal_and_aborts(
    store: tuple[int, sessionmaker[Session]], monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id, factory = store
    cancel = threading.Event()
    monkeypatch.setattr(chat, "CHAT_REQUEST_TIMEOUT_SECONDS", 0.01)

    async def wait_for_timeout(_context: RunContext) -> dict[str, object]:
        while not cancel.is_set():
            await asyncio.sleep(0.01)
        raise RunAborted("cancelled")

    monkeypatch.setattr(chat, "run_graph", wait_for_timeout)
    queue: asyncio.Queue[bytes | None] = asyncio.Queue()
    await chat._produce(queue, user_id, ChatRequest.model_validate({"message": "slow"}), [], "en",
                        cast(CompatibleChatModel, object()), None, cancel)
    assert cancel.is_set()
    with factory() as session:
        terminal = session.query(Message).filter_by(type="aborted").one()
        assert terminal.metadata_json["reason"] == "timeout"
