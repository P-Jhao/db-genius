import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from app.agent.json_capabilities import ChatJsonCapabilityRule, parse_capability_allowlist


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SQLCHAT_", env_file=".env", extra="ignore",
                                     hide_input_in_errors=True)

    database_url: str = "postgresql+psycopg://sqlchat:sqlchat@localhost:5432/sqlchat"
    encrypt_key: str = Field(default="", validation_alias=AliasChoices("SQLCHAT_ENCRYPT_KEY", "DB_GENIUS_ENCRYPT_KEY"))
    broker_url: str = "amqp://guest:guest@localhost:5672//"
    task_always_eager: bool = False
    verification_timeout_seconds: int = Field(default=180, gt=120)
    storage_backend: Literal["oss", "local"] = "oss"
    storage_root: str = "./uploads"
    oss_endpoint: str = ""
    oss_bucket: str = ""
    oss_access_key_id: str = ""
    oss_access_key_secret: str = ""
    ocr_enabled: bool = False
    ocr_endpoint: str = "ocr-api.cn-hangzhou.aliyuncs.com"
    ocr_access_key_id: str = ""
    ocr_access_key_secret: str = ""
    default_model_base_url: str = "https://api.deepseek.com"
    default_model_api_key: str = Field(
        default="", validation_alias=AliasChoices("SQLCHAT_DEFAULT_MODEL_API_KEY", "DEEPSEEK_API_KEY")
    )
    default_model_name: str = "deepseek-flash"
    default_model_context_window: int | None = Field(default=None, gt=0)
    model_chat_json_capabilities: Annotated[tuple[ChatJsonCapabilityRule, ...], NoDecode] = ()
    trial_enabled: bool = False
    trial_builtin_db_name: str = "db-genius"
    trial_builtin_host: str = ""
    trial_builtin_port: int = 3306
    trial_builtin_username: str = ""
    trial_builtin_password: str = ""
    bootstrap_username: str = "admin"
    bootstrap_password: str = "admin123"
    cors_origins: list[str] = ["http://localhost:5173"]

    session_lifetime_seconds: int = Field(default=86400, gt=0)
    session_idle_seconds: int = Field(default=3600, gt=0)
    query_timeout_seconds: int = Field(default=30, gt=0)
    query_max_rows: int = Field(default=100, gt=0)
    sql_agent_max_steps: int = Field(default=10, gt=0)
    workflow_agent_max_steps: int = Field(default=20, gt=0)
    compare_agent_max_steps: int = Field(default=15, gt=0)
    checkpoint_database_url: str = ""
    context_auto_compress_enabled: bool = False
    context_auto_compress_threshold: float = Field(default=0.8, gt=0, le=1)
    context_keep_last_messages: int = Field(default=6, gt=0)
    observation_elision_enabled: bool = True
    observation_elision_threshold: float = Field(default=0.6, gt=0, le=1)
    observation_elision_keep_last_steps: int = Field(default=3, gt=0)
    step_summary_enabled: bool = True
    step_summary_threshold: float = Field(default=0.8, gt=0, le=1)
    step_summary_keep_last_steps: int = Field(default=4, gt=0)
    stale_reasoning_discard_enabled: bool = False
    repeated_tool_call_warning_count: int = Field(default=3, gt=0)
    repeated_tool_call_stop_count: int = Field(default=5, gt=0)
    tool_output_max_characters: int = Field(default=4000, gt=0)
    tool_output_max_rows: int = Field(default=50, gt=0)
    tool_output_per_tool_max_characters: Annotated[dict[str, int], NoDecode] = Field(default_factory=dict)
    tool_artifact_ttl_seconds: int = Field(default=1800, gt=0)
    tool_artifact_max_per_task: int = Field(default=20, gt=0)

    metrics_multiprocess_root: str = ""
    otlp_endpoint: str = ""
    otlp_sample_rate: float = Field(default=0.1, ge=0, le=1)
    observe_content: bool = False
    ready_broker_timeout_seconds: float = Field(default=2, gt=0, le=10)
    ready_database_timeout_seconds: int = Field(default=3, ge=1, le=10)
    sse_keepalive_seconds: float = Field(default=15, gt=0, le=120)

    @field_validator("metrics_multiprocess_root")
    @classmethod
    def absolute_metric_root(cls, value: str) -> str:
        if value and not Path(value).is_absolute():
            raise ValueError("Shared metric root must be an absolute path")
        return value

    @field_validator("default_model_context_window", mode="before")
    @classmethod
    def optional_model_context_window(cls, value: object) -> int | None:
        if value is None or value == "":
            return None
        if isinstance(value, str) and re.fullmatch(r"[0-9]+", value) is not None:
            return int(value)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        raise ValueError("Default model context window must be a positive integer or empty")

    @field_validator("model_chat_json_capabilities", mode="before")
    @classmethod
    def explicit_chat_json_capabilities(cls, value: object) -> tuple[ChatJsonCapabilityRule, ...]:
        if isinstance(value, str):
            return parse_capability_allowlist(value)
        if isinstance(value, tuple) and not value:
            return ()
        raise ValueError("Model JSON capabilities require an explicit JSON array")

    @field_validator("otlp_endpoint")
    @classmethod
    def safe_otlp_endpoint(cls, value: str) -> str:
        if not value:
            return ""
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or \
                parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
            raise ValueError("OTLP endpoint must be an HTTP(S) base URL without credentials or query")
        if parsed.port is not None and not 0 < parsed.port <= 65535:
            raise ValueError("OTLP endpoint port is invalid")
        return value.rstrip("/")

    @field_validator("observe_content")
    @classmethod
    def content_collection_disabled(cls, value: bool) -> bool:
        if value:
            raise ValueError("Content collection is not supported; SQLCHAT_OBSERVE_CONTENT must be false")
        return value

    @field_validator("tool_output_per_tool_max_characters", mode="before")
    @classmethod
    def tool_output_overrides(cls, value: object) -> dict[str, int]:
        if isinstance(value, str):
            if not value.strip():
                return {}
            if value.lstrip().startswith("{"):
                value = json.loads(value)
            else:
                parsed: dict[str, int] = {}
                for item in value.split(","):
                    name, separator, limit = item.partition("=")
                    if not separator or name.strip() in parsed:
                        raise ValueError("Invalid or duplicate tool output override")
                    parsed[name.strip()] = int(limit.strip())
                value = parsed
        if not isinstance(value, dict):
            raise TypeError("Tool output overrides must be a mapping")
        result: dict[str, int] = {}
        for name, limit in value.items():
            if not isinstance(name, str) or re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", name) is None:
                raise ValueError("Invalid tool name in output overrides")
            if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
                raise ValueError("Tool output override must be a positive integer")
            result[name] = limit
        return result


@lru_cache
def get_settings() -> Settings:
    return Settings()
