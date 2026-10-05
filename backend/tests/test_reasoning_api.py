"""HTTP provider -> observed graph -> SSE -> durable replay, including terminals."""

import json

import pytest
from fastapi.testclient import TestClient
from test_chat_api import parse_events, reply
from test_model_protocol import Provider, frame

from app.agent.cancellation import RunAborted
from app.agent.types import Usage
from app.api import chat
from app.models import DbConfig, User
from app.services import chat_store, database_tools
from app.services.chat_records import ReplayRecord

pytest_plugins = ["test_chat_api"]


def stream_reply(content: str, reasoning: list[str], *, tool: str | None = None,
                 args: dict[str, object] | None = None) -> list[bytes]:
    parts = [frame({"usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8}})]
    parts += [frame({"choices": [{"delta": {"reasoning_content": part}}]}) for part in reasoning]
    delta: dict[str, object] = {"content": content}
    if tool is not None:
        delta["tool_calls"] = [{"index": 0, "id": tool,
                                "function": {"name": tool, "arguments": json.dumps(args)}}]
    return [*parts, frame({"choices": [{"delta": delta}]}), frame("[DONE]")]


def selected_database(user: User) -> int:
    with chat_store.SessionLocal() as session:
        selected = DbConfig(user_id=user.id, name="selected", db_type="mysql",
                            host="localhost", port=3306, db_name="test", username="u", status=1)
        session.add(selected)
        session.commit()
        return selected.id


def goal(db_id: int) -> str:
    return json.dumps({"mode": "statement_execution", "dbIds": [db_id],
        "tableScope": [{"dbId": db_id, "tables": None}], "confidence": 0.95,
        "needsClarification": False, "reasoning": "PRIVATE_GOAL_BODY"})


def history(client: TestClient, events: list[dict[str, object]]) -> list[dict[str, object]]:
    conversation_id = events[0]["content"]
    return client.get(f"/api/chat/conversations/{conversation_id}/messages").json()["data"]


@pytest.mark.parametrize("confirmed", [False, True])
def test_two_decisions_and_final_reasoning_replay_in_order(
    chat_client: tuple[object, User, User, DbConfig], provider: Provider,
    monkeypatch: pytest.MonkeyPatch, confirmed: bool,
) -> None:
    client, user, _, _foreign = chat_client
    assert isinstance(client, TestClient)
    db_id = selected_database(user)
    monkeypatch.setattr(database_tools, "get_schema", lambda *_: {"tables": [], "incomplete": False})
    monkeypatch.setattr(database_tools, "execute_statement", lambda *_args, **_kwargs:
                        {"success": True, "rowCount": 1, "data": [{"value": 1}]})
    internal = goal(db_id) if confirmed else json.dumps({"intent": "sql_query", "confidence": 0.95,
        "reasoning": "public classification", "needsClarification": False, "taskGoal": json.loads(goal(db_id))})
    provider.replies = [
        stream_reply(internal, ["PRIVATE_INTERNAL_REASONING"]),
        stream_reply("PRIVATE_DECISION", ["inspect ", "schema"], tool="executeSql",
                     args={"db_id": db_id, "statement": "SELECT 1"}),
        stream_reply("PRIVATE_SECOND_DECISION", ["verify ", "results"], tool="doTerminate",
                     args={"reason": "done"}),
        stream_reply(json.dumps({"report": "Verified one row.", "complete": True}), ["final ", "check"]),
    ]
    body: dict[str, object] = {"message": "Query one row", "dbConfigIds": [db_id]}
    if confirmed:
        body["confirmedIntent"] = "sql_query"
    response = client.post("/api/chat", json=body)
    events = parse_events(response.text)
    assert events[-1]["type"] == "done" and not any(event["type"] == "error" for event in events)
    assert "PRIVATE_" not in response.text and "DSML" not in response.text
    rows = history(client, events)
    reasoning_rows = [row for row in rows if row["type"] == "reasoning"]
    assert [(row["step"], row["content"]) for row in reasoning_rows] == [
        (0, "inspect schema"), (1, "verify results"), (2, "final check"),
    ]
    assert all(row["reasoningContent"] is None for row in reasoning_rows)
    assert [row["type"] for row in rows] == [
        "user", "step", "reasoning", "step", "reasoning", "step", "reasoning", "summary",
    ]
    assert "PRIVATE_" not in json.dumps(rows) and rows[-1]["content"] == "Verified one row."
    usage = next(event["content"] for event in events if event["type"] == "usage")
    assert usage["callCount"] == 4 and usage["totalTokens"] == usage["conversationTotalTokens"] == 32
    assert provider.requests[0]["thinking"] == {"type": "disabled"}
    assert all("thinking" not in payload for payload in provider.requests[1:])
    effective = chat_store.history(user.id, int(events[0]["content"]))
    assert [message.content for message in effective] == ["Query one row", "Verified one row."]


def test_no_reasoning_provider_produces_no_replay_block(
    chat_client: tuple[object, User, User, DbConfig], provider: Provider,
) -> None:
    client, _, _, _foreign = chat_client
    assert isinstance(client, TestClient)
    provider.replies = [reply("Plain answer.")]
    response = client.post("/api/chat", json={"message": "hello", "confirmedIntent": "simple_chat"})
    events = parse_events(response.text)
    assert "reasoning" not in [event["type"] for event in events]
    assert [row["type"] for row in history(client, events)] == ["user", "content"]


@pytest.mark.parametrize("terminal", ["error", "aborted"])
def test_visible_reasoning_and_partial_survive_error_or_cancel(
    chat_client: tuple[object, User, User, DbConfig], provider: Provider,
    monkeypatch: pytest.MonkeyPatch, terminal: str,
) -> None:
    client, user, _, _foreign = chat_client
    assert isinstance(client, TestClient)
    original_frame = chat._frame
    observed_cancel = None
    original_graph = chat.run_graph

    async def observe(context: chat.RunContext):
        nonlocal observed_cancel
        observed_cancel = context.cancel_event
        return await original_graph(context)

    def cancel_after_frame(task_id: str, kind: str, content: object, step: int) -> bytes:
        packet = original_frame(task_id, kind, content, step)
        if terminal == "aborted" and kind == "content":
            assert observed_cancel is not None
            observed_cancel.set()
        return packet

    monkeypatch.setattr(chat, "run_graph", observe)
    monkeypatch.setattr(chat, "_frame", cancel_after_frame)
    provider.replies = [[
        frame({"usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8}}),
        frame({"choices": [{"delta": {"reasoning_content": "shown "}}]}),
        frame({"choices": [{"delta": {"reasoning_content": "reason", "content": "partial"}}]}),
        frame({"error": {"message": "PRIVATE_PROVIDER_ERROR"}}) if terminal == "error" else frame("[DONE]"),
    ]]
    response = client.post("/api/chat", json={"message": "hello", "confirmedIntent": "simple_chat"})
    events = parse_events(response.text)
    assert terminal in [event["type"] for event in events]
    rows = history(client, events)
    assert [(row["type"], row["content"]) for row in rows[:2]] == [
        ("user", "hello"), ("reasoning", "shown reason"),
    ]
    assert rows[-1]["type"] == terminal and "PRIVATE_PROVIDER_ERROR" not in json.dumps(rows)
    if terminal == "aborted":
        assert rows[-1]["content"] == "partial"
    effective = chat_store.history(user.id, int(events[0]["content"]))
    assert [message.content for message in effective] == ["hello"]
    usage = next(event["content"] for event in events if event["type"] == "usage")
    assert usage["callCount"] == 1 and usage["totalTokens"] == 8


def test_terminal_race_does_not_replay_or_charge_twice(
    chat_client: tuple[object, User, User, DbConfig], provider: Provider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _, _, _foreign = chat_client
    assert isinstance(client, TestClient)
    original_finalize = chat_store.finalize_run
    attempts: list[str] = []

    def race_finalize(user_id: int, conversation_id: int, task_id: str, usage: Usage,
                      status: str, content: str, kind: str, details: dict[str, object] | None = None,
                      records: list[ReplayRecord] | None = None) -> bool:
        attempts.append(status)
        result = original_finalize(user_id, conversation_id, task_id, usage, status,
                                   content, kind, details, records)
        if status == "done":
            raise RunAborted("cancelled")
        return result

    monkeypatch.setattr(chat_store, "finalize_run", race_finalize)
    provider.replies = [stream_reply("Finished.", ["first ", "then finish"])]
    events = parse_events(client.post("/api/chat", json={
        "message": "hello", "confirmedIntent": "simple_chat",
    }).text)
    rows = history(client, events)
    assert attempts == ["done", "aborted"]
    assert [(row["type"], row["content"]) for row in rows] == [
        ("user", "hello"), ("reasoning", "first then finish"), ("content", "Finished."),
    ]
    listed = client.get("/api/chat/conversations").json()["data"]
    assert listed[0]["totalTokens"] == 8


def test_flush_failure_reports_diagnostic_and_terminal(
    chat_client: tuple[object, User, User, DbConfig], provider: Provider,
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    client, _, _, _foreign = chat_client
    assert isinstance(client, TestClient)

    def fail(*_args: object, **_kwargs: object) -> bool:
        raise RuntimeError("PRIVATE_STORAGE_FAILURE")

    monkeypatch.setattr(chat_store, "finalize_run", fail)
    provider.replies = [stream_reply("Answer.", ["actual reasoning"])]
    response = client.post("/api/chat", json={"message": "hello", "confirmedIntent": "simple_chat"})
    kinds = [event["type"] for event in parse_events(response.text)]
    assert kinds[-2:] == ["error", "done"] and "reasoning" in kinds
    assert "Chat failure persistence failed" in caplog.text and "errorType=RuntimeError" in caplog.text
    assert "PRIVATE_STORAGE_FAILURE" not in response.text + caplog.text
