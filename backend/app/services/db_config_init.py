from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import encrypt
from app.models import DbConfig, User
from app.services.db_config import _enqueue


def initialize_trial_database(session: Session) -> None:
    settings = get_settings()
    if not settings.trial_enabled:
        return
    if not all((settings.trial_builtin_host, settings.trial_builtin_username,
                settings.trial_builtin_password, settings.trial_builtin_db_name)):
        raise ValueError("Trial built-in database connection is incomplete")
    existing = session.scalar(select(DbConfig.id).where(DbConfig.builtin.is_(True)).limit(1))
    if existing is not None:
        return
    admin = session.scalar(select(User).where(User.username == settings.bootstrap_username))
    if admin is None:
        raise RuntimeError("Trial built-in database requires the bootstrap admin account")
    config = DbConfig(
        user_id=admin.id, name=settings.trial_builtin_db_name, db_type="mysql",
        host=settings.trial_builtin_host, port=settings.trial_builtin_port,
        db_name=settings.trial_builtin_db_name, username=settings.trial_builtin_username,
        password_encrypted=encrypt(settings.trial_builtin_password),
        status=0, builtin=True, verification_version=1,
    )
    session.add(config)
    session.commit()
    _enqueue(session, config.id, config.verification_version)
