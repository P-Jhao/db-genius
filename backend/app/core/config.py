from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SQLCHAT_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://sqlchat:sqlchat@localhost:5432/sqlchat"
    encrypt_key: str = Field(default="", validation_alias=AliasChoices("SQLCHAT_ENCRYPT_KEY", "DB_GENIUS_ENCRYPT_KEY"))
    broker_url: str = "amqp://guest:guest@localhost:5672//"
    task_always_eager: bool = False
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
    default_model_name: str = "deepseek-v4-pro"
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


@lru_cache
def get_settings() -> Settings:
    return Settings()
