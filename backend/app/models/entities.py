from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class User(TimestampMixin, Base):
    __tablename__ = "sys_user"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    nickname: Mapped[str | None] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(16), default="user")
    status: Mapped[int] = mapped_column(default=1)


class AuthSession(Base):
    __tablename__ = "auth_session"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("sys_user.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)


class DbConfig(TimestampMixin, Base):
    __tablename__ = "db_config"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("sys_user.id"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    db_type: Mapped[str] = mapped_column(String(32), default="mysql")
    host: Mapped[str] = mapped_column(String(256))
    port: Mapped[int] = mapped_column(Integer)
    db_name: Mapped[str] = mapped_column(String(128))
    username: Mapped[str] = mapped_column(String(128), default="")
    password_encrypted: Mapped[str | None] = mapped_column(Text)
    status: Mapped[int] = mapped_column(default=0)
    builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    doc_content: Mapped[str | None] = mapped_column(Text)
    doc_generated_at: Mapped[datetime | None] = mapped_column(DateTime)
    verification_error: Mapped[str | None] = mapped_column(Text)


class Conversation(TimestampMixin, Base):
    __tablename__ = "conversation"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("sys_user.id"), index=True)
    title: Mapped[str | None] = mapped_column(String(256))
    type: Mapped[str] = mapped_column(String(32), default="simple_chat")
    db_config_ids: Mapped[str | None] = mapped_column(Text)
    total_tokens: Mapped[int] = mapped_column(default=0)
    context_tokens: Mapped[int | None] = mapped_column(Integer)
    metadata_json: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)


class Message(Base):
    __tablename__ = "message"
    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversation.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    step: Mapped[int | None] = mapped_column(Integer)
    type: Mapped[str | None] = mapped_column(String(32))
    reasoning_content: Mapped[str | None] = mapped_column(Text)
    tool_calls: Mapped[str | None] = mapped_column(Text)
    file_url: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class UploadedFile(Base):
    __tablename__ = "uploaded_file"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("sys_user.id"), index=True)
    original_name: Mapped[str] = mapped_column(String(256))
    oss_key: Mapped[str] = mapped_column(String(512))
    file_size: Mapped[int] = mapped_column(Integer)
    content_type: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ModelProvider(TimestampMixin, Base):
    __tablename__ = "model_provider"
    id: Mapped[int] = mapped_column(primary_key=True)
    provider_code: Mapped[str] = mapped_column(String(32), unique=True)
    display_name: Mapped[str] = mapped_column(String(64))
    provider_type: Mapped[str] = mapped_column(String(32), default="openai_compatible")
    default_base_url: Mapped[str | None] = mapped_column(String(256))
    default_model: Mapped[str | None] = mapped_column(String(128))
    builtin: Mapped[bool] = mapped_column(default=True)
    sort_order: Mapped[int] = mapped_column(default=0)


class UserModelConfig(TimestampMixin, Base):
    __tablename__ = "user_model_config"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("sys_user.id"), index=True)
    provider_code: Mapped[str] = mapped_column(String(32))
    provider_type: Mapped[str] = mapped_column(String(32), default="openai_compatible")
    display_name: Mapped[str] = mapped_column(String(128))
    base_url: Mapped[str] = mapped_column(String(256))
    api_key_encrypted: Mapped[str] = mapped_column(Text)
    model_name: Mapped[str] = mapped_column(String(128))
    context_window: Mapped[int | None] = mapped_column(Integer)
    is_default: Mapped[bool] = mapped_column(default=False)
    status: Mapped[int] = mapped_column(default=1)
