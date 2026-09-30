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


def _context_rows(session: Session, conversation_id: int) -> list[Message]:
    rows = list(session.scalars(select(Message).where(Message.conversation_id == conversation_id)
                                .order_by(Message.id)))
    active = [row for row in rows if (
        row.type == "context_summary" or
        (row.role == "user" and row.type in ("user", None)) or
        (row.role == "assistant" and row.type in ("summary", "content", None))
    )]
    markers = [row for row in active if row.type == "context_summary" or
               (row.type == "summary" and row.step == -2)]
    if not markers:
        return active
    latest = markers[-1]
    retained_ids: list[int] = []
    if latest.type == "summary":
        raw_ids = (latest.metadata_json or {}).get("retainedMessageIds", [])
        if not isinstance(raw_ids, list) or not all(isinstance(value, int) and not isinstance(value, bool)
                                                    for value in raw_ids) or len(raw_ids) != len(set(raw_ids)):
            raise ValueError("Invalid context summary retained message IDs")
        retained_ids = raw_ids
    retained = [row for row in active if row.id in retained_ids and row.id < latest.id]
    if len(retained) != len(retained_ids):
        raise ValueError("Context summary references missing retained messages")
    following = [row for row in active if row.id > latest.id and row not in markers]
    return [latest, *retained, *following]


def context_snapshot(user_id: int, conversation_id: int) -> tuple[list[Message], int | None]:
    with SessionLocal() as session:
        conversation = owned(session, user_id, conversation_id)
        return _context_rows(session, conversation_id), conversation.context_tokens


def apply_compression(user_id: int, conversation_id: int, expected_ids: list[int],
                      compressed_ids: list[int], summary: str, after_tokens: int) -> int:
    """Atomically replace one validated context snapshot; preserve all message bodies."""
    with SessionLocal() as session:
        conversation = session.scalar(select(Conversation).where(Conversation.id == conversation_id)
                                      .with_for_update())
        if conversation is None or conversation.user_id != user_id:
            raise BusinessError(404, "Conversation not found", 404)
        active = _context_rows(session, conversation_id)
        if [row.id for row in active] != expected_ids:
            raise RuntimeError("Conversation changed during compression")
        if not compressed_ids or not set(compressed_ids).issubset(set(expected_ids)):
            raise ValueError("Invalid compressed message IDs")
        retained_ids = [row.id for row in active if row.id not in compressed_ids]
        for row in active:
            if row.id in compressed_ids:
                row.type = "compressed"
        summary_row = Message(conversation_id=conversation_id, role="assistant", content=summary,
                              type="summary", step=-2,
                              metadata_json={"retainedMessageIds": retained_ids})
        session.add(summary_row)
        conversation.context_tokens = after_tokens
        conversation.updated_at = datetime.now(UTC).replace(tzinfo=None)
        session.flush()
        summary_id = summary_row.id
        session.commit()
        return summary_id


def history(user_id: int, conversation_id: int) -> list[BaseMessage]:
    with SessionLocal() as session:
        owned(session, user_id, conversation_id)
        rows = _context_rows(session, conversation_id)
        messages: list[BaseMessage] = []
        for row in rows:
            if row.type == "context_summary" or (row.type == "summary" and row.step == -2):
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


def finalize_run(user_id: int, conversation_id: int, task_id: str, usage: Usage,
                 status: str, content: str, kind: str,
                 details: dict[str, object] | None = None) -> bool:
    """Write one terminal message and apply known provider usage once per task."""
    if status not in {"done", "error", "aborted"}:
        raise ValueError(f"Unsupported chat run status: {status}")
    with SessionLocal() as session:
        row = session.scalar(select(Conversation).where(Conversation.id == conversation_id).with_for_update())
        if row is None or row.user_id != user_id:
            raise BusinessError(404, "Conversation not found", 404)
        metadata = dict(row.metadata_json or {})
        task_ids = metadata.get("finalizedTaskIds", [])
        if not isinstance(task_ids, list) or not all(isinstance(value, str) for value in task_ids):
            raise ValueError("Invalid conversation run ledger")
        if task_id in task_ids:
            usage.conversationTotalTokens = row.total_tokens
            return False
        terminal_details = dict(details or {})
        terminal_details.update({"taskId": task_id, "runStatus": status,
                                 "usage": usage.model_dump(exclude={"conversationTotalTokens"})})
        session.add(Message(conversation_id=conversation_id, role="assistant", content=content,
                            type=kind, step=-1, metadata_json=terminal_details))
        row.total_tokens += usage.totalTokens
        row.context_tokens = usage.contextTokens
        row.updated_at = datetime.now(UTC).replace(tzinfo=None)
        metadata["finalizedTaskIds"] = [*task_ids, task_id]
        row.metadata_json = metadata
        usage.conversationTotalTokens = row.total_tokens
        session.commit()
        return True


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
