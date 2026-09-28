from pydantic import Field

from app.schemas.base import ApiModel


class LoginRequest(ApiModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class CreateUserRequest(LoginRequest):
    nickname: str | None = None
    role: str | None = None


class LoginVO(ApiModel):
    token: str
    username: str
    nickname: str | None = None
    role: str
