"""Real migrated PostgreSQL and RabbitMQ readiness on dedicated test containers."""

import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import URL, create_engine

from alembic import command
from app.core import config as config_module
from app.core import observability_health
from app.core.config import Settings


def test_migrated_system_database_and_broker_are_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    values = {key: os.environ.get(f"SQLCHAT_TEST_PG_{key}")
              for key in ("HOST", "PORT", "DB", "USER", "PASSWORD")}
    broker_url = os.environ.get("SQLCHAT_TEST_RABBIT_URL")
    if any(value is None for value in values.values()) or broker_url is None:
        pytest.skip("Dedicated PostgreSQL and RabbitMQ test credentials are required")
    host, port, database, username, password = (values[key] for key in
                                                 ("HOST", "PORT", "DB", "USER", "PASSWORD"))
    assert host is not None and port is not None and database is not None
    assert username is not None and password is not None
    admin_url = URL.create("postgresql+psycopg", username=username, password=password,
                           host=host, port=int(port), database=database)
    admin_engine = create_engine(admin_url)
    db_name = f"s14_ready_{uuid4().hex[:12]}"
    quote = admin_engine.dialect.identifier_preparer.quote_identifier
    created = False
    try:
        with admin_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            connection.exec_driver_sql(f"CREATE DATABASE {quote(db_name)}")
        created = True
        target_url = admin_url.set(database=db_name)
        target_settings = Settings(database_url=target_url.render_as_string(hide_password=False),
                                   broker_url=broker_url, ready_broker_timeout_seconds=1)
        monkeypatch.setattr(config_module, "get_settings", lambda: target_settings)
        assert observability_health.readiness(target_settings) == {"database": "DOWN", "broker": "UP"}
        alembic_ini = Path(__file__).resolve().parents[1] / "alembic.ini"
        command.upgrade(Config(str(alembic_ini)), "head")
        assert observability_health.readiness(target_settings) == {"database": "UP", "broker": "UP"}
    finally:
        try:
            if created:
                with admin_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
                    connection.exec_driver_sql(f"DROP DATABASE IF EXISTS {quote(db_name)} WITH (FORCE)")
                    assert connection.exec_driver_sql(
                        "SELECT count(*) FROM pg_database WHERE datname = %s", (db_name,)
                    ).scalar_one() == 0
        finally:
            admin_engine.dispose()
