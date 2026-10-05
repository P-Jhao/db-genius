"""Public SSE and real SQLite history omit the final-report envelope."""

import json
from typing import cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from task_goal_fixtures import goal_reply
from test_chat_api import parse_events
from test_final_report_api import final_reply
from test_model_parameters import tool_reply
from test_model_protocol import Provider

from app.agent.final_report import REPORT_CONTRACT
from app.agent.types import Usage
from app.models import Conversation, DbConfig, Message, User
from app.services import chat_store, database_tools

pytest_plugins = ["test_chat_api"]


@pytest.mark.parametrize("variant", ["valid", "extra", "missing-complete", "missing-report", "renamed"])
def test_fieldset_failures_keep_one_write_once_usage_and_safe_stored_terminal(
    chat_client: tuple[object, User, User, DbConfig], provider: Provider,
    monkeypatch: pytest.MonkeyPatch, variant: str,
) -> None:
    client, user, _second, _foreign = chat_client
    assert isinstance(client, TestClient)
    session_factory = cast(sessionmaker[Session], chat_store.__dict__["SessionLocal"])
    with session_factory() as session:
        selected = DbConfig(user_id=user.id, name="selected", db_type="postgresql",
                            host="localhost", port=5432, db_name="test", username="u", status=1)
        session.add(selected)
        session.commit()
        db_id = selected.id
    statements: list[str] = []

    def execute(_user: int, _db: int, statement: str, **_kwargs: object) -> dict[str, object]:
        statements.append(statement)
        return {"success": True, "affectedRows": 1}

    monkeypatch.setattr(database_tools, "get_schema", lambda *_args: {"tables": []})
    monkeypatch.setattr(database_tools, "execute_statement", execute)
    text = '已验证写入。 "quoted" \\ path\n```sql\n-- Manual review\n```\nRemaining work is unfinished.'
    envelope: dict[str, object] = {"report": text, "complete": True}
    if variant == "extra":
        envelope["private_status_marker"] = "SYNTHETIC_PRIVATE_FIELD_VALUE"
    elif variant == "missing-complete":
        del envelope["complete"]
    elif variant == "missing-report":
        del envelope["report"]
    elif variant == "renamed":
        envelope["answer"] = envelope.pop("report")
    provider.replies = [goal_reply([db_id]),
        tool_reply("executeSql", {"db_id": db_id, "statement": "INSERT INTO t VALUES (1)"}),
        tool_reply("doTerminate", {"reason": "Done"}), final_reply(json.dumps(envelope)),
    ]
    response = client.post("/api/chat", json={"message": "Insert", "dbConfigIds": [db_id],
                                               "confirmedIntent": "sql_query"})
    assert response.status_code == 200
    events = parse_events(response.text)
    kinds = [event["type"] for event in events]
    assert kinds[-1] == "done" and kinds.count("done") == kinds.count("usage") == 1
    assert statements == ["INSERT INTO t VALUES (1)"] and len(provider.requests) == 4
    usage = next(event["content"] for event in events if event["type"] == "usage")
    assert isinstance(usage, dict) and set(usage) == set(Usage().model_dump())
    assert usage["callCount"] == 4 and usage["totalTokens"] == usage["conversationTotalTokens"] == 24
    conversation_id = events[0]["content"]
    assert isinstance(conversation_id, int)
    history = client.get(f"/api/chat/conversations/{conversation_id}/messages").json()["data"]
    assert isinstance(history, list)
    with session_factory() as session:
        terminal = list(session.scalars(select(Message).where(
            Message.conversation_id == conversation_id, Message.step == -1, Message.role == "assistant",
        )))
        conversation = session.get(Conversation, conversation_id)
        assert conversation is not None and conversation.total_tokens == 24
        finalized_ids = conversation.metadata_json["finalizedTaskIds"]
        assert isinstance(finalized_ids, list) and len(finalized_ids) == len(terminal) == 1
        details = terminal[0].metadata_json
        stored_usage = details["usage"]
        assert isinstance(stored_usage, dict)
        assert details["completedWriteCount"] == 1 and stored_usage["callCount"] == 4
        assert details["runStatus"] == ("done" if variant == "valid" else "error")
    stored_terminal = [item for item in history if item["role"] == "assistant" and item["step"] == -1]
    assert len(stored_terminal) == 1
    if variant == "valid":
        assert kinds.count("summary") == 1 and "error" not in kinds
        assert stored_terminal[0]["type"] == "summary" and stored_terminal[0]["content"] == text
        assert "".join(str(event["content"]) for event in events if event["type"] == "summary_delta") == text
    else:
        assert "summary" not in kinds and kinds.count("error") == 1
        public_error = next(event["content"] for event in events if event["type"] == "error")
        assert stored_terminal[0]["type"] == "error" and stored_terminal[0]["content"] == public_error
        assert isinstance(public_error, str) and "does not roll back completed writes" in public_error
    public_and_history = response.text + json.dumps(history, ensure_ascii=False)
    assert all(private not in public_and_history for private in (
        REPORT_CONTRACT, '"complete"', "private_status_marker", "SYNTHETIC_PRIVATE_FIELD_VALUE",
        "envelopeIssue", "field_set", "Formatting-only example",
    ))
    final_messages = provider.requests[-1]["messages"]
    assert isinstance(final_messages, list) and final_messages[-1]["content"] == REPORT_CONTRACT
