import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import decrypt, encrypt
from app.models import DbConfig, User
from app.services.db_config import _enqueue

logger = logging.getLogger(__name__)


def initialize_trial_database(session: Session) -> None:
    settings = get_settings()
    if not settings.trial_enabled:
        return
    if not all(value.strip() for value in (settings.trial_builtin_host, settings.trial_builtin_username,
                                          settings.trial_builtin_password, settings.trial_builtin_db_name)):
        logger.warning("Trial built-in database connection is incomplete; initialization skipped")
        return
    existing = session.scalar(select(DbConfig).where(DbConfig.builtin.is_(True)).with_for_update().limit(1))
    if existing is not None:
        target = {
            "db_type": "mysql", "host": settings.trial_builtin_host,
            "port": settings.trial_builtin_port, "db_name": settings.trial_builtin_db_name,
            "username": settings.trial_builtin_username,
        }
        password_changed = (existing.password_encrypted is None
                            or decrypt(existing.password_encrypted) != settings.trial_builtin_password)
        if not password_changed and all(getattr(existing, key) == value for key, value in target.items()):
            return
        for key, value in target.items():
            setattr(existing, key, value)
        if password_changed:
            existing.password_encrypted = encrypt(settings.trial_builtin_password)
        existing.status = 0
        existing.doc_content = None
        existing.doc_generated_at = None
        existing.verification_error = None
        existing.verification_version += 1
        session.commit()
        _enqueue(session, existing.id, existing.verification_version)
        return
    admin = session.scalar(select(User).where(User.username == settings.bootstrap_username))
    if admin is None:
        logger.warning("Trial bootstrap admin is absent; built-in database initialization skipped")
        return
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
