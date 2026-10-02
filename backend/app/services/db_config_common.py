from urllib.parse import quote, quote_plus

from app.adapters import DbConnectionConfig, get_adapter
from app.core.config import get_settings
from app.core.errors import BusinessError
from app.core.localization import translate
from app.core.request_locale import current_locale
from app.core.security import decrypt
from app.models import DbConfig
from app.schemas.db_config import DbConfigRequest, DbConfigVO


def request_password(request: DbConfigRequest, current: DbConfig | None = None) -> str:
    """Mongo updates replace the submitted credential pair; SQL edits retain blanks."""
    db_type = request.db_type.strip().lower() if request.db_type else "mysql"
    password = request.password
    if db_type == "mongodb":
        return "" if password is None or not password.strip() else password
    if current is not None and (password is None or not password.strip()):
        return connection_for(current).password
    if password is None:
        raise BusinessError(400, "password is required")
    return password


def validate_request(request: DbConfigRequest, password: str) -> DbConnectionConfig:
    db_type = request.db_type.strip().lower() if request.db_type else "mysql"
    try:
        adapter = get_adapter(db_type)
    except ValueError as exc:
        raise BusinessError(400, str(exc)) from exc
    if request.host is None or request.port is None or (db_type != "mongodb" and request.username is None):
        raise BusinessError(400, "host, port and username are required")
    connection = DbConnectionConfig(db_type, request.host.strip(), request.port,
                                    request.db_name.strip(),
                                    "" if request.username is None else request.username.strip(), password)
    try:
        adapter.validate_config(connection)
    except (ValueError, TypeError) as exc:
        raise BusinessError(400, str(exc)) from exc
    return connection


def connection_for(config: DbConfig) -> DbConnectionConfig:
    if config.password_encrypted is None:
        if config.db_type != "mongodb" or config.username.strip():
            raise ValueError("Database credential is missing")
        password = ""
    else:
        password = decrypt(config.password_encrypted)
    return DbConnectionConfig(config.db_type, config.host, config.port, config.db_name,
                              config.username, password)


def to_vo(config: DbConfig) -> DbConfigVO:
    mask = get_settings().trial_enabled and config.builtin
    status_desc = {0: "验证中", 1: "连接成功", 2: "连接失败"}[config.status]
    if config.status == 2 and config.verification_error and not mask:
        status_desc = f"{status_desc}: {config.verification_error}"
    return DbConfigVO(
        id=config.id, name=config.name, db_type="*" if mask else config.db_type,
        host="*" if mask else config.host, port=0 if mask else config.port,
        db_name="*" if mask else config.db_name,
        username="*" if mask else config.username, status=config.status,
        status_desc=status_desc, doc_content="*" if mask else config.doc_content,
        doc_generated_at=config.doc_generated_at, created_at=config.created_at,
    )


def diagnostic(exc: Exception, password: str = "") -> str:
    detail = (translate(exc.message, current_locale(), *exc.message_args)
              if isinstance(exc, BusinessError) else str(exc))
    if password:
        for credential in {password, quote(password, safe=""), quote_plus(password)}:
            detail = detail.replace(credential, "[REDACTED]")
    return f"{type(exc).__name__}: {detail}"[:1000]
