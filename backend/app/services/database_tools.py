import threading

from app.adapters import get_adapter
from app.adapters.oracle import OracleAdapter
from app.adapters.types import QueryResult, SchemaMetadata
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.errors import BusinessError
from app.models import DbConfig
from app.services.db_config_common import connection_for


def _ready_config(user_id: int, db_id: int) -> DbConfig:
    with SessionLocal() as session:
        config = session.get(DbConfig, db_id)
        if config is None or config.user_id != user_id:
            raise BusinessError(404, "error.dbConfig.notFound")
        if config.status == 0:
            raise BusinessError(400, "error.dbConfig.verifying")
        if config.status == 2:
            raise BusinessError(400, "error.dbConfig.connectionFailed")
        if config.status != 1:
            raise ValueError(f"Unknown database configuration status: {config.status}")
        session.expunge(config)
        return config


def get_schema(user_id: int, db_id: int) -> SchemaMetadata:
    config = _ready_config(user_id, db_id)
    connection = connection_for(config)
    metadata = get_adapter(config.db_type).extract_metadata(
        connection, timeout_seconds=get_settings().query_timeout_seconds,
    )
    if get_settings().trial_enabled and config.builtin:
        metadata["databaseName"] = "*"
        metadata["host"] = "*"
        metadata["port"] = 0
    return metadata


def execute_statement(user_id: int, db_id: int, statement: str,
                      cancel_event: threading.Event | None = None) -> QueryResult:
    return _execute(user_id, db_id, statement, cancel_event, read_only=False)


def execute_comparison_read(user_id: int, db_id: int, statement: str,
                            cancel_event: threading.Event | None = None) -> QueryResult:
    """Check and execute using the same owned configuration and target adapter."""
    return _execute(user_id, db_id, statement, cancel_event, read_only=True)


def _execute(user_id: int, db_id: int, statement: str,
             cancel_event: threading.Event | None, *, read_only: bool) -> QueryResult:
    config = _ready_config(user_id, db_id)
    adapter = get_adapter(config.db_type)
    oracle_connection = None
    if read_only:
        try:
            if isinstance(adapter, OracleAdapter):
                oracle_connection = connection_for(config)
                allowed = adapter.is_read_only_for_config(
                    oracle_connection, statement, timeout_seconds=get_settings().query_timeout_seconds,
                )
            else:
                allowed = adapter.is_read_only(statement)
        except ValueError as error:
            raise BusinessError(400, "Comparison statement could not be safely parsed") from error
        if not allowed:
            raise BusinessError(403, "Comparison cannot execute migration writes", 403)
    connection = oracle_connection if oracle_connection is not None else connection_for(config)
    settings = get_settings()
    return adapter.execute(
        connection, statement, trial_mode=read_only or settings.trial_enabled,
        timeout_seconds=settings.query_timeout_seconds, max_rows=settings.query_max_rows,
        cancel_event=cancel_event,
    )
