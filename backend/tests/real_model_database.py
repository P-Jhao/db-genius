"""Own random databases/users on the two dedicated S15 target instances."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, cast
from uuid import uuid4

from psycopg.sql import Literal as PgLiteral
from pydantic import SecretStr
from real_model_relay import object_value
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import URL, Engine
from sqlalchemy.exc import SQLAlchemyError

type DatabaseType = Literal["postgresql", "mysql"]


def normalized(value: object) -> str:
    if value is None:
        return "<NULL>"
    if isinstance(value, Decimal):
        return str(value.normalize())
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(Decimal(str(value)).normalize())
    if isinstance(value, str):
        try:
            return str(Decimal(value).normalize())
        except ArithmeticError:
            return value
    return str(value)


def snapshot_cell(value: object) -> tuple[str, str]:
    if value is None:
        return ("null", "")
    if isinstance(value, bool):
        return ("bool", str(value))
    if isinstance(value, (Decimal, int, float)):
        return ("number", normalized(value))
    if isinstance(value, (date, datetime)):
        return ("date", value.isoformat())
    return ("text", str(value))


def _environment(container: str) -> dict[str, str]:
    result = subprocess.run(["docker", "inspect", container], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError("Dedicated S15 target container is unavailable")
    raw: object = json.loads(result.stdout)
    if not isinstance(raw, list) or len(raw) != 1:
        raise TypeError("Expected one dedicated target container")
    values = object_value(object_value(raw[0])["Config"])["Env"]
    if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
        raise TypeError("Expected container environment entries")
    return dict(item.split("=", 1) for item in cast(list[str], values))


def _admin(db_type: DatabaseType) -> Engine:
    if db_type == "postgresql":
        env = _environment("sqlchat-migration-test-postgres")
        url = URL.create("postgresql+psycopg", host="127.0.0.1", port=15432,
                         username=env["POSTGRES_USER"], password=env["POSTGRES_PASSWORD"],
                         database=env["POSTGRES_DB"])
    else:
        env = _environment("sqlchat-migration-test-mysql")
        url = URL.create("mysql+pymysql", host="127.0.0.1", port=13306,
                         username="root", password=env["MYSQL_ROOT_PASSWORD"],
                         database=env["MYSQL_DATABASE"])
    return create_engine(url, hide_parameters=True, echo=False)


@dataclass
class TargetSnapshot:
    db_type: DatabaseType
    name: str
    username: str
    password: SecretStr = field(repr=False)
    engine: Engine

    def request(self) -> dict[str, object]:
        return {"name": "S15 synthetic target", "dbType": self.db_type,
                "host": "host.docker.internal", "port": 15432 if self.db_type == "postgresql" else 13306,
                "dbName": self.name, "username": self.username, "password": self.password.get_secret_value()}

    def rows(self, statement: str) -> list[tuple[object, ...]]:
        # A fresh connection independently verifies writes after the application commits.
        with self.engine.connect() as connection:
            return [tuple(row) for row in connection.exec_driver_sql(statement)]

    def fingerprint(self, *, exclude_tables: tuple[str, ...] = ()) -> str:
        metadata = inspect(self.engine)
        tables: dict[str, object] = {}
        for name in sorted(metadata.get_table_names()):
            if name in exclude_tables:
                continue
            quoted = self.engine.dialect.identifier_preparer.quote(name)
            columns = [{"name": column["name"], "type": str(column["type"]), "nullable": column["nullable"]}
                       for column in metadata.get_columns(name)]
            rows = sorted([snapshot_cell(cell) for cell in row] for row in self.rows(f"SELECT * FROM {quoted}"))
            tables[name] = {"columns": columns, "rows": rows}
        return hashlib.sha256(json.dumps(tables, sort_keys=True).encode()).hexdigest()


def _seed(target: TargetSnapshot, *, comparison_target: bool) -> None:
    extra = ",loyalty_level VARCHAR(20) DEFAULT 'basic'" if comparison_target else ""
    amount = "DECIMAL(14,2)" if comparison_target else "DECIMAL(12,2)"
    with target.engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE customers (id INTEGER PRIMARY KEY,name VARCHAR(30) NOT NULL,"
                                   f"region VARCHAR(20) NOT NULL{extra})")
        connection.exec_driver_sql("CREATE TABLE orders (id INTEGER PRIMARY KEY,customer_id INTEGER NOT NULL,"
                                   f"amount {amount},status VARCHAR(20) NOT NULL,ordered_at DATE NOT NULL,"
                                   "note VARCHAR(40),FOREIGN KEY(customer_id) REFERENCES customers(id))")
        connection.exec_driver_sql("CREATE TABLE imported_contacts (id INTEGER PRIMARY KEY,"
                                   "name VARCHAR(30) NOT NULL,city VARCHAR(30) NOT NULL)")
        connection.exec_driver_sql("CREATE TABLE " + ("audit_events" if comparison_target else "legacy_notes") +
                                   " (id INTEGER PRIMARY KEY,label VARCHAR(30))")
        connection.exec_driver_sql("INSERT INTO customers (id,name,region) VALUES (%s,%s,%s)", [
            (1, "Ada", "east"), (2, "Lin", "south"), (3, "Bo", "east"), (4, "Kai", "north"),
        ])
        connection.exec_driver_sql("INSERT INTO orders VALUES (%s,%s,%s,%s,%s,%s)", [
            (1, 1, Decimal(10), "paid", "2026-01-01", None),
            (2, 1, Decimal(20), "paid", "2026-01-31", "one"),
            (3, 2, Decimal("7.5"), "cancelled", "2026-02-01", None),
            (4, 2, Decimal(15), "paid", "2026-02-02", "two"),
            (5, 3, Decimal(5), "paid", "2026-01-15", None),
            (6, 3, None, "paid", "2026-03-01", "three"),
        ])
        connection.exec_driver_sql("CREATE INDEX ix_customers_region ON customers(region)")


@contextmanager
def isolated_database(db_type: DatabaseType, variant: str, *,
                      comparison_target: bool = False,
                      cleanup_evidence: dict[str, object] | None = None) -> Iterator[TargetSnapshot]:
    if variant not in {"py", "java", "pre", "test"}:
        raise ValueError("Unknown isolated target variant")
    name = f"s15_{uuid4().hex[:16]}_{variant}"
    if re.fullmatch(r"s15_[0-9a-f]{16}_(py|java|pre|test)", name) is None:
        raise ValueError("Invalid acceptance resource name")
    if cleanup_evidence is not None:
        cleanup_evidence.update({"generatedDatabase": name, "generatedRole": name, "database": db_type, "status": "pending"})
    password = SecretStr(secrets.token_urlsafe(32))
    admin = _admin(db_type)
    role_created = database_created = False
    target: TargetSnapshot | None = None
    try:
        try:
            with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
                if db_type == "postgresql":
                    literal = PgLiteral(password.get_secret_value()).as_string()
                    connection.exec_driver_sql(f"CREATE ROLE {name} LOGIN PASSWORD {literal}")
                    role_created = True
                    connection.exec_driver_sql(f"CREATE DATABASE {name} OWNER {name}")
                    database_created = True
                else:
                    connection.exec_driver_sql("CREATE USER %s@'%%' IDENTIFIED BY %s",
                                               (name, password.get_secret_value()))
                    role_created = True
                    connection.exec_driver_sql(f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4")
                    database_created = True
                    connection.exec_driver_sql(f"GRANT ALL PRIVILEGES ON `{name}`.* TO %s@'%%'", (name,))
            url = URL.create("postgresql+psycopg" if db_type == "postgresql" else "mysql+pymysql",
                             username=name, password=password.get_secret_value(), host="127.0.0.1",
                             port=15432 if db_type == "postgresql" else 13306, database=name)
            target = TargetSnapshot(db_type, name, name, password,
                                    create_engine(url, hide_parameters=True, echo=False))
            _seed(target, comparison_target=comparison_target)
        except SQLAlchemyError as error:
            raise RuntimeError(f"Isolated S15 target provisioning failed: {type(error).__name__}") from None
        yield target
    finally:
        if target is not None:
            target.engine.dispose()
        try:
            with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
                if database_created:
                    connection.exec_driver_sql(f"DROP DATABASE \"{name}\" WITH (FORCE)" if db_type == "postgresql"
                                               else f"DROP DATABASE `{name}`")
                if role_created:
                    connection.exec_driver_sql(f"DROP ROLE {name}" if db_type == "postgresql"
                                               else "DROP USER %s@'%%'", () if db_type == "postgresql" else (name,))
                database_count: object = connection.exec_driver_sql(
                    "SELECT COUNT(*) FROM pg_database WHERE datname=%s" if db_type == "postgresql" else
                    "SELECT COUNT(*) FROM information_schema.schemata WHERE schema_name=%s", (name,),
                ).scalar_one()
                user_count: object = connection.exec_driver_sql(
                    "SELECT COUNT(*) FROM pg_roles WHERE rolname=%s" if db_type == "postgresql" else
                    "SELECT COUNT(*) FROM mysql.user WHERE User=%s", (name,),
                ).scalar_one()
                if cleanup_evidence is not None:
                    cleanup_evidence.update({"databaseCount": database_count, "roleCount": user_count, "status": "passed"})
                if database_count != 0 or user_count != 0:
                    raise RuntimeError("Exact S15 database/user resources remain after cleanup")
        except Exception as error:  # noqa: BLE001 - record cleanup failure, redact diagnostics and rethrow
            if cleanup_evidence is not None:
                cleanup_evidence.update({"status": "failed", "errorType": type(error).__name__})
            raise RuntimeError(f"Exact S15 target cleanup failed: {type(error).__name__}") from None
        finally:
            admin.dispose()
