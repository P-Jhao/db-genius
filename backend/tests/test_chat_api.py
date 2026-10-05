"""POST SSE and history through FastAPI, a local HTTP model, and a real SQL store."""

import json
import threading
from collections.abc import Iterator
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from test_model_protocol import Provider, frame

from app.api.auth import database_session
from app.core.auth import current_user
from app.core.config import Settings
from app.core.database import Base
from app.main import app
from app.models import DbConfig, User
from app.services import chat_store, database_tools, model_config
from app.services.model_config import resolve_active_model


@pytest.fixture
def provider() -> Iterator[Provider]:
    service = Provider([])
    thread = threading.Thread(target=service.serve_forever, daemon=True)
    thread.start()
    yield service
    service.shutdown()
    service.server_close()
    thread.join(timeout=2)


@pytest.fixture
def chat_client(tmp_path: object, monkeypatch: pytest.MonkeyPatch, provider: Provider):
    from pathlib import Path

    directory = Path(str(tmp_path))
    engine = create_engine(f"sqlite:///{directory / 'main.db'}", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def attach(dbapi_connection: object, _record: object) -> None:
        dbapi_connection.execute("ATTACH DATABASE ? AS app", (str(directory / "app.db"),))

    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as session:
        first = User(username="first", password_hash="unused", status=1)
        second = User(username="second", password_hash="unused", status=1)
        session.add_all([first, second])
        session.flush()
        foreign_db = DbConfig(user_id=second.id, name="foreign", db_type="postgresql",
                              host="localhost", port=5432, db_name="test", username="u", status=1)
        session.add(foreign_db)
        session.commit()

    def session_override() -> Iterator[Session]:
        with factory() as session:
            yield session

    app.dependency_overrides[database_session] = session_override
    app.dependency_overrides[current_user] = lambda: first
    monkeypatch.setattr(chat_store, "SessionLocal", factory)
    host, port = provider.server_address
    monkeypatch.setattr(model_config, "resolve_active_model", lambda _session, _user_id: SimpleNamespace(
        base_url=f"http://{host}:{port}", api_key=SecretStr("local-test"), model_name="test",
        context_window=8192,
    ))
    try:
        yield TestClient(app), first, second, foreign_db
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def reply(content: str) -> list[bytes]:
    return [frame({"choices": [{"delta": {"content": content}}]}),
            frame({"usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8}}),
            frame("[DONE]")]


def parse_events(text: str) -> list[dict[str, object]]:
    return [json.loads(line.removeprefix("data: ")) for line in text.splitlines() if line.startswith("data: ")]


def test_sse_history_continue_ownership_and_delete(chat_client: tuple[object, User, User, DbConfig],
                                                    provider: Provider) -> None:
    client, _first, second, foreign_db = chat_client
    assert isinstance(client, TestClient)
    provider.replies = [
        reply(json.dumps({"intent": "simple_chat", "confidence": 0.95,
                          "reasoning": "general", "needsClarification": False})),
        reply("First answer."),
        reply("Second answer."),
    ]
    first_response = client.post("/api/chat", json={"message": "first"})
    assert first_response.status_code == 200
    assert "text/event-stream" in first_response.headers["content-type"]
    assert first_response.headers["x-accel-buffering"] == "no"
    first_events = parse_events(first_response.text)
    assert [event["type"] for event in first_events] == [
        "conversation", "classifying", "classified", "routing", "thinking", "content", "usage", "done",
    ]
    conversation_id = first_events[0]["content"]
    assert isinstance(conversation_id, int)
    assert first_events[-2]["content"]["conversationTotalTokens"] == 16
    second_response = client.post("/api/chat", json={"message": "second", "conversationId": conversation_id,
                                                    "confirmedIntent": "simple_chat"})
    second_events = parse_events(second_response.text)
    assert [event["type"] for event in second_events] == ["conversation", "routing", "thinking",
                                                           "content", "usage", "done"]
    assert second_events[-2]["content"]["conversationTotalTokens"] == 24
    sent = provider.requests[-1]["messages"]
    assert isinstance(sent, list)
    assert [message["content"] for message in sent if message["role"] in ("user", "assistant")] == [
        "first", "First answer.", "second",
    ]
    messages = client.get(f"/api/chat/conversations/{conversation_id}/messages").json()["data"]
    assert [(message["role"], message["content"]) for message in messages] == [
        ("user", "first"), ("assistant", "First answer."),
        ("user", "second"), ("assistant", "Second answer."),
    ]
    listed = client.get("/api/chat/conversations").json()["data"]
    assert len(listed) == 1 and listed[0]["totalTokens"] == 24
    app.dependency_overrides[current_user] = lambda: second
    assert client.get(f"/api/chat/conversations/{conversation_id}/messages").json()["code"] == 404
    assert client.delete(f"/api/chat/conversations/{conversation_id}").json()["code"] == 404
    app.dependency_overrides[current_user] = lambda: _first
    assert client.post("/api/chat", json={"message": "hello", "dbConfigIds": [foreign_db.id],
                                           "confirmedIntent": "simple_chat"}).json()["code"] == 404
    assert len(provider.requests) == 3
    assert client.delete(f"/api/chat/conversations/{conversation_id}").json()["code"] == 200
    assert client.get("/api/chat/conversations").json()["data"] == []


def test_tool_internal_error_is_not_exposed(chat_client: tuple[object, User, User, DbConfig],
                                            provider: Provider, monkeypatch: pytest.MonkeyPatch) -> None:
    client, user, _second, _foreign = chat_client
    assert isinstance(client, TestClient)
    with chat_store.SessionLocal() as session:
        selected = DbConfig(user_id=user.id, name="selected", db_type="postgresql",
                            host="localhost", port=5432, db_name="test", username="u", status=1)
        session.add(selected)
        session.commit()
        db_id = selected.id

    monkeypatch.setattr(database_tools, "get_schema", lambda _user, _db: {"tables": [], "incomplete": False})

    def fail(_user: int, _db: int, _statement: str) -> dict[str, object]:
        raise RuntimeError("secret-driver-diagnostic")

    monkeypatch.setattr(database_tools, "execute_statement", fail)
    provider.replies = [[frame({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_1",
        "function": {"name": "executeSql", "arguments": json.dumps({"db_id": db_id,
                                                                 "statement": "SELECT 1"})}}]}}]}),
        frame("[DONE]")]]
    response = client.post("/api/chat", json={"message": "query", "dbConfigIds": [db_id],
                                               "confirmedIntent": "sql_query"})
    stream_events = parse_events(response.text)
    assert [event["type"] for event in stream_events][-3:] == ["usage", "error", "done"]
    assert "secret-driver-diagnostic" not in response.text
    conversation_id = stream_events[0]["content"]
    history = client.get(f"/api/chat/conversations/{conversation_id}/messages").json()["data"]
    assert "secret-driver-diagnostic" not in json.dumps(history)


