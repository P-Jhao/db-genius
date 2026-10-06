"""Missing SQL resources terminate through real API persistence and can recover."""

import json
import threading

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from task_goal_fixtures import goal_reply, goal_value
from test_chat_api import parse_events, reply
from test_model_protocol import Provider, frame

from app.core.localization import translate
from app.models import Conversation, DbConfig, Message, User
from app.services import chat_store, database_tools

pytest_plugins = ["test_chat_api"]

type ClientFixture = tuple[TestClient, User, User, DbConfig]


def forbid_database_access(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*_args: object, **_kwargs: object) -> None:
        pytest.fail("Missing resources must be checked before database access")

    monkeypatch.setattr(database_tools, "get_schema", fail)
    monkeypatch.setattr(database_tools, "execute_statement", fail)


def error_terminal(events: list[dict[str, object]], locale: str) -> None:
    kinds = [event["type"] for event in events]
    assert kinds[-3:] == ["usage", "error", "done"]
    assert kinds.count("usage") == kinds.count("error") == kinds.count("done") == 1
    assert not set(kinds).intersection({"clarify", "routing", "step", "thinking", "summary", "content"})
    assert events[-2]["content"] == translate("error.chat.sqlQueryNoDbConfig", locale)
    assert events[-1]["content"] is None


def terminal_rows(conversation_id: int) -> tuple[list[Message], Conversation]:
    with chat_store.SessionLocal() as session:
        rows = list(session.scalars(select(Message).where(
            Message.conversation_id == conversation_id, Message.step == -1,
        ).order_by(Message.id)))
        conversation = session.get(Conversation, conversation_id)
        assert conversation is not None
        session.expunge_all()
        return rows, conversation


@pytest.mark.parametrize("database_ids", [None, []])
@pytest.mark.parametrize("locale", ["en", "zh-CN"])
def test_confirmed_sql_missing_database_is_one_persisted_zero_call_error(
    chat_client: ClientFixture, provider: Provider, monkeypatch: pytest.MonkeyPatch,
    database_ids: list[int] | None, locale: str,
) -> None:
    client, _user, _second, _foreign = chat_client
    forbid_database_access(monkeypatch)
    response = client.post("/api/chat", headers={"accept-language": locale}, json={
        "message": "Count orders", "confirmedIntent": "sql_query", "dbConfigIds": database_ids,
    })
    assert response.status_code == 200 and "text/event-stream" in response.headers["content-type"]
    events = parse_events(response.text)
    assert [event["type"] for event in events] == ["conversation", "usage", "error", "done"]
    error_terminal(events, locale)
    assert provider.requests == []
    usage = events[-3]["content"]
    assert isinstance(usage, dict)
    assert usage["callCount"] == usage["totalTokens"] == usage["conversationTotalTokens"] == 0
    conversation_id = events[0]["content"]
    assert isinstance(conversation_id, int)
    history = client.get(f"/api/chat/conversations/{conversation_id}/messages").json()["data"]
    assert [(message["role"], message["type"]) for message in history] == [
        ("user", "user"), ("assistant", "error"),
    ]
    assert history[-1]["content"] == events[-2]["content"]
    rows, conversation = terminal_rows(conversation_id)
    assert [row.type for row in rows] == ["user", "error"]
    details = rows[-1].metadata_json
    assert details["taskId"] == events[-1]["taskId"] and details["runStatus"] == "error"
    assert details["usage"]["callCount"] == details["usage"]["totalTokens"] == 0
    assert details["completedWriteCount"] == 0 and conversation.total_tokens == 0
    assert conversation.metadata_json["finalizedTaskIds"] == [events[-1]["taskId"]]


@pytest.mark.parametrize("goal_ids", [[], [999]])
def test_clear_sql_classification_errors_before_goal_clarification_or_authorization(
    chat_client: ClientFixture, provider: Provider, monkeypatch: pytest.MonkeyPatch,
    goal_ids: list[int],
) -> None:
    client, _user, _second, _foreign = chat_client
    forbid_database_access(monkeypatch)
    provider.replies = [reply(json.dumps({
        "intent": "sql_query", "confidence": 0.99, "needsClarification": False,
        "reasoning": "An explicit SQL query", "taskGoal": goal_value(goal_ids, clarify=not goal_ids),
    }))]
    response = client.post("/api/chat", json={"message": "Count orders", "dbConfigIds": []})
    events = parse_events(response.text)
    assert [event["type"] for event in events][:3] == ["conversation", "classifying", "classified"]
    error_terminal(events, "en")
    assert len(provider.requests) == 1 and provider.replies == []
    usage = events[-3]["content"]
    assert isinstance(usage, dict)
    assert usage["callCount"] == 1 and usage["totalTokens"] == usage["conversationTotalTokens"] == 8
    conversation_id = events[0]["content"]
    assert isinstance(conversation_id, int)
    rows, conversation = terminal_rows(conversation_id)
    assert [row.type for row in rows] == ["user", "error"]
    assert rows[-1].content == events[-2]["content"] and conversation.total_tokens == 8


