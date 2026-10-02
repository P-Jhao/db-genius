"""Readiness with independent, bounded driver I/O and deterministic release."""

from collections.abc import Callable
from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from kombu import Connection  # type: ignore[import-untyped]
from sqlalchemy import Engine, create_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings, get_settings

_BACKEND_ROOT = Path(__file__).resolve().parents[2]


def probe_engine(settings: Settings) -> Engine:
    timeout = settings.ready_database_timeout_seconds
    if settings.database_url.startswith("postgresql"):
        connect_args: dict[str, object] = {
            "connect_timeout": timeout,
            "options": (f"-c search_path=app -c statement_timeout={timeout * 1000} "
                        f"-c lock_timeout={timeout * 1000}"),
        }
    elif settings.database_url.startswith("sqlite"):
        connect_args = {"timeout": float(timeout), "check_same_thread": False}
    else:
        raise ValueError("Readiness supports PostgreSQL or SQLite system databases")
    return create_engine(settings.database_url, poolclass=NullPool, connect_args=connect_args)


def migration_ready(settings: Settings | None = None) -> bool:
    config = settings if settings is not None else get_settings()
    heads = set(ScriptDirectory.from_config(Config(str(_BACKEND_ROOT / "alembic.ini"))).get_heads())
    if not heads:
        raise RuntimeError("Migration history has no head")
    engine = probe_engine(config)
    try:
        with engine.connect() as connection:
            schema = "app" if connection.dialect.name == "postgresql" else None
            current = set(MigrationContext.configure(
                connection, opts={"version_table_schema": schema}).get_current_heads())
    finally:
        engine.dispose()
    return current == heads


def broker_ready(settings: Settings) -> bool:
    timeout = settings.ready_broker_timeout_seconds
    with Connection(settings.broker_url, connect_timeout=timeout,
                    transport_options={"read_timeout": timeout, "write_timeout": timeout}) as broker:
        broker.ensure_connection(max_retries=0, timeout=timeout)
        return bool(broker.connected)


def readiness(settings: Settings) -> dict[str, str]:
    checks: dict[str, str] = {}
    probes: tuple[tuple[str, Callable[[], bool]], ...] = (
        ("database", lambda: migration_ready(settings)), ("broker", lambda: broker_ready(settings)),
    )
    for name, probe in probes:
        try:
            checks[name] = "UP" if probe() else "DOWN"
        except Exception:  # noqa: BLE001 - no connection diagnostics in public probes
            checks[name] = "DOWN"
    return checks
