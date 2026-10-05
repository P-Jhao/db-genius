"""Replay flush shares the terminal usage ledger and transaction."""

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.agent.types import ChatRequest, Usage
from app.models import Conversation, Message
from app.services import chat_store
from app.services.chat_records import ReplayRecord

pytest_plugins = ["test_chat_abort"]


def test_replay_flush_keeps_order_and_duplicate_terminals_add_nothing(
    store: tuple[int, sessionmaker[Session]],
) -> None:
    user_id, factory = store
    conversation_id = chat_store.prepare(user_id, ChatRequest(message="hello"))
    records = [ReplayRecord("assistant", "plan first", "reasoning", 0, 1),
               ReplayRecord("tool", "executed", "step", 1),
               ReplayRecord("assistant", "summarize", "reasoning", 1, 2)]
    usage = Usage()
    usage.record({"input_tokens": 5, "output_tokens": 3, "total_tokens": 8})
    assert chat_store.finalize_run(user_id, conversation_id, "once", usage, "done",
                                   "answer", "summary", records=records)
    assert not chat_store.finalize_run(user_id, conversation_id, "once", usage, "aborted",
                                       "partial", "aborted", records=records)
    with factory() as session:
        rows = list(session.query(Message).order_by(Message.id))
        assert [(row.type, row.content) for row in rows] == [
            ("reasoning", "plan first"), ("step", "executed"), ("reasoning", "summarize"),
            ("summary", "answer"),
        ]
        assert rows[0].metadata_json == {"taskId": "once", "runStatus": "done", "modelCallId": 1}
        conversation = session.get(Conversation, conversation_id)
        assert conversation is not None and conversation.total_tokens == 8
    assert [message.content for message in chat_store.history(user_id, conversation_id)] == ["answer"]


def test_failed_replay_flush_rolls_back_records_terminal_and_usage(
    store: tuple[int, sessionmaker[Session]],
) -> None:
    user_id, factory = store
    conversation_id = chat_store.prepare(user_id, ChatRequest(message="hello"))
    records = [ReplayRecord("assistant", "valid", "reasoning", 0, 1),
               ReplayRecord("assistant", "internal", "classification", 0, 2)]
    usage = Usage(totalTokens=8)
    with pytest.raises(ValueError, match="Unsupported run replay record"):
        chat_store.finalize_run(user_id, conversation_id, "rollback", usage, "error", "failed",
                                "error", records=records)
    with factory() as session:
        assert session.query(Message).count() == 0
        conversation = session.get(Conversation, conversation_id)
        assert conversation is not None and conversation.total_tokens == 0
        assert "finalizedTaskIds" not in conversation.metadata_json
    assert chat_store.finalize_run(user_id, conversation_id, "rollback", usage, "aborted",
                                   "partial", "aborted", records=records[:1])
    assert chat_store.history(user_id, conversation_id) == []
