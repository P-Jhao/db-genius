from datetime import datetime

from pydantic import Field

from app.schemas.base import ApiModel


class DbConfigRequest(ApiModel):
    name: str = Field(min_length=1, max_length=128)
    db_type: str = "mysql"
    host: str | None = None
    port: int | None = None
    db_name: str = Field(min_length=1, max_length=128)
    username: str | None = None
    password: str | None = None


class DbConfigVO(ApiModel):
    id: int
    name: str
    db_type: str
    host: str | None
    port: int | None
    db_name: str
    username: str | None
    status: int
    status_desc: str
    doc_content: str | None
    doc_generated_at: datetime | None
    created_at: datetime
