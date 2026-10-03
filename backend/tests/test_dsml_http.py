"""DSML decisions and summary cleanup across POST SSE and persisted history."""

import json
import threading

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker
from test_chat_api import parse_events
from test_dsml import _reply, _sql_text
from test_model_protocol import Provider, frame

from app.models import DbConfig, User
from app.services import chat_store, database_tools

pytest_plugins = ["test_chat_api"]


def selected_database(user: User) -> int:
    factory: sessionmaker[Session] = chat_store.SessionLocal  # type: ignore[attr-defined]
    with factory() as session:
        config = DbConfig(user_id=user.id, name="fixture", db_type="postgresql", host="localhost",
                          port=5432, db_name="fixture", username="fixture", status=1)
        session.add(config)
        session.commit()
        return config.id


@pytest.mark.parametrize("final_protocol", [False, True])
def test_recovered_call_and_split_final_summary_match_history(
    chat_client: tuple[TestClient, User, User, DbConfig], provider: Provider,
    monkeypatch: pytest.MonkeyPatch, final_protocol: bool,
) -> None:
    client, user, _, _foreign = chat_client
    db_id = selected_database(user)
    calls: list[str] = []
    monkeypatch.setattr(database_tools, "get_schema", lambda _user, _db: {"tables": [], "incomplete": False})

    def execute(_user: int, _db: int, statement: str,
                cancel_event: threading.Event | None = None) -> dict[str, object]:
        calls.append(statement)
        return {"success": True, "rowCount": 1, "data": [{"value": 1}]}

    monkeypatch.setattr(database_tools, "execute_statement", execute)
    protocol = _sql_text(db_id=str(db_id))
    first = frame({"choices": [{"delta": {"content": protocol, "tool_calls": [{"index": 0,
        "id": "original_id", "function": {"name": "executeSql", "arguments": ""}}]}}]})
    report = "One row. " + (protocol if final_protocol else "") + " Verified."
    wire = json.dumps({"report": report, "complete": True})
    provider.replies = [[first[:8], first[8:53], first[53:], frame("[DONE]")],
        [frame({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "end",
            "function": {"name": "doTerminate", "arguments": '{"reason":"verified"}'}}]}}]}),
         frame("[DONE]")],
        [frame({"choices": [{"delta": {"content": wire[index:index + 17]}}]})
         for index in range(0, len(wire), 17)]
        + [frame("[DONE]")]]
    response = client.post("/api/chat", json={"message": "query", "confirmedIntent": "sql_query",
                                             "dbConfigIds": [db_id]})
    events = parse_events(response.text)
    assert calls == ["SELECT 1"] and len(provider.requests) == 3
    streamed = "".join(str(event["content"]) for event in events if event["type"] == "summary_delta")
    final = [event["content"] for event in events if event["type"] == "summary"]
    assert "DSML" not in response.text and "original_id" not in response.text
    history = client.get(f"/api/chat/conversations/{events[0]['content']}/messages").json()["data"]
    if final_protocol:
        errors = [event["content"] for event in events if event["type"] == "error"]
        assert len(errors) == 1 and "final report could not be completed" in str(errors[0])
        assert final == [] and [event["type"] for event in events][-3:] == ["usage", "error", "done"]
        assert history[-1]["content"] == errors[0] and history[-1]["type"] == "error"
    else:
        assert not any(event["type"] == "error" for event in events)
        assert streamed == "One row.  Verified." and final == [streamed]
        assert history[-1]["content"] == streamed and history[-1]["type"] == "summary"
    sent = provider.requests[1]["messages"]
    assert isinstance(sent, list)
    assistant = next(message for message in sent if message.get("tool_calls"))
    tool = next(message for message in sent if message["role"] == "tool")
    assert assistant["tool_calls"][0]["id"] == tool["tool_call_id"] == "original_id"


@pytest.mark.parametrize("invalid", ["", "<｜｜DSML｜｜tool_calls><｜｜DSML｜｜invoke broken"])
def test_invalid_model_never_claims_success_or_executes_query(
    chat_client: tuple[TestClient, User, User, DbConfig], provider: Provider,
    monkeypatch: pytest.MonkeyPatch, invalid: str,
) -> None:
    client, user, _, _foreign = chat_client
    db_id = selected_database(user)
    monkeypatch.setattr(database_tools, "get_schema", lambda _user, _db: {"tables": [], "incomplete": False})

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("Malformed provider tool text must not execute")

    monkeypatch.setattr(database_tools, "execute_statement", forbidden)
    provider.replies = [_reply(invalid)]
    response = client.post("/api/chat", json={"message": "query", "confirmedIntent": "sql_query",
                                             "dbConfigIds": [db_id]})
    events = parse_events(response.text)
    assert [event["type"] for event in events][-3:] == ["usage", "error", "done"]
    assert not any(event["type"] in {"summary", "summary_delta"} for event in events)
    history = client.get(f"/api/chat/conversations/{events[0]['content']}/messages").json()["data"]
    assert history[-1]["type"] == "error" and "DSML" not in json.dumps(history)
