"""Real TCP disconnect propagates through ASGI to disposable PG/MySQL queries."""

import asyncio
import json
import os
import socket
import sqlite3
import threading
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import monotonic
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import httpx
import pytest
import uvicorn
from pydantic import SecretStr
from sqlalchemy import create_engine, event, select
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session, sessionmaker
from test_model_protocol import Provider, frame

from app.adapters import DbConnectionConfig, get_adapter
from app.adapters.relational import RelationalAdapter
from app.api import auth as api_auth
from app.core import auth as core_auth
from app.core.config import get_settings
from app.core.database import Base
from app.core.security import encrypt, token_digest
from app.main import app
from app.models import AuthSession, Conversation, DbConfig, Message, User
from app.services import chat_store, database_tools, model_config


def _target(db_type: str) -> DbConnectionConfig:
    prefix = "SQLCHAT_TEST_PG" if db_type == "postgresql" else "SQLCHAT_TEST_MYSQL"

    def required(key: str) -> str:
        value = os.environ.get(f"{prefix}_{key}")
        if value is None:
            pytest.skip(f"{db_type} disposable target credentials are required")
        return value

    return DbConnectionConfig(db_type, required("HOST"), int(required("PORT")),
                              required("DB"), required("USER"), required("PASSWORD"))


@pytest.fixture
def provider() -> Iterator[Provider]:
    service = Provider([])
    thread = threading.Thread(target=service.serve_forever, daemon=True)
    thread.start()
    yield service
    service.shutdown()
    service.server_close()
    thread.join(timeout=2)


def _tool(name: str, args: dict[str, object]) -> list[bytes]:
    return [frame({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": uuid4().hex,
             "function": {"name": name, "arguments": json.dumps(args)}}]}}]}),
            frame({"usage": {"prompt_tokens": 4, "completion_tokens": 2}}), frame("[DONE]")]


def _active_sql(config: DbConnectionConfig, marker: str) -> set[int]:
    adapter = get_adapter(config.db_type)
    assert isinstance(adapter, RelationalAdapter)
    with adapter._connection(config, 5) as connection:
        if config.db_type == "postgresql":
            # SQLAlchemy's stream_results issues FETCH; the original SELECT is not
            # visible in pg_stat_activity while its backend waits in pg_sleep.
            activity = connection.exec_driver_sql(
                "SELECT pid, application_name, wait_event, query FROM pg_stat_activity "
                "WHERE state = 'active' AND pid <> pg_backend_pid()"
            )
            return {int(row[0]) for row in activity
                    if row[1] == marker and row[2] == "PgSleep" and str(row[3]).startswith("FETCH ")}
        activity = connection.exec_driver_sql("SHOW FULL PROCESSLIST")
        return {int(row._mapping["Id"]) for row in activity
                if marker in str(row._mapping["Info"]) and "SLEEP" in str(row._mapping["Info"]).upper()}


async def _until(predicate: Callable[[], bool], timeout: float = 8) -> bool:
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        if await asyncio.to_thread(predicate):
            return True
        await asyncio.sleep(0.05)
    return False


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


async def _serve(port: int) -> tuple[uvicorn.Server, threading.Thread]:
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, lifespan="off",
                                            log_level="error", access_log=False))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    if not await _until(lambda: server.started, timeout=5):
        raise RuntimeError("Test ASGI server did not start")
    return server, thread


def _terminal(factory: sessionmaker[Session], user_id: int) -> tuple[Conversation, Message] | None:
    with factory() as session:
        conversation = session.scalar(select(Conversation).where(Conversation.user_id == user_id))
        if conversation is None:
            return None
        terminal = session.scalar(select(Message).where(Message.conversation_id == conversation.id,
                                                        Message.type == "aborted"))
        if terminal is None:
            return None
        session.expunge(conversation)
        session.expunge(terminal)
        return conversation, terminal


