from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator

from app.schemas.base import ApiModel


class ModelProviderVO(ApiModel):
    provider_code: str
    display_name: str
    provider_type: str
    default_base_url: str | None
    default_model: str | None
    builtin: bool
    sort_order: int


class UserModelConfigBase(ApiModel):
    provider_code: str = Field(min_length=1)
    provider_type: str = Field(min_length=1)
    display_name: str = Field(min_length=1, max_length=128)
    base_url: str | None = Field(default=None, max_length=256)
    model_name: str = Field(min_length=1, max_length=128)
    context_window: int | None = Field(default=None, gt=0)

    @field_validator("provider_code", "provider_type", "display_name", "model_name")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class UserModelConfigRequest(UserModelConfigBase):
    api_key: str = Field(min_length=1)

    @field_validator("api_key")
    @classmethod
    def api_key_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class UserModelConfigUpdate(UserModelConfigBase):
    api_key: str = ""


class ContextWindowLookupRequest(ApiModel):
    base_url: str = Field(min_length=1, max_length=256)
    api_key: str = Field(min_length=1)
    model_name: str = Field(min_length=1, max_length=128)

    @field_validator("base_url", "api_key", "model_name")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class UserModelConfigVO(ApiModel):
    id: int | None
    provider_code: str | None
    provider_type: str
    display_name: str
    base_url: str
    model_name: str
    context_window: int | None
    is_default: bool
    status: int
    status_desc: str
    created_at: datetime | None


class ContextWindowLookupVO(ApiModel):
    model_name: str
    context_window: int | None
    source: Literal["registry", "not_found"]
