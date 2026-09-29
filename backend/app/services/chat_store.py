"""Ownership-checked conversation persistence and context reconstruction."""
from datetime import UTC, datetime

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.agent.types import ChatRequest, Usage
from app.core.database import SessionLocal
from app.core.errors import BusinessError
from app.models import Conversation, Message


def owned(session: Session, user_id: int, conversation_id: int) -> Conversation:
    conversation = session.get(Conversation, conversation_id)
    if conversation is None or conversation.user_id != user_id:
        raise BusinessError(404, "Conversation not found", 404)
    return conversation


def prepare(user_id: int, request: ChatRequest) -> int:
    with SessionLocal() as session:
        if request.conversation_id is not None:
            conversation = owned(session, user_id, request.conversation_id)
        else:
            conversation = Conversation(user_id=user_id, title=request.message[:100],
                                        type=request.confirmed_intent or "simple_chat",
                                        db_config_ids=",".join(map(str, request.db_config_ids or [])))
            session.add(conversation)
            session.flush()
        conversation_id = conversation.id
        session.commit()
        return conversation_id


def save(conversation_id: int, role: str, content: str, kind: str, step: int = -1,
         reasoning: str | None = None, tool_calls: str | None = None,
         metadata: dict[str, object] | None = None) -> int:
    with SessionLocal() as session:
        message = Message(conversation_id=conversation_id, role=role, content=content,
                          type=kind, step=step, reasoning_content=reasoning,
                          tool_calls=tool_calls, metadata_json={} if metadata is None else metadata)
        session.add(message)
        session.flush()
        message_id = message.id
        session.commit()
        return message_id


def history(user_id: int, conversation_id: int) -> list[BaseMessage]:
    with SessionLocal() as session:
        owned(session, user_id, conversation_id)
        rows = list(session.scalars(select(Message).where(Message.conversation_id == conversation_id).order_by(Message.id)))
        latest_summary = next((i for i in range(len(rows) - 1, -1, -1) if rows[i].type == "context_summary"), None)
        if latest_summary is not None:
            rows = rows[latest_summary:]
        messages: list[BaseMessage] = []
        for row in rows:
            if row.type == "context_summary":
                messages.append(SystemMessage(content="Previous conversation summary:\n" + row.content))
            elif row.role == "user" and row.type in ("user", None):
                messages.append(HumanMessage(content=row.content))
            elif row.role == "assistant" and row.type in ("summary", "content", None):
                messages.append(AIMessage(content=row.content))
        return messages


def update_usage(user_id: int, conversation_id: int, usage: Usage) -> None:
    with SessionLocal() as session:
        row = session.scalar(select(Conversation).where(Conversation.id == conversation_id).with_for_update())
        if row is None or row.user_id != user_id:
            raise BusinessError(404, "Conversation not found", 404)
        row.total_tokens = row.total_tokens + usage.totalTokens
        row.context_tokens = usage.contextTokens
        row.updated_at = datetime.now(UTC).replace(tzinfo=None)
        usage.conversationTotalTokens = row.total_tokens
        session.commit()


def set_intent(user_id: int, conversation_id: int, intent: str) -> None:
    with SessionLocal() as session:
        row = owned(session, user_id, conversation_id)
        row.type = intent
        session.commit()


def conversations(user_id: int) -> list[dict[str, object]]:
    with SessionLocal() as session:
        rows = session.scalars(select(Conversation).where(Conversation.user_id == user_id).order_by(Conversation.updated_at.desc()))
        return [{"id": row.id, "title": row.title, "type": row.type, "dbConfigIds": row.db_config_ids,
                 "totalTokens": row.total_tokens, "contextTokens": row.context_tokens,
                 "createdAt": row.created_at.isoformat()} for row in rows]


def messages(user_id: int, conversation_id: int) -> list[dict[str, object]]:
    with SessionLocal() as session:
        owned(session, user_id, conversation_id)
        rows = session.scalars(select(Message).where(Message.conversation_id == conversation_id).order_by(Message.id))
        return [{"id": row.id, "conversationId": row.conversation_id, "role": row.role,
                 "content": row.content, "type": row.type, "step": row.step,
                 "reasoningContent": row.reasoning_content, "toolCalls": row.tool_calls,
                 "fileUrl": row.file_url, "createdAt": row.created_at.isoformat()}
                for row in rows if row.type != "context_summary"]


def remove(user_id: int, conversation_id: int) -> None:
    with SessionLocal() as session:
        row = owned(session, user_id, conversation_id)
        session.execute(delete(Message).where(Message.conversation_id == conversation_id))
        session.delete(row)
        session.commit()
