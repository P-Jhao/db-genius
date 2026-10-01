from datetime import UTC, datetime, timedelta

from kombu.exceptions import OperationalError  # type: ignore[import-untyped]
from sqlalchemy import delete, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.adapters import get_adapter
from app.adapters.document import render_document
from app.core.config import get_settings
from app.core.errors import BusinessError, deny_trial
from app.core.ownership import require_owned
from app.core.security import encrypt
from app.models import DbConfig
from app.schemas.db_config import DbConfigRequest, DbConfigVO
from app.services.db_config_common import connection_for, diagnostic, to_vo, validate_request
from app.tasks.db_config import verify_config


def owned_config(session: Session, user_id: int, config_id: int) -> DbConfig:
    return require_owned(session, DbConfig, config_id, user_id, "error.dbConfig.notFound")


def mutable_config(session: Session, user_id: int, config_id: int) -> DbConfig:
    config = owned_config(session, user_id, config_id)
    session.refresh(config, with_for_update=True)
    if get_settings().trial_enabled and config.builtin:
        raise BusinessError(403, "error.trial.builtinModify")
    return config


def _expire_stalled(session: Session, user_id: int) -> None:
    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(
        seconds=get_settings().verification_timeout_seconds,
    )
    session.execute(update(DbConfig).where(
        DbConfig.user_id == user_id, DbConfig.status == 0, DbConfig.updated_at < cutoff,
    ).values(status=2, verification_error="Verification timed out or worker unavailable"))
    session.commit()
    session.expire_all()


def list_configs(session: Session, user_id: int) -> list[DbConfigVO]:
    _expire_stalled(session, user_id)
    configs = session.scalars(select(DbConfig).where(DbConfig.user_id == user_id).order_by(
        DbConfig.created_at.desc(), DbConfig.id.desc(),
    )).all()
    return [to_vo(config) for config in configs]


def get_config(session: Session, user_id: int, config_id: int) -> DbConfigVO:
    _expire_stalled(session, user_id)
    return to_vo(owned_config(session, user_id, config_id))


def _enqueue(session: Session, config_id: int, version: int) -> bool:
    try:
        verify_config.apply_async(args=(config_id, version))
        return True
    except OperationalError as exc:
        session.execute(update(DbConfig).where(
            DbConfig.id == config_id, DbConfig.verification_version == version, DbConfig.status == 0,
        ).values(status=2, verification_error=f"Verification queue unavailable: {diagnostic(exc)}"))
        session.commit()
        return False


def create_config(session: Session, user_id: int, request: DbConfigRequest) -> DbConfigVO:
    deny_trial("error.trial.dbConfigCreate")
    if request.password is None:
        raise BusinessError(400, "password is required")
    connection = validate_request(request, request.password)
    config = DbConfig(
        user_id=user_id, name=request.name.strip(), db_type=connection.db_type,
        host=connection.host, port=connection.port, db_name=connection.db_name,
        username=connection.username, password_encrypted=encrypt(connection.password),
        status=0, builtin=False, verification_version=1,
    )
    session.add(config)
    session.commit()
    _enqueue(session, config.id, config.verification_version)
    session.refresh(config)
    return to_vo(config)


def update_config(session: Session, user_id: int, config_id: int,
                  request: DbConfigRequest) -> DbConfigVO:
    config = mutable_config(session, user_id, config_id)
    password = request.password if request.password is not None and request.password.strip() else connection_for(config).password
    connection = validate_request(request, password)
    config.name = request.name.strip()
    config.db_type = connection.db_type
    config.host = connection.host
    config.port = connection.port
    config.db_name = connection.db_name
    config.username = connection.username
    if request.password is not None and request.password.strip():
        config.password_encrypted = encrypt(connection.password)
    config.status = 0
    config.doc_content = None
    config.doc_generated_at = None
    config.verification_error = None
    config.verification_version += 1
    session.commit()
    _enqueue(session, config.id, config.verification_version)
    session.refresh(config)
    return to_vo(config)


def delete_config(session: Session, user_id: int, config_id: int) -> None:
    mutable_config(session, user_id, config_id)
    session.execute(delete(DbConfig).where(DbConfig.id == config_id, DbConfig.user_id == user_id))
    session.commit()


def _start_sync(session: Session, config: DbConfig) -> int:
    config.verification_version += 1
    config.status = 0
    config.verification_error = None
    session.commit()
    return config.verification_version


def _finish_sync(session: Session, config_id: int, version: int,
                 *, document: str | None, failure: str | None) -> bool:
    values: dict[str, object] = {"status": 2 if failure else 1, "verification_error": failure}
    if document is not None:
        values["doc_content"] = document
        values["doc_generated_at"] = datetime.now(UTC).replace(tzinfo=None)
    elif failure:
        values["doc_content"] = None
        values["doc_generated_at"] = None
    result = session.connection().execute(update(DbConfig).where(
        DbConfig.id == config_id, DbConfig.verification_version == version, DbConfig.status == 0,
    ).values(**values))
    session.commit()
    session.expire_all()
    return result.rowcount == 1


def test_connection(session: Session, user_id: int, config_id: int) -> bool:
    config = mutable_config(session, user_id, config_id)
    connection = connection_for(config)
    version = _start_sync(session, config)
    try:
        connected = get_adapter(connection.db_type).test_connection(connection)
        failure = None if connected else "Connection test returned false"
    except (OSError, SQLAlchemyError, TimeoutError) as exc:
        failure = diagnostic(exc, connection.password)
        connected = False
    if not _finish_sync(session, config_id, version, document=None, failure=failure):
        raise BusinessError(409, "Database configuration changed during connection test")
    return connected


def generate_doc(session: Session, user_id: int, config_id: int) -> str:
    config = mutable_config(session, user_id, config_id)
    connection = connection_for(config)
    version = _start_sync(session, config)
    try:
        adapter = get_adapter(connection.db_type)
        if not adapter.test_connection(connection):
            raise ConnectionError("Connection test returned false")
        metadata = adapter.extract_metadata(connection)
        document = render_document(metadata)
    except Exception as exc:
        _finish_sync(session, config_id, version, document=None,
                     failure=diagnostic(exc, connection.password))
        raise BusinessError(400, "Database document generation failed") from exc
    if not _finish_sync(session, config_id, version, document=document, failure=None):
        raise BusinessError(409, "Database configuration changed during document generation")
    return document


def refresh_doc(session: Session, user_id: int, config_id: int) -> str:
    config = mutable_config(session, user_id, config_id)
    config.verification_version += 1
    config.status = 0
    config.doc_content = None
    config.doc_generated_at = None
    config.verification_error = None
    session.commit()
    if not _enqueue(session, config.id, config.verification_version):
        raise BusinessError(503, "Database verification queue unavailable")
    return "文档刷新任务已受理，正在后台重新验证连接并生成文档"


def get_doc(session: Session, user_id: int, config_id: int) -> str:
    config = owned_config(session, user_id, config_id)
    if not config.doc_content:
        raise BusinessError(400, "error.dbConfig.docNotGenerated")
    if get_settings().trial_enabled and config.builtin:
        return "*"
    return config.doc_content
