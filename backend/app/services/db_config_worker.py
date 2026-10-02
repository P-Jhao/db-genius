from datetime import UTC, datetime

from sqlalchemy import select, update

from app.adapters import get_adapter
from app.adapters.document import render_document
from app.adapters.types import DbConnectionConfig
from app.core.database import SessionLocal
from app.core.observability_metrics import verification_finished
from app.core.observability_runtime import observe_database
from app.core.observability_tracing import verification_outcome
from app.models import DbConfig
from app.services.db_config_common import connection_for, diagnostic


def verify_and_generate(config_id: int, version: int) -> None:
    with SessionLocal() as session:
        config = session.scalar(select(DbConfig).where(
            DbConfig.id == config_id, DbConfig.verification_version == version,
            DbConfig.status == 0,
        ))
        if config is None:
            verification_finished("stale")
            verification_outcome("stale")
            return
    outcome = "error"
    error_type: str | None = None
    connection: DbConnectionConfig | None = None
    try:
        connection = connection_for(config)
        adapter = get_adapter(connection.db_type)
        if not adapter.test_connection(connection):
            raise ConnectionError("Connection test returned false")
        metadata = observe_database("schema")(adapter.extract_metadata)(connection)
        document = render_document(metadata)
        outcome = "partial" if metadata["incomplete"] else "done"
        values: dict[str, object] = {
            "status": 1, "verification_error": None, "doc_content": document,
            "doc_generated_at": datetime.now(UTC).replace(tzinfo=None),
        }
    except Exception as exc:  # noqa: BLE001 - task boundary persists every verification failure
        error_type = type(exc).__name__
        password = connection.password if connection is not None else ""
        values = {"status": 2, "verification_error": diagnostic(exc, password),
                  "doc_content": None, "doc_generated_at": None}
    with SessionLocal() as session:
        updated = session.execute(update(DbConfig).where(
            DbConfig.id == config_id, DbConfig.verification_version == version,
            DbConfig.status == 0,
        ).values(**values))
        session.commit()
        rows = getattr(updated, "rowcount", None)
    applied = outcome if isinstance(rows, int) and rows > 0 else "stale"
    verification_finished(applied)
    verification_outcome(applied, error_type=error_type if applied == "error" else None)
