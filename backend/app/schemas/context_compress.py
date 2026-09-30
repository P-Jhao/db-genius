"""Compatible request and result for conversation context compression."""

from pydantic import Field

from app.schemas.base import ApiModel


class CompressOptions(ApiModel):
    target_tokens: int | None = Field(default=None, gt=0)


class CompressResult(ApiModel):
    conversation_id: int
    compressed: bool
    before_tokens: int | None
    after_tokens: int | None
    summary_message_id: int | None
    message: str
