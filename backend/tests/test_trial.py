"""Public trial status and intent guards at HTTP and graph boundaries."""

import json
import sqlite3
import threading
from collections.abc import Iterator
from types import SimpleNamespace
from typing import cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from test_model_protocol import Provider, frame, model

from app.agent.graph import RunContext, run_graph
from app.agent.streaming import ModelStream
from app.agent.tools import RunTools
from app.agent.types import ChatRequest, Usage
from app.api.auth import database_session
from app.core.auth import current_user
from app.core.config import get_settings
from app.core.database import Base
from app.core.errors import BusinessError
from app.core.security import decrypt
from app.main import app
from app.models import DbConfig, User
from app.services import db_config_init


@pytest.fixture
def trial_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "trial_enabled", True)


@pytest.fixture
def provider() -> Iterator[Provider]:
    service = Provider([])
    thread = threading.Thread(target=service.serve_forever, daemon=True)
    thread.start()
    yield service
    service.shutdown()
    service.server_close()
    thread.join(timeout=2)


def _response(content: str) -> list[bytes]:
    return [frame({"choices": [{"delta": {"content": content}}]}), frame("[DONE]")]


def test_trial_status_is_public_and_reflects_runtime_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    client = TestClient(app)
    monkeypatch.setattr(get_settings(), "trial_enabled", False)
    assert client.get("/api/trial/status").json() == {
        "code": 200, "message": "success", "data": {"trialEnabled": False},
    }
    monkeypatch.setattr(get_settings(), "trial_enabled", True)
    assert client.get("/api/trial/status").json()["data"] == {"trialEnabled": True}


