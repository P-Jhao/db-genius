"""S07 HTTP model to LangGraph to the isolated PostgreSQL database."""

import json
import os
import threading
from collections.abc import Iterator
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, delete, select
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session, sessionmaker
from task_goal_fixtures import goal_reply
from test_model_protocol import Provider, frame

from app.api.auth import database_session
from app.core.auth import current_user
from app.core.config import get_settings
from app.core.security import encrypt
from app.main import app
from app.models import Conversation, DbConfig, Message, User
from app.services import chat_store, database_tools, model_config


@pytest.fixture
def provider() -> Iterator[Provider]:
    service = Provider([])
    thread = threading.Thread(target=service.serve_forever, daemon=True)
    thread.start()
    yield service
    service.shutdown()
    service.server_close()
    thread.join(timeout=2)


def model_reply(content: str) -> list[bytes]:
    return [frame({"choices": [{"delta": {"content": content}}]}),
            frame({"usage": {"prompt_tokens": 6, "completion_tokens": 4, "total_tokens": 10}}),
            frame("[DONE]")]


def tool_reply(call_id: str, statement: str, db_id: int) -> list[bytes]:
    return [frame({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": call_id,
             "function": {"name": "executeSql", "arguments": json.dumps({"db_id": db_id,
                                                                      "statement": statement})}}]}}]}),
            frame("[DONE]")]


def events(response_text: str) -> list[dict[str, object]]:
    return [json.loads(line.removeprefix("data: ")) for line in response_text.splitlines()
            if line.startswith("data: ")]


@pytest.mark.parametrize("db_type", ["postgresql", "mysql"])
def test_real_insert_and_select_through_chat(db_type: str, provider: Provider,
                                             monkeypatch: pytest.MonkeyPatch) -> None:
    url = os.environ.get("SQLCHAT_TEST_DATABASE_URL")
    prefix = "SQLCHAT_TEST_PG" if db_type == "postgresql" else "SQLCHAT_TEST_MYSQL"
    values = {name: os.environ.get(f"{prefix}_{name}")
              for name in ("HOST", "PORT", "DB", "USER", "PASSWORD")}
    if url is None or any(value is None for value in values.values()):
        pytest.skip("Isolated system and target database credentials are required")
    monkeypatch.setenv("SQLCHAT_ENCRYPT_KEY", "0123456789abcdef0123456789abcdef")
    get_settings.cache_clear()
    engine = create_engine(url, connect_args={"options": "-csearch_path=app"})
    target_engine = create_engine(URL.create(
        "postgresql+psycopg" if db_type == "postgresql" else "mysql+pymysql",
        username=values["USER"], password=values["PASSWORD"], host=values["HOST"],
        port=int(values["PORT"]), database=values["DB"],
    ))
    factory = sessionmaker(engine, expire_on_commit=False)
    table = f"s07_{uuid4().hex[:12]}"
    qualified = f"public.{table}" if db_type == "postgresql" else table
    user_id = -1
    db_id = -1

    def session_override() -> Iterator[Session]:
        with factory() as session:
            yield session

    try:
        with target_engine.begin() as connection:
            connection.exec_driver_sql(f"CREATE TABLE {qualified} (id INTEGER PRIMARY KEY, label TEXT)")
        with factory() as session:
            user = User(username=f"s07_{uuid4().hex}", password_hash="unused", status=1)
            session.add(user)
            session.flush()
            config = DbConfig(user_id=user.id, name="s07 target", db_type=db_type,
                              host=values["HOST"], port=int(values["PORT"]), db_name=values["DB"],
                              username=values["USER"], password_encrypted=encrypt(values["PASSWORD"]), status=1)
            session.add(config)
            session.commit()
            user_id, db_id = user.id, config.id
        app.dependency_overrides[database_session] = session_override
        app.dependency_overrides[current_user] = lambda: user
        monkeypatch.setattr(chat_store, "SessionLocal", factory)
        monkeypatch.setattr(database_tools, "SessionLocal", factory)
        host, port = provider.server_address
        monkeypatch.setattr(model_config, "resolve_active_model", lambda _session, _user_id: SimpleNamespace(
            base_url=f"http://{host}:{port}", api_key=SecretStr("local-test"), model_name="test",
            context_window=8192,
        ))
        provider.replies = [goal_reply([db_id]),
            tool_reply("insert_1", f"INSERT INTO {qualified} VALUES (1, '真实结果')", db_id),
            model_reply("Inserted one row."),
            model_reply(json.dumps({"report": "Inserted one row.", "complete": True})),
            goal_reply([db_id]),
            tool_reply("select_1", f"SELECT COUNT(*) AS count FROM {qualified}", db_id),
            model_reply("There is one row."),
            model_reply(json.dumps({"report": "There is one row.", "complete": True})),
        ]
        client = TestClient(app)
        insert_response = client.post("/api/chat", json={"message": "Insert one row",
                                                        "dbConfigIds": [db_id],
                                                        "confirmedIntent": "sql_query"})
        insert_events = events(insert_response.text)
        assert insert_response.status_code == 200
        assert insert_events[-1]["type"] == "done"
        assert any(event["type"] == "step" and "affectedRows" in str(event["content"])
                   for event in insert_events)
        with target_engine.connect() as connection:
            assert connection.exec_driver_sql(f"SELECT COUNT(*) FROM {qualified}").scalar_one() == 1
        select_response = client.post("/api/chat", json={"message": "Count rows",
                                                        "dbConfigIds": [db_id],
                                                        "confirmedIntent": "sql_query"})
        select_events = events(select_response.text)
        assert select_events[-1]["type"] == "done"
        assert any(event["type"] == "step" and '"count": 1' in str(event["content"])
                   for event in select_events)
        assert any(event["type"] == "summary" and event["content"] == "There is one row."
                   for event in select_events)
        assert table in json.dumps(provider.requests[1]["messages"])
        assert len(provider.requests) == 8
    finally:
        app.dependency_overrides.clear()
        if user_id != -1:
            with factory() as session:
                ids = session.scalars(select(Conversation.id).where(Conversation.user_id == user_id)).all()
                if ids:
                    session.execute(delete(Message).where(Message.conversation_id.in_(ids)))
                    session.execute(delete(Conversation).where(Conversation.id.in_(ids)))
                session.execute(delete(DbConfig).where(DbConfig.user_id == user_id))
                session.execute(delete(User).where(User.id == user_id))
                session.commit()
        with target_engine.begin() as connection:
            connection.exec_driver_sql(f"DROP TABLE IF EXISTS {qualified}")
        target_engine.dispose()
        engine.dispose()
        get_settings.cache_clear()