@pytest.mark.asyncio
@pytest.mark.parametrize("db_type", ["postgresql", "mysql"])
async def test_client_disconnect_cancels_real_slow_sql_and_keeps_committed_write(
    db_type: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, provider: Provider,
) -> None:
    target = _target(db_type)
    adapter = get_adapter(db_type)
    assert isinstance(adapter, RelationalAdapter)
    suffix = uuid4().hex[:12]
    table = f"s08_disconnect_{suffix}"
    marker = f"s08_slow_{suffix}"
    if db_type == "postgresql":
        original_timeout = adapter._set_timeout

        def mark_query_session(connection: Connection, timeout_seconds: int, trial_mode: bool) -> None:
            original_timeout(connection, timeout_seconds, trial_mode)
            connection.exec_driver_sql(f"SET LOCAL application_name = '{marker}'")

        monkeypatch.setattr(adapter, "_set_timeout", mark_query_session)
    with adapter._connection(target, 10) as connection:
        qualified = adapter._qualified_name(connection, table)
        connection.exec_driver_sql(f"CREATE TABLE {qualified} (id INT PRIMARY KEY, label VARCHAR(30))")
        connection.commit()
    try:
        engine = create_engine(f"sqlite:///{tmp_path / 'system.db'}",
                               connect_args={"check_same_thread": False})

        @event.listens_for(engine, "connect")
        def attach(dbapi_connection: object, _record: object) -> None:
            if not isinstance(dbapi_connection, sqlite3.Connection):
                raise TypeError("Expected SQLite system connection")
            dbapi_connection.execute("ATTACH DATABASE ? AS app", (str(tmp_path / "app.db"),))

        Base.metadata.create_all(engine)
        factory = sessionmaker(engine, expire_on_commit=False)
        monkeypatch.setattr(get_settings(), "encrypt_key", "0123456789abcdef0123456789abcdef")
        monkeypatch.setattr(get_settings(), "trial_enabled", False)
        monkeypatch.setattr(get_settings(), "query_timeout_seconds", 30)
        for module in (api_auth, core_auth, chat_store, database_tools):
            monkeypatch.setattr(module, "SessionLocal", factory)
        provider_port = provider.server_port
        monkeypatch.setattr(model_config, "resolve_active_model", lambda _session, _user: SimpleNamespace(
            base_url=f"http://127.0.0.1:{provider_port}", api_key=SecretStr("local-test"),
            model_name="test", context_window=8192,
        ))
        token = uuid4().hex
        with factory() as session:
            user = User(username=f"s08_{suffix}", password_hash="unused", status=1)
            session.add(user)
            session.flush()
            config = DbConfig(user_id=user.id, name="disposable", db_type=db_type,
                              host=target.host, port=target.port, db_name=target.db_name,
                              username=target.username, password_encrypted=encrypt(target.password), status=1)
            now = datetime.now(UTC).replace(tzinfo=None)
            session.add_all([config, AuthSession(token_hash=token_digest(token), user_id=user.id,
                                                 expires_at=now + timedelta(hours=1), last_active_at=now)])
            session.commit()
            user_id, db_id = user.id, config.id

        insert = f"INSERT INTO {qualified} (id, label) VALUES (1, 'committed')"
        sleeper = "pg_sleep" if db_type == "postgresql" else "SLEEP"
        slow = f"SELECT {sleeper}(20) AS slept, '{marker}' AS marker"
        provider.replies = [_tool("executeSql", {"db_id": db_id, "statement": insert}),
                            _tool("executeSql", {"db_id": db_id, "statement": slow}),
                            _tool("executeSql", {"db_id": db_id, "statement": f"SELECT * FROM {qualified}"})]
        port = _free_port()
        server, thread = await _serve(port)
        try:
            async with (
                httpx.AsyncClient(timeout=httpx.Timeout(30, connect=5)) as client,
                client.stream("POST", f"http://127.0.0.1:{port}/api/chat",
                              headers={"Authorization": f"Bearer {token}"},
                              json={"message": marker, "dbConfigIds": [db_id],
                                    "confirmedIntent": "sql_query"}) as response,
            ):
                assert response.status_code == 200
                active_ids: set[int] = set()

                def slow_query_started() -> bool:
                    active_ids.update(_active_sql(target, marker))
                    return bool(active_ids)

                if not await _until(slow_query_started, timeout=10):
                    with factory() as diagnostic_session:
                        diagnostic = [(row.type, row.content[:180]) for row in diagnostic_session.scalars(
                            select(Message).order_by(Message.id))]
                    pytest.fail(f"Slow {db_type} query never became active; "
                                f"model calls={len(provider.requests)}; messages={diagnostic}")
                await response.aclose()  # Close the real TCP response while SQL is active.
            assert await _until(lambda: _terminal(factory, user_id) is not None, timeout=10)
            assert await _until(lambda: active_ids.isdisjoint(_active_sql(target, marker)), timeout=5)
            assert len(provider.requests) == 2  # No follow-on SELECT or summary model call.
            terminal_pair = _terminal(factory, user_id)
            assert terminal_pair is not None
            conversation, terminal = terminal_pair
            assert conversation.total_tokens == 12
            assert terminal.metadata_json["runStatus"] == "aborted"
            assert terminal.metadata_json["completedWriteCount"] == 1
            interruption = cast("dict[str, object]", terminal.metadata_json["databaseInterruption"])
            assert interruption["cancelRequestSent"] is True, interruption
            if db_type == "postgresql":
                assert interruption["serverTerminationConfirmed"] is True, interruption
            assert interruption["writeOutcomeUnknown"] is False
            with factory() as session:
                rows = list(session.scalars(select(Message).where(Message.conversation_id == conversation.id)))
                assert sum(row.type == "aborted" for row in rows) == 1
                assert not any(row.type in {"summary", "content"} for row in rows)
            committed = adapter.execute(target, f"SELECT label FROM {qualified} WHERE id = 1")
            assert committed["data"] == [{"label": "committed"}]
        finally:
            server.should_exit = True
            await asyncio.to_thread(thread.join, 5)
            engine.dispose()
    finally:
        with adapter._connection(target, 10) as connection:
            connection.exec_driver_sql(f"DROP TABLE IF EXISTS {qualified}")
            connection.commit()