def test_builtin_window_matches_active_response_sse_and_governance(
    chat_client: tuple[object, User, User, DbConfig], provider: Provider, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api import chat

    client, _user, _second, _foreign = chat_client
    assert isinstance(client, TestClient)
    host, port = provider.server_address
    monkeypatch.setenv("SQLCHAT_DEFAULT_MODEL_API_KEY", "synthetic-key")
    settings = Settings(_env_file=None, default_model_base_url=f"http://{host}:{port}",
                        default_model_context_window=16384)
    monkeypatch.setattr(model_config, "get_settings", lambda: settings)
    monkeypatch.setattr(model_config, "resolve_active_model", resolve_active_model)
    original_graph = chat.run_graph
    observed_windows: list[int | None] = []

    async def observe_graph(context: chat.RunContext):
        observed_windows.append(context.model_stream.usage.contextWindow)
        return await original_graph(context)

    monkeypatch.setattr(chat, "run_graph", observe_graph)
    active = client.get("/api/model-config/active").json()["data"]
    assert active["id"] is None and active["contextWindow"] == 16384
    provider.replies = [reply("Configured window answer.")]
    response = client.post("/api/chat", json={"message": "hello", "confirmedIntent": "simple_chat"})
    events = parse_events(response.text)
    assert events[-1]["type"] == "done"
    assert events[-2]["content"]["contextWindow"] == active["contextWindow"]
    assert observed_windows == [active["contextWindow"]]
