from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SQLCHAT_", env_file=".env", extra="ignore")
    database_url: str = "postgresql+psycopg://sqlchat:sqlchat@localhost:5432/sqlchat"
    encrypt_key: str = Field(validation_alias=AliasChoices("SQLCHAT_ENCRYPT_KEY", "DB_GENIUS_ENCRYPT_KEY"))
    broker_url: str = "amqp://guest:guest@localhost:5672//"
    task_always_eager: bool = False
    storage_backend: Literal["oss", "local"] = "oss"
    storage_root: str = "./uploads"
    oss_endpoint: str = ""
    oss_bucket: str = ""
    oss_access_key_id: str = ""
    oss_access_key_secret: str = ""
    ocr_endpoint: str = "ocr-api.cn-hangzhou.aliyuncs.com"
    ocr_access_key_id: str = ""
    ocr_access_key_secret: str = ""
    default_model_base_url: str = "https://api.deepseek.com"
    default_model_api_key: str = Field(default="", validation_alias=AliasChoices("SQLCHAT_DEFAULT_MODEL_API_KEY", "DEEPSEEK_API_KEY"))
    default_model_name: str = "deepseek-v4-pro"
    trial_enabled: bool = False
    bootstrap_username: str = "admin"
    bootstrap_password: str = ""
    auto_create_schema: bool = False
    cors_origins: list[str] = ["http://localhost:5173"]
    session_lifetime_seconds: int = 2592000
    query_timeout_seconds: int = 60
    query_max_rows: int = 1000
    agent_max_steps: int = 20
    checkpoint_database_url: str = ""

    @field_validator("encrypt_key")
    @classmethod
    def valid_key(cls, value: str) -> str:
        if len(value.encode("utf-8")) != 32:
            raise ValueError("SQLCHAT_ENCRYPT_KEY must contain exactly 32 UTF-8 bytes")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
