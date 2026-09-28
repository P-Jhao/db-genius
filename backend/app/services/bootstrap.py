from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models import User


def bootstrap_admin(session: Session) -> bool:
    settings = get_settings()
    if not settings.bootstrap_password:
        raise ValueError("SQLCHAT_BOOTSTRAP_PASSWORD is required for account initialization")
    existing = session.scalar(select(User).where(User.username == settings.bootstrap_username))
    if existing is not None:
        return False
    session.add(User(
        username=settings.bootstrap_username,
        password_hash=hash_password(settings.bootstrap_password),
        nickname="Administrator",
        role="admin",
        status=1,
    ))
    session.commit()
    return True


def main() -> None:
    with SessionLocal() as session:
        bootstrap_admin(session)


if __name__ == "__main__":
    main()
