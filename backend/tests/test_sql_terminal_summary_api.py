"""Direct SQL report framing, reasoning order and durable history through HTTP."""

import json
from itertools import count
from types import SimpleNamespace
from uuid import UUID

import pytest
from chat_terminal_fixtures import DRAFT, REPORT, configure_paging, reasoning_reply, replies, schema
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from test_chat_api import parse_events, reply
from test_final_report_api import final_reply
from test_model_parameters import tool_reply
from test_model_protocol import Provider
from test_reasoning_api import history, selected_database

from app.agent import output_guard
from app.agent.final_report import REPORT_CONTRACT
from app.models import DbConfig, User
from app.services import chat_store, database_tools, model_config

pytest_plugins = ["test_chat_api"]


@pytest.mark.parametrize("terminal", ["valid", "length", "unclosed"])
@pytest.mark.parametrize("refresh_schema", [False, True])
def test_direct_report_after_simple_history_keeps_framing_and_reasoning(
    chat_client: tuple[object, User, User, DbConfig], provider: Provider,
    monkeypatch: pytest.MonkeyPatch, terminal: str, refresh_schema: bool,
) -> None:
    client, user, _, _ = chat_client
    assert isinstance(client, TestClient)
    db_id = selected_database(user)
    configure_paging(monkeypatch)
    active_model = model_config.resolve_active_model

    def large_context(session: Session, user_id: int) -> SimpleNamespace:
        configured = active_model(session, user_id)
        return SimpleNamespace(base_url=configured.base_url, api_key=configured.api_key,
                               model_name=configured.model_name, context_window=100000)

    monkeypatch.setattr(model_config, "resolve_active_model", large_context)
    monkeypatch.setattr(database_tools, "get_schema", lambda *_: schema())

    def forbidden(*_args: object, **_kwargs: object) -> None:
        pytest.fail("Metadata task cannot execute a statement")

    monkeypatch.setattr(database_tools, "execute_statement", forbidden)
    provider.replies = [reply("请选择数据源，我无法访问数据库。")]
    first = parse_events(client.post("/api/chat", json={
        "message": "有哪些表", "confirmedIntent": "simple_chat"}).text)
    conversation_id = first[0]["content"]
    assert isinstance(conversation_id, int)
    terminal_replies = replies(db_id, terminate=False)
    if refresh_schema:
        identities = count(1)
        monkeypatch.setattr(output_guard, "uuid4", lambda: UUID(int=next(identities)))
        terminal_replies.insert(1, tool_reply("getDatabaseSchema", {"db_id": db_id}))
    if terminal == "length":
        terminal_replies[-1] = reasoning_reply(
            json.dumps({"report": REPORT, "complete": True}), "final check")
        terminal_replies[-1][-2] = final_reply("", "length")[-2]
    elif terminal == "unclosed":
        terminal_replies[-1] = reasoning_reply('{"report":"Partial result', "final check")
    provider.replies = list(terminal_replies)
    response = client.post("/api/chat", json={"message": "有哪些表？", "dbConfigIds": [db_id],
        "confirmedIntent": "sql_query", "conversationId": conversation_id})
    assert response.status_code == 200
    events = parse_events(response.text)
    rows = history(client, events)
    assert len(provider.requests) == 8 + int(refresh_schema) and not provider.replies
    assert events[-1]["type"] == "done"
    kinds = [event["type"] for event in events]
    assert kinds.count("usage") == kinds.count("done") == 1
    terminal_rows = [row for row in rows if row["step"] == -1 and row["role"] == "assistant"]
    assert len(terminal_rows) == 2
    assert [(row["step"], row["content"]) for row in rows if row["type"] == "reasoning"] == [
        (4 + int(refresh_schema), "schema inspection complete"), (4 + int(refresh_schema), "final check")]
    assert [row["type"] for row in rows] == ["user", "content", "user", *(["step"] if refresh_schema else []),
        "step", "step", "step",
        "step", "step", "reasoning", "reasoning", "summary" if terminal == "valid" else "error"]
    messages = provider.requests[-1]["messages"]
    assert isinstance(messages, list) and messages[-1]["content"] == REPORT_CONTRACT
    assert "tools" not in provider.requests[-1] and DRAFT not in json.dumps(messages, ensure_ascii=False)
    assert any(message["content"] == "请选择数据源，我无法访问数据库。" for message in messages)
    assert REPORT_CONTRACT not in response.text and '"complete"' not in response.text
    assert DRAFT not in response.text and DRAFT not in json.dumps(rows, ensure_ascii=False)
    if terminal == "valid":
        assert "error" not in kinds and kinds.count("summary") == 1
        summary = next(event["content"] for event in events if event["type"] == "summary")
        assert summary == terminal_rows[-1]["content"] == REPORT
        assert "".join(str(event["content"]) for event in events
                       if event["type"] == "summary_delta") == REPORT
        assert [message.content for message in chat_store.history(user.id, conversation_id)] == [
            "有哪些表", "请选择数据源，我无法访问数据库。", "有哪些表？", REPORT]
    else:
        assert "summary" not in kinds and kinds.count("error") == 1
        public_error = next(event["content"] for event in events if event["type"] == "error")
        assert terminal_rows[-1]["content"] == public_error
        assert terminal_rows[-1]["type"] == "error"