def test_initial_clarify_then_confirmed_error_then_selected_database_recovers(
    chat_client: ClientFixture, provider: Provider, monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, user, _second, _foreign = chat_client
    forbid_database_access(monkeypatch)
    provider.replies = [reply(json.dumps({
        "intent": "sql_query", "confidence": 0.4, "needsClarification": False,
        "reasoning": "Ambiguous operation", "taskGoal": goal_value([], clarify=True),
    }))]
    first = parse_events(client.post("/api/chat", json={"message": "Maybe query"}).text)
    assert [event["type"] for event in first] == [
        "conversation", "classifying", "classified", "clarify", "usage", "done",
    ]
    conversation_id = first[0]["content"]
    assert isinstance(conversation_id, int)
    second = parse_events(client.post("/api/chat", json={
        "message": "Count orders", "confirmedIntent": "sql_query", "conversationId": conversation_id,
    }).text)
    error_terminal(second, "en")
    assert len(provider.requests) == 1
    assert second[-3]["content"]["callCount"] == second[-3]["content"]["totalTokens"] == 0
    assert second[-3]["content"]["conversationTotalTokens"] == 8
    with chat_store.SessionLocal() as session:
        selected = DbConfig(user_id=user.id, name="selected", db_type="postgresql", host="localhost",
                            port=5432, db_name="test", username="test", status=1)
        session.add(selected)
        session.commit()
        db_id = selected.id
    calls: list[str] = []

    def schema(_user: int, selected_id: int) -> dict[str, object]:
        assert selected_id == db_id
        calls.append("schema")
        return {"tables": [{"name": "orders", "columns": [{"name": "id"}]}]}

    def execute(_user: int, selected_id: int, statement: str, *,
                cancel_event: threading.Event) -> dict[str, object]:
        assert selected_id == db_id and statement == "SELECT COUNT(*) FROM orders"
        assert not cancel_event.is_set()
        calls.append("execute")
        return {"success": True, "rowCount": 1, "data": [{"count": 3}]}

    monkeypatch.setattr(database_tools, "get_schema", schema)
    monkeypatch.setattr(database_tools, "execute_statement", execute)
    provider.replies = [goal_reply([db_id]),
        [frame({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "count",
            "function": {"name": "executeSql", "arguments": json.dumps({"db_id": db_id,
                "statement": "SELECT COUNT(*) FROM orders"})}}]}}]}), frame("[DONE]")],
        reply("Draft that must not become the terminal answer."),
        reply(json.dumps({"report": "There are 3 orders.", "complete": True})),
    ]
    recovered = parse_events(client.post("/api/chat", json={
        "message": "Count orders using the selected database", "confirmedIntent": "sql_query",
        "conversationId": conversation_id, "dbConfigIds": [db_id],
    }).text)
    kinds = [event["type"] for event in recovered]
    assert "error" not in kinds and "clarify" not in kinds
    assert kinds[-3:] == ["summary", "usage", "done"] and kinds.count("summary") == 1
    assert recovered[-3]["content"] == "There are 3 orders."
    assert calls == ["schema", "execute"] and len(provider.requests) == 5 and provider.replies == []
    assert recovered[-2]["content"]["callCount"] == 4
    assert recovered[-2]["content"]["totalTokens"] == 22
    assert recovered[-2]["content"]["conversationTotalTokens"] == 30
    rows, conversation = terminal_rows(conversation_id)
    assert [row.type for row in rows] == ["user", "clarify", "user", "error", "user", "summary"]
    assert [row.metadata_json["runStatus"] for row in rows if row.role == "assistant"] == [
        "done", "error", "done",
    ]
    assert [row.metadata_json["usage"]["totalTokens"] for row in rows if row.role == "assistant"] == [8, 0, 22]
    task_ids = conversation.metadata_json["finalizedTaskIds"]
    assert len(task_ids) == len(set(task_ids)) == 3 and conversation.total_tokens == 30
    visible_history = client.get(f"/api/chat/conversations/{conversation_id}/messages").json()["data"]
    assert sum(message["type"] == "error" for message in visible_history) == 1
    assert "Draft that must not" not in json.dumps(visible_history)
    goal_messages = json.dumps(provider.requests[1]["messages"])
    assert translate("error.chat.sqlQueryNoDbConfig", "en") not in goal_messages


@pytest.mark.parametrize("intent", ["workflow", "db_compare"])
def test_other_database_intents_keep_existing_missing_resource_clarification(
    chat_client: ClientFixture, provider: Provider, monkeypatch: pytest.MonkeyPatch, intent: str,
) -> None:
    client, _user, _second, _foreign = chat_client
    forbid_database_access(monkeypatch)
    events = parse_events(client.post("/api/chat", json={
        "message": "Database task", "confirmedIntent": intent,
    }).text)
    assert [event["type"] for event in events] == ["conversation", "clarify", "usage", "done"]
    assert provider.requests == [] and events[-2]["content"]["callCount"] == 0
