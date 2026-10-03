"""Comparison preserves POST SSE, usage, ownership and replay contracts."""

import json

import pytest
from fastapi.testclient import TestClient
from test_chat_api import parse_events, reply
from test_compare_graph import call
from test_model_protocol import Provider
from test_schema_diff import _column, _schema, _table

from app.core.auth import current_user
from app.main import app
from app.models import DbConfig, User
from app.services import chat_store, database_tools

pytest_plugins = ["test_chat_api"]


def _pair(user: User) -> tuple[int, int]:
    with chat_store.SessionLocal() as session:
        rows = [DbConfig(user_id=user.id, name=side, db_type="postgresql", host="localhost", port=5432,
                         db_name=side, username="unused", status=1) for side in ("pre", "test")]
        session.add_all(rows)
        session.commit()
        return rows[0].id, rows[1].id


def test_compare_sse_actual_diff_usage_and_replay(
    chat_client: tuple[object, User, User, DbConfig], provider: Provider, monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, owner, other, _foreign = chat_client
    assert isinstance(client, TestClient)
    pre_id, test_id = _pair(owner)
    schemas = {pre_id: _schema("pre", "postgresql", _table("orders", _column("id", "INTEGER", False))),
               test_id: _schema("test", "postgresql", _table("orders", _column("id", "INTEGER", False),
                                   _column("note", "TEXT", True)))}
    reads: list[int] = []

    def schema(user_id: int, db_id: int):
        assert user_id == owner.id
        reads.append(db_id)
        return schemas[db_id]

    monkeypatch.setattr(database_tools, "get_schema", schema)
    monkeypatch.setattr(database_tools, "execute_statement", lambda *_args, **_kwargs:
                        pytest.fail("Deployment SQL must remain a report"))
    provider.replies = [call("doTerminate", {"reason": "report ready"}, "done"),
                        reply("pre→test: add orders.note. Report SQL: ALTER TABLE orders ADD COLUMN note TEXT;")]
    response = client.post("/api/chat", json={"message": "Compare", "preDbConfigId": pre_id,
                          "testDbConfigId": test_id, "confirmedIntent": "db_compare"})
    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    events = parse_events(response.text)
    assert [event["type"] for event in events][-3:] == ["summary", "usage", "done"]
    assert [event["type"] for event in events].count("done") == 1
    assert reads == [pre_id, test_id]
    assert len(provider.requests) == 2
    steps = [event["content"] for event in events if event["type"] == "step"]
    assert any('"ADD_COLUMN"' in str(item) and '"note"' in str(item) for item in steps)
    usage = events[-2]["content"]
    assert isinstance(usage, dict)
    assert (usage["callCount"], usage["totalTokens"], usage["conversationTotalTokens"]) == (2, 8, 8)
    conversation_id = events[0]["content"]
    replay = client.get(f"/api/chat/conversations/{conversation_id}/messages").json()["data"]
    assert any(item["type"] == "summary" and "ALTER TABLE" in item["content"] for item in replay)
    app.dependency_overrides[current_user] = lambda: other
    assert client.get(f"/api/chat/conversations/{conversation_id}/messages").json()["code"] == 404


def test_request_cross_user_pair_is_denied_before_model(
    chat_client: tuple[object, User, User, DbConfig], provider: Provider,
) -> None:
    client, owner, _other, foreign = chat_client
    assert isinstance(client, TestClient)
    pre_id, _test_id = _pair(owner)
    response = client.post("/api/chat", json={"message": "Compare", "preDbConfigId": pre_id,
                          "testDbConfigId": foreign.id, "confirmedIntent": "db_compare"})
    assert response.json()["code"] == 404
    assert provider.requests == []


def test_model_wrong_pair_yields_one_error_terminal_without_summary(
    chat_client: tuple[object, User, User, DbConfig], provider: Provider, monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, owner, _other, _foreign = chat_client
    assert isinstance(client, TestClient)
    pre_id, test_id = _pair(owner)
    monkeypatch.setattr(database_tools, "get_schema", lambda _user, db_id:
                        _schema("pre" if db_id == pre_id else "test", "postgresql"))
    provider.replies = [call("compareDatabases", {"pre_id": test_id, "test_id": pre_id}, "reverse")]
    response = client.post("/api/chat", json={"message": "Compare", "preDbConfigId": pre_id,
                          "testDbConfigId": test_id, "confirmedIntent": "db_compare"})
    events = parse_events(response.text)
    kinds = [event["type"] for event in events]
    assert kinds[-3:] == ["usage", "error", "done"]
    assert kinds.count("done") == 1 and "summary" not in kinds
    assert len(provider.requests) == 1
    assert "direction differs" in json.dumps(events)
