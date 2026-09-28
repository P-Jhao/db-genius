from datetime import UTC, datetime, timedelta

from fastapi import Header
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.errors import BusinessError
from app.core.security import token_digest
from app.models import AuthSession, User


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def parse_token(authorization: str | None) -> str:
    if not authorization:
        raise BusinessError(401, "error.auth.notLogin", 401)
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise BusinessError(401, "error.auth.notLogin", 401)
    return token


def authenticated_user(session: Session, token: str, now: datetime | None = None) -> User:
    current_time = now or utc_now()
    auth_session = session.get(AuthSession, token_digest(token))
    if auth_session is None:
        raise BusinessError(401, "error.auth.notLogin", 401)
    settings = get_settings()
    if (auth_session.expires_at <= current_time or
            auth_session.last_active_at + timedelta(seconds=settings.session_idle_seconds) <= current_time):
        session.delete(auth_session)
        session.commit()
        raise BusinessError(401, "error.auth.notLogin", 401)
    user = session.scalar(select(User).where(User.id == auth_session.user_id))
    if user is None or user.status != 1:
        session.delete(auth_session)
        session.commit()
        raise BusinessError(401, "error.auth.notLogin", 401)
    auth_session.last_active_at = current_time
    session.commit()
    return user


def current_user(authorization: str | None = Header(default=None)) -> User:
    token = parse_token(authorization)
    with SessionLocal() as session:
        return authenticated_user(session, token)
