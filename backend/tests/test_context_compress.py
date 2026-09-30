"""Manual and automatic summary compression through the real chat API."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from test_chat_api import parse_events, reply
from test_model_protocol import Provider

from app.agent.types import ChatRequest
from app.core.auth import current_user
from app.core.config import Settings
from app.main import app
from app.services import chat_store, context_compress

pytest_plugins = ["test_chat_api"]


def _conversation(user_id: int, count: int = 8) -> int:
    conversation_id = chat_store.prepare(user_id, ChatRequest(message="initial"))
    for index in range(count):
        if index % 2 == 0:
            chat_store.save(conversation_id, "user", f"question {index}", "user")
        else:
            chat_store.save(conversation_id, "assistant", f"answer {index}", "summary")
    chat_store.save(conversation_id, "tool", "hidden tool output", "step")
    chat_store.save(conversation_id, "assistant", "partial answer", "aborted")
    return conversation_id


def test_manual_compression_replay_and_followup(chat_client: tuple[object, object, object, object],
                                                 provider: Provider) -> None:
    client, owner, other, _ = chat_client
    assert isinstance(client, TestClient)
    conversation_id = _conversation(owner.id)
    provider.replies = [reply("## Goal\nEarlier questions and answers were about sales."),
                        reply("Answer after compression.")]

    result = client.post(f"/api/chat/conversations/{conversation_id}/compress",
                         json={"targetTokens": 100}).json()["data"]
    assert result["compressed"] is True
    assert isinstance(result["summaryMessageId"], int)
    assert result["beforeTokens"] > 0 and result["afterTokens"] > 0
    sent = provider.requests[0]
    assert sent["messages"][1]["content"].endswith(
        "Please try to keep the summary within about 100 tokens (a soft requirement — "
        "prioritize information completeness when it cannot be met)."
    )
    assert "question 0" in sent["messages"][1]["content"]
    assert "answer 1" in sent["messages"][1]["content"]
    assert "hidden tool output" not in sent["messages"][1]["content"]

    replay = client.get(f"/api/chat/conversations/{conversation_id}/messages").json()["data"]
    assert len(replay) == 11
    assert replay[0]["content"] == "question 0" and replay[0]["type"] == "compressed"
    assert replay[1]["content"] == "answer 1" and replay[1]["type"] == "compressed"
    assert replay[-1]["type"] == "summary" and replay[-1]["step"] == -2
    assert [item.content for item in chat_store.history(owner.id, conversation_id)] == [
        "Previous conversation summary:\n## Goal\nEarlier questions and answers were about sales.",
        *[f"question {index}" if index % 2 == 0 else f"answer {index}" for index in range(2, 8)],
    ]
    app.dependency_overrides[current_user] = lambda: other
    assert client.post(f"/api/chat/conversations/{conversation_id}/compress", json={}).status_code == 404
    app.dependency_overrides[current_user] = lambda: owner

    response = client.post("/api/chat", json={"message": "follow up", "conversationId": conversation_id,
                                               "confirmedIntent": "simple_chat"})
    assert [item["type"] for item in parse_events(response.text)][-2:] == ["usage", "done"]
    history_sent = provider.requests[-1]["messages"]
    assert history_sent[0]["role"] == "system" or history_sent[1]["role"] == "system"
    assert any("Previous conversation summary:" in item["content"] for item in history_sent)
    assert not any(item["content"] == "question 0" for item in history_sent)
    assert any(item["content"] == "follow up" for item in history_sent)


def test_failure_and_short_history_do_not_change_messages(chat_client: tuple[object, object, object, object],
                                                           provider: Provider) -> None:
    client, owner, _, _ = chat_client
    assert isinstance(client, TestClient)
    conversation_id = _conversation(owner.id)
    provider.replies = [503]
    before = client.get(f"/api/chat/conversations/{conversation_id}/messages").json()["data"]
    result = client.post(f"/api/chat/conversations/{conversation_id}/compress").json()["data"]
    assert result["compressed"] is False
    assert result["summaryMessageId"] is None
    assert "failed" in result["message"].lower()
    assert client.get(f"/api/chat/conversations/{conversation_id}/messages").json()["data"] == before
    assert chat_store.history(owner.id, conversation_id)[0].content == "question 0"

    short = _conversation(owner.id, 6)
    result = client.post(f"/api/chat/conversations/{short}/compress").json()["data"]
    assert result["compressed"] is False
    assert result["summaryMessageId"] is None
    assert len(provider.requests) == 1


def test_automatic_compression_threshold_and_default(chat_client: tuple[object, object, object, object],
                                                     provider: Provider,
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    client, owner, _, _ = chat_client
    assert isinstance(client, TestClient)
    assert Settings().context_auto_compress_enabled is False
    assert Settings().context_auto_compress_threshold == 0.8
    assert Settings().context_keep_last_messages == 6
    conversation_id = _conversation(owner.id)
    with chat_store.SessionLocal() as session:
        conversation = chat_store.owned(session, owner.id, conversation_id)
        conversation.context_tokens = 6554
        session.commit()
    monkeypatch.setattr(context_compress, "get_settings", lambda: SimpleNamespace(
        context_auto_compress_enabled=True, context_auto_compress_threshold=0.8,
        context_keep_last_messages=6,
    ))
    provider.replies = [reply("## Goal\nEarlier exchange summarized."), reply("Next answer.")]
    response = client.post("/api/chat", json={"message": "new question", "conversationId": conversation_id,
                                               "confirmedIntent": "simple_chat"})
    assert [item["type"] for item in parse_events(response.text)][-2:] == ["usage", "done"]
    assert len(provider.requests) == 2
    assert any("Earlier exchange summarized" in item["content"]
               for item in provider.requests[1]["messages"])
    assert "question 0" not in str(provider.requests[1]["messages"])


def test_automatic_failure_uses_uncompressed_history(chat_client: tuple[object, object, object, object],
                                                     provider: Provider,
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    client, owner, _, _ = chat_client
    assert isinstance(client, TestClient)
    conversation_id = _conversation(owner.id)
    with chat_store.SessionLocal() as session:
        conversation = chat_store.owned(session, owner.id, conversation_id)
        conversation.context_tokens = 7000
        session.commit()
    monkeypatch.setattr(context_compress, "get_settings", lambda: SimpleNamespace(
        context_auto_compress_enabled=True, context_auto_compress_threshold=0.8,
        context_keep_last_messages=6,
    ))
    provider.replies = [503, reply("Answer after compression failure.")]
    response = client.post("/api/chat", json={"message": "continue", "conversationId": conversation_id,
                                               "confirmedIntent": "simple_chat"})
    assert [item["type"] for item in parse_events(response.text)][-2:] == ["usage", "done"]
    assert "question 0" in str(provider.requests[1]["messages"])
    events = parse_events(response.text)
    notices = [event["content"] for event in events if event["type"] == "step"]
    assert any("Compression failed" in str(notice) for notice in notices)
    replay = client.get(f"/api/chat/conversations/{conversation_id}/messages").json()["data"]
    assert replay[0]["type"] == "user"
    assert any(item["type"] == "step" and "Compression failed" in item["content"] for item in replay)
    assert not any(item["step"] == -2 for item in replay)


def test_compression_rejects_changed_snapshot(chat_client: tuple[object, object, object, object]) -> None:
    _client, owner, _, _ = chat_client
    conversation_id = _conversation(owner.id)
    rows, _ = chat_store.context_snapshot(owner.id, conversation_id)
    chat_store.save(conversation_id, "user", "new concurrent message", "user")
    with pytest.raises(RuntimeError, match="changed during compression"):
        chat_store.apply_compression(owner.id, conversation_id, [row.id for row in rows],
                                     [rows[0].id], "stale summary", 1)
    replay = chat_store.messages(owner.id, conversation_id)
    assert replay[0]["type"] == "user"
    assert not any(item["step"] == -2 for item in replay)


def test_legacy_summary_excludes_earlier_active_messages(
    chat_client: tuple[object, object, object, object],
) -> None:
    _client, owner, _, _ = chat_client
    conversation_id = _conversation(owner.id)
    chat_store.save(conversation_id, "assistant", "legacy compacted facts", "context_summary", -2)
    chat_store.save(conversation_id, "user", "question after legacy summary", "user")
    chat_store.save(conversation_id, "assistant", "answer after legacy summary", "summary")

    assert [message.content for message in chat_store.history(owner.id, conversation_id)] == [
        "Previous conversation summary:\nlegacy compacted facts",
        "question after legacy summary",
        "answer after legacy summary",
    ]
    replay = chat_store.messages(owner.id, conversation_id)
    assert len(replay) == 12
    assert replay[0]["content"] == "question 0"
    assert not any(message["type"] == "context_summary" for message in replay)


def test_repeated_compression_replaces_previous_summary(
    chat_client: tuple[object, object, object, object], provider: Provider,
) -> None:
    client, owner, _, _ = chat_client
    assert isinstance(client, TestClient)
    conversation_id = _conversation(owner.id)
    provider.replies = [reply("First compact summary."), reply("Second compact summary.")]
    endpoint = f"/api/chat/conversations/{conversation_id}/compress"
    first = client.post(endpoint, json={}).json()["data"]
    assert first["compressed"] is True
    chat_store.save(conversation_id, "user", "new question", "user")
    chat_store.save(conversation_id, "assistant", "new answer", "summary")
    second = client.post(endpoint, json={}).json()["data"]
    assert second["compressed"] is True
    second_transcript = provider.requests[1]["messages"][1]["content"]
    assert "First compact summary." in second_transcript
    assert "question 2" in second_transcript
    assert "question 0" not in second_transcript
    assert [message.content for message in chat_store.history(owner.id, conversation_id)] == [
        "Previous conversation summary:\nSecond compact summary.",
        "question 4", "answer 5", "question 6", "answer 7", "new question", "new answer",
    ]
    replay = client.get(f"/api/chat/conversations/{conversation_id}/messages").json()["data"]
    assert replay[0]["content"] == "question 0"
    assert [item["content"] for item in replay if item["step"] == -2] == [
        "First compact summary.", "Second compact summary.",
    ]
    assert next(item for item in replay if item["content"] == "First compact summary.")["type"] == "compressed"


@pytest.mark.parametrize(
    ("locale", "system_excerpt", "user_excerpt", "role_excerpt", "language_excerpt"),
    [
        ("en", "Known errors and how to avoid them", "Below is the conversation history",
         "[user] question 0", "You MUST respond in English."),
        ("zh-CN", "已知错误与规避方式", "以下是需要压缩的历史对话内容",
         "[用户] question 0", "You MUST respond in Simplified Chinese."),
    ],
)
def test_compression_uses_source_prompt_in_both_languages(
    chat_client: tuple[object, object, object, object], provider: Provider,
    locale: str, system_excerpt: str, user_excerpt: str,
    role_excerpt: str, language_excerpt: str,
) -> None:
    client, owner, _, _ = chat_client
    assert isinstance(client, TestClient)
    conversation_id = _conversation(owner.id)
    provider.replies = [reply("Structured summary")]
    response = client.post(f"/api/chat/conversations/{conversation_id}/compress",
                           headers={"Accept-Language": locale}, json={})
    assert response.json()["data"]["compressed"] is True
    messages = provider.requests[0]["messages"]
    assert system_excerpt in messages[0]["content"]
    assert language_excerpt in messages[0]["content"]
    assert user_excerpt in messages[1]["content"]
    assert role_excerpt in messages[1]["content"]
    assert "{transcript}" not in messages[1]["content"]
    assert "{targetTokens}" not in messages[1]["content"]
