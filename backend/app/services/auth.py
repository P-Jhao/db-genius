import secrets
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import parse_token, utc_now
from app.core.config import get_settings
from app.core.errors import BusinessError, deny_trial
from app.core.security import hash_password, token_digest, verify_password
from app.models import AuthSession, User
from app.schemas.auth import CreateUserRequest, LoginRequest, LoginVO


def login(session: Session, request: LoginRequest) -> LoginVO:
    user = session.scalar(select(User).where(User.username == request.username))
    if user is None:
        raise BusinessError(401, "error.auth.invalidCredentials")
    if user.status != 1:
        raise BusinessError(403, "error.auth.accountDisabled")
    if not verify_password(request.password, user.password_hash):
        raise BusinessError(401, "error.auth.invalidCredentials")
    now = utc_now()
    token = secrets.token_urlsafe(32)
    session.add(AuthSession(
        token_hash=token_digest(token), user_id=user.id,
        expires_at=now + timedelta(seconds=get_settings().session_lifetime_seconds),
        last_active_at=now,
    ))
    session.commit()
    return LoginVO(token=token, username=user.username, nickname=user.nickname, role=user.role)


def logout(session: Session, authorization: str | None) -> None:
    token = parse_token(authorization)
    auth_session = session.get(AuthSession, token_digest(token))
    if auth_session is None:
        raise BusinessError(401, "error.auth.notLogin", 401)
    session.delete(auth_session)
    session.commit()


def create_user(session: Session, actor: User, request: CreateUserRequest) -> None:
    deny_trial("error.trial.createUser")
    if actor.role != "admin":
        raise BusinessError(403, "error.auth.adminOnly")
    if session.scalar(select(User.id).where(User.username == request.username)) is not None:
        raise BusinessError(400, "error.user.usernameExists")
    role = request.role or "user"
    if role not in {"admin", "user"}:
        raise BusinessError(400, "Invalid role")
    session.add(User(
        username=request.username,
        password_hash=hash_password(request.password),
        nickname=request.nickname,
        role=role,
        status=1,
    ))
    session.commit()
