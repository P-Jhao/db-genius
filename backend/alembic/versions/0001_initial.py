"""Initial app schema and authentication sessions.

Revision ID: 0001_initial
Revises:
"""

import sqlalchemy as sa

from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    ]


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS app")
    op.create_table(
        "sys_user", sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("username", sa.String(64), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(256), nullable=False),
        sa.Column("nickname", sa.String(64)),
        sa.Column("role", sa.String(16), nullable=False, server_default="user"),
        sa.Column("status", sa.SmallInteger(), nullable=False, server_default="1"),
        *timestamps(), schema="app",
    )
    op.create_table(
        "auth_session", sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("app.sys_user.id"), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("last_active_at", sa.DateTime(), nullable=False), schema="app",
    )
    op.create_index("ix_auth_session_user_id", "auth_session", ["user_id"], schema="app")
    op.create_table(
        "db_config", sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("app.sys_user.id"), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("db_type", sa.String(32), nullable=False, server_default="mysql"),
        sa.Column("host", sa.String(256), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False, server_default="3306"),
        sa.Column("db_name", sa.String(128), nullable=False),
        sa.Column("username", sa.String(128), nullable=False),
        sa.Column("password_encrypted", sa.Text()),
        sa.Column("status", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("builtin", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("doc_content", sa.Text()),
        sa.Column("doc_generated_at", sa.DateTime()),
        sa.Column("verification_error", sa.Text()),
        sa.Column("verification_version", sa.Integer(), nullable=False, server_default="0"),
        *timestamps(), schema="app",
    )
    op.create_index("ix_db_config_user_id", "db_config", ["user_id"], schema="app")
    op.create_table(
        "conversation", sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("app.sys_user.id"), nullable=False),
        sa.Column("title", sa.String(256)),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("db_config_ids", sa.Text()),
        sa.Column("total_tokens", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("context_tokens", sa.Integer()),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        *timestamps(), schema="app",
    )
    op.create_index("ix_conversation_user_id", "conversation", ["user_id"], schema="app")
    op.create_table(
        "message", sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("conversation_id", sa.BigInteger(), sa.ForeignKey("app.conversation.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("step", sa.Integer()),
        sa.Column("type", sa.String(32)),
        sa.Column("reasoning_content", sa.Text()),
        sa.Column("tool_calls", sa.Text()),
        sa.Column("file_url", sa.Text()),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()), schema="app",
    )
    op.create_index("ix_message_conversation_id", "message", ["conversation_id"], schema="app")
    op.create_table(
        "uploaded_file", sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("app.sys_user.id"), nullable=False),
        sa.Column("original_name", sa.String(256), nullable=False),
        sa.Column("oss_key", sa.String(512), nullable=False),
        sa.Column("file_size", sa.BigInteger()),
        sa.Column("content_type", sa.String(128)),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()), schema="app",
    )
    op.create_index("ix_uploaded_file_user_id", "uploaded_file", ["user_id"], schema="app")
    op.create_table(
        "model_provider", sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("provider_code", sa.String(32), nullable=False, unique=True),
        sa.Column("display_name", sa.String(64), nullable=False),
        sa.Column("provider_type", sa.String(32), nullable=False, server_default="openai_compatible"),
        sa.Column("default_base_url", sa.String(256)),
        sa.Column("default_model", sa.String(128)),
        sa.Column("builtin", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        *timestamps(), schema="app",
    )
    op.create_table(
        "user_model_config", sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("app.sys_user.id"), nullable=False),
        sa.Column("provider_code", sa.String(32)),
        sa.Column("provider_type", sa.String(32), nullable=False, server_default="openai_compatible"),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("base_url", sa.String(256), nullable=False),
        sa.Column("api_key_encrypted", sa.Text(), nullable=False),
        sa.Column("model_name", sa.String(128), nullable=False),
        sa.Column("context_window", sa.Integer()),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.SmallInteger(), nullable=False, server_default="1"),
        *timestamps(), schema="app",
    )
    op.create_index("ix_user_model_config_user_id", "user_model_config", ["user_id"], schema="app")


def downgrade() -> None:
    for table in ("user_model_config", "model_provider", "uploaded_file", "message",
                  "conversation", "db_config", "auth_session", "sys_user"):
        op.drop_table(table, schema="app")
    op.execute("DROP SCHEMA app")
