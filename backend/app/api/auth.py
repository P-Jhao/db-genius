from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from app.core.auth import current_user
from app.core.database import SessionLocal
from app.core.errors import success
from app.models import User
from app.schemas.auth import CreateUserRequest, LoginRequest
from app.services import auth as auth_service

router = APIRouter(prefix="/auth")


def database_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session


DatabaseSession = Annotated[Session, Depends(database_session)]
CurrentUser = Annotated[User, Depends(current_user)]
Authorization = Annotated[str | None, Header()]


@router.post("/login")
def login(request: LoginRequest, session: DatabaseSession) -> dict[str, object]:
    return success(auth_service.login(session, request).model_dump(by_alias=True))


@router.post("/logout")
def logout(user: CurrentUser, session: DatabaseSession,
           authorization: Authorization = None) -> dict[str, object]:
    auth_service.logout(session, authorization)
    return success()


@router.post("/user")
def create_user(request: CreateUserRequest, actor: CurrentUser,
                session: DatabaseSession) -> dict[str, object]:
    auth_service.create_user(session, actor, request)
    return success()