@pytest.mark.parametrize("intent", ["workflow", "db_compare"])
def test_confirmed_trial_intent_denied_before_resource_or_model_resolution(
    trial_mode: None, intent: str,
) -> None:
    app.dependency_overrides[current_user] = lambda: SimpleNamespace(id=7)
    app.dependency_overrides[database_session] = lambda: None
    try:
        response = TestClient(app).post("/api/chat", json={"message": "run", "confirmedIntent": intent})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["code"] == 403
    assert response.json()["data"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("intent", ["workflow", "db_compare"])
async def test_classified_trial_intent_denied_before_route_and_tools(
    trial_mode: None, provider: Provider, intent: str,
) -> None:
    provider.replies = [_response(json.dumps({
        "intent": intent, "taskGoal": None, "confidence": 0.99, "reasoning": "requested", "needsClarification": False,
    }))]
    events: list[str] = []

    async def emit(kind: str, _content: object, _step: int) -> None:
        events.append(kind)

    request = ChatRequest.model_validate({
        "message": "run", "dbConfigIds": [12], "preDbConfigId": 12, "testDbConfigId": 13,
    })
    context = RunContext(request, [], "en", ModelStream(model(provider), emit, Usage()),
                         RunTools(7, request), emit)
    with pytest.raises(BusinessError) as captured:
        await run_graph(context)
    assert captured.value.code == 403
    assert events == ["classifying", "classified"]
    assert len(provider.requests) == 1


@pytest.mark.asyncio
async def test_trial_still_allows_general_chat(trial_mode: None, provider: Provider) -> None:
    provider.replies = [_response("A general answer.")]

    async def emit(_kind: str, _content: object, _step: int) -> None:
        pass

    request = ChatRequest.model_validate({"message": "hello", "confirmedIntent": "simple_chat"})
    context = RunContext(request, [], "en", ModelStream(model(provider), emit, Usage()),
                         RunTools(7, request), emit)
    result = await run_graph(context)
    assert result["answer"] == "A general answer."


def test_trial_initializer_creates_one_encrypted_builtin(
    trial_mode: None, monkeypatch: pytest.MonkeyPatch, tmp_path: object,
) -> None:
    from pathlib import Path

    directory = Path(str(tmp_path))
    engine = create_engine(f"sqlite:///{directory / 'main.db'}")

    @event.listens_for(engine, "connect")
    def attach(dbapi_connection: sqlite3.Connection, _record: object) -> None:
        dbapi_connection.execute("ATTACH DATABASE ? AS app", (str(directory / "app.db"),))

    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    settings = get_settings()
    monkeypatch.setattr(settings, "trial_builtin_host", "127.0.0.1")
    monkeypatch.setattr(settings, "trial_builtin_username", "reader")
    monkeypatch.setattr(settings, "trial_builtin_password", "secret")
    monkeypatch.setattr(settings, "encrypt_key", "0123456789abcdef0123456789abcdef")
    queued: list[tuple[int, int]] = []
    monkeypatch.setattr(db_config_init, "_enqueue", lambda _session, db_id, version:
                        queued.append((db_id, version)))
    try:
        with factory() as session:
            db_config_init.initialize_trial_database(session)
            assert session.scalars(select(DbConfig)).all() == []
            session.add(User(username=settings.bootstrap_username, password_hash="unused", status=1))
            session.commit()
            db_config_init.initialize_trial_database(session)
            db_config_init.initialize_trial_database(session)
            configs = session.scalars(select(DbConfig)).all()
            assert len(configs) == 1
            assert configs[0].builtin and configs[0].db_type == "mysql"
            assert configs[0].host == "127.0.0.1"
            assert configs[0].password_encrypted != "secret"
            assert configs[0].password_encrypted is not None
            assert decrypt(configs[0].password_encrypted) == "secret"
            assert queued == [(configs[0].id, 1)]
            builtin = configs[0]
            encrypted_before = builtin.password_encrypted
            builtin.name = "Display name retained"
            builtin.status = 1
            builtin.doc_content = "old schema"
            builtin.verification_error = "old failure"
            session.add(DbConfig(user_id=builtin.user_id, name="user-owned", db_type="mysql",
                                 host="user-host", port=3306, db_name="user-db", username="user",
                                 builtin=False, verification_version=9, status=1, doc_content="user schema"))
            session.commit()
            db_config_init.initialize_trial_database(session)
            assert builtin.status == 1 and builtin.doc_content == "old schema"
            assert builtin.password_encrypted == encrypted_before
            assert len(queued) == 1
            monkeypatch.setattr(settings, "trial_builtin_host", "sqlchat-demo-mysql")
            monkeypatch.setattr(settings, "trial_builtin_port", 3307)
            monkeypatch.setattr(settings, "trial_builtin_db_name", "blog-v2")
            monkeypatch.setattr(settings, "trial_builtin_username", "reader-v2")
            monkeypatch.setattr(settings, "trial_builtin_password", "new-secret")
            db_config_init.initialize_trial_database(session)
            assert builtin.host == "sqlchat-demo-mysql" and builtin.port == 3307
            assert builtin.db_name == "blog-v2" and builtin.username == "reader-v2"
            assert builtin.name == "Display name retained"
            assert builtin.verification_version == 2 and builtin.status == 0
            assert builtin.doc_content is None and builtin.doc_generated_at is None
            assert builtin.verification_error is None
            assert decrypt(builtin.password_encrypted) == "new-secret"
            assert queued == [(builtin.id, 1), (builtin.id, 2)]
            from app.services.db_config import _finish_sync
            assert not _finish_sync(session, builtin.id, 1, document="stale schema", failure=None)
            assert builtin.doc_content is None and builtin.verification_version == 2
            assert _finish_sync(session, builtin.id, 2, document="new schema", failure=None)
            db_config_init.initialize_trial_database(session)
            assert len(queued) == 2 and builtin.doc_content == "new schema"
            custom = session.scalar(select(DbConfig).where(DbConfig.builtin.is_(False)))
            assert custom is not None
            assert (custom.host, custom.verification_version, custom.doc_content) == ("user-host", 9, "user schema")
    finally:
        engine.dispose()


def test_trial_initializer_skips_incomplete_connection(
    trial_mode: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "trial_builtin_host", "")
    db_config_init.initialize_trial_database(cast(Session, object()))
