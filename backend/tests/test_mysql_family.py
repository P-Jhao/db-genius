"""MySQL-wire family protocol tests; real server acceptance remains separate."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.adapters import DbConnectionConfig, get_adapter
from app.adapters.mysql_family import MysqlFamilyAdapter
from app.adapters.safety import UnsafeStatement

FAMILY = {
    "mariadb": (3306, "max_statement_time", 30),
    "tidb": (4000, "max_execution_time", 30_000),
    "doris": (9030, "query_timeout", 30),
    "starrocks": (9030, "query_timeout", 30),
    "oceanbase": (2881, "ob_query_timeout", 30_000_000),
}


def config(db_type: str) -> DbConnectionConfig:
    return DbConnectionConfig(db_type, "db.example", FAMILY[db_type][0], "tenant_db", "user", "p@ss")


@pytest.mark.parametrize("db_type", FAMILY)
def test_explicit_driver_port_and_connection_arguments(db_type: str) -> None:
    adapter = get_adapter(db_type)
    assert isinstance(adapter, MysqlFamilyAdapter)
    assert adapter.db_type == db_type
    assert adapter.default_port == FAMILY[db_type][0]
    assert adapter.dialect == "mysql"
    assert adapter.driver == "mysql+pymysql"
    assert adapter.mysql_protocol is True
    with patch("app.adapters.relational.create_engine") as create:
        adapter._engine(config(db_type), 30)
    url = create.call_args.args[0]
    assert (url.drivername, url.port, url.database, url.password) == (
        "mysql+pymysql",
        FAMILY[db_type][0],
        "tenant_db",
        "p@ss",
    )
    assert create.call_args.kwargs["connect_args"] == {
        "connect_timeout": 10,
        "read_timeout": 30,
        "write_timeout": 30,
        "charset": "utf8mb4",
    }
    with pytest.raises(ValueError):
        adapter.validate_config(DbConnectionConfig("mysql", "db.example", 3306, "tenant_db", "user", "p@ss"))


@pytest.mark.parametrize("db_type", FAMILY)
def test_connection_probe_and_per_engine_timeout(db_type: str, monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = get_adapter(db_type)
    connection = Mock()
    connection.exec_driver_sql.return_value.scalar_one.return_value = 1

    @contextmanager
    def connected(_config: DbConnectionConfig, timeout: int) -> Iterator[Mock]:
        assert timeout == 5
        yield connection

    monkeypatch.setattr(adapter, "_connection", connected)
    assert adapter.test_connection(config(db_type)) is True
    connection.exec_driver_sql.assert_called_once_with("SELECT 1")
    connection.reset_mock()
    adapter._set_timeout(connection, 30, False)
    connection.exec_driver_sql.assert_called_once_with(
        f"SET SESSION {FAMILY[db_type][1]} = {FAMILY[db_type][2]}"
    )


@pytest.mark.parametrize("db_type", FAMILY)
def test_sql_policy_is_mysql_dialect_with_write_and_trial_guard(db_type: str) -> None:
    adapter = get_adapter(db_type)
    assert adapter.is_read_only("SELECT 'DROP TABLE t'") is True
    assert adapter.is_read_only("INSERT INTO t VALUES (1)") is False
    with pytest.raises(UnsafeStatement):
        adapter.execute(config(db_type), "ALTER TABLE t DROP COLUMN c")
    with pytest.raises(UnsafeStatement):
        adapter.execute(config(db_type), "UPDATE t SET c = 1", trial_mode=True)
    with pytest.raises(UnsafeStatement):
        adapter.execute(config(db_type), "SELECT 1; DELETE FROM t")


@pytest.mark.parametrize("db_type", FAMILY)
def test_successful_sql_dispatch_commits_and_normalizes(
    db_type: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = get_adapter(db_type)
    result = Mock(returns_rows=True)
    result.fetchmany.return_value = [SimpleNamespace(_mapping={"value": 1})]
    connection = Mock()
    connection.exec_driver_sql.return_value.scalar_one.return_value = 42
    connection.execution_options.return_value.exec_driver_sql.return_value = result

    @contextmanager
    def connected(_config: DbConnectionConfig, _timeout: int) -> Iterator[Mock]:
        yield connection

    monkeypatch.setattr(adapter, "_connection", connected)
    assert adapter.execute(config(db_type), "SELECT 1 AS value") == {
        "success": True,
        "rowCount": 1,
        "data": [{"value": 1}],
        "truncated": False,
    }
    connection.exec_driver_sql.assert_any_call("SELECT CONNECTION_ID()")
    connection.commit.assert_called_once()
    result.close.assert_called_once()


@pytest.mark.parametrize("db_type", FAMILY)
def test_write_dispatch_reports_affected_rows(db_type: str, monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = get_adapter(db_type)
    result = Mock(returns_rows=False, rowcount=2)
    connection = Mock()
    connection.exec_driver_sql.return_value.scalar_one.return_value = 42
    connection.execution_options.return_value.exec_driver_sql.return_value = result

    @contextmanager
    def connected(_config: DbConnectionConfig, _timeout: int) -> Iterator[Mock]:
        yield connection

    monkeypatch.setattr(adapter, "_connection", connected)
    response = adapter.execute(config(db_type), "INSERT INTO t VALUES (1), (2)")
    assert response["success"] is True
    assert response["affectedRows"] == 2
    connection.commit.assert_called_once()


@pytest.mark.parametrize("db_type", ("tidb", "doris", "starrocks", "oceanbase"))
def test_unpinned_proxy_cancel_never_kills_another_session(db_type: str) -> None:
    adapter = get_adapter(db_type)
    with pytest.raises(RuntimeError, match="unpinned proxy"):
        adapter._cancel_running_statement(config(db_type), Mock(), 42)


class MetadataConnection:
    def __init__(self, *, index_error: bool = False) -> None:
        self.index_error = index_error
        self.queries: list[tuple[str, dict[str, str]]] = []
        self.dialect = SimpleNamespace(
            identifier_preparer=SimpleNamespace(
                quote_identifier=lambda value: "`" + value.replace("`", "``") + "`"
            )
        )
        self.rollback = Mock()

    def execute(self, query: object, parameters: dict[str, str]) -> list[SimpleNamespace]:
        sql = str(query)
        self.queries.append((sql, parameters))
        if "information_schema.TABLES" in sql:
            return [SimpleNamespace(TABLE_NAME="order`items", TABLE_COMMENT="orders")]
        if "information_schema.COLUMNS" in sql:
            return [
                SimpleNamespace(
                    COLUMN_NAME="id",
                    COLUMN_TYPE="BIGINT",
                    IS_NULLABLE="NO",
                    COLUMN_COMMENT="",
                    COLUMN_KEY="PRI",
                )
            ]
        if "information_schema.STATISTICS" in sql:
            if self.index_error:
                raise SQLAlchemyError("statistics unavailable")
            return [SimpleNamespace(INDEX_NAME="PRIMARY", COLUMN_NAME="id", SEQ_IN_INDEX=1)]
        raise AssertionError(sql)

    def exec_driver_sql(self, sql: str) -> Mock:
        if sql.startswith("SET SESSION"):
            return Mock()
        assert sql == "SELECT COUNT(*) FROM `order``items`"
        return Mock(scalar_one=Mock(return_value=7))


@pytest.mark.parametrize("db_type", ("doris", "starrocks"))
@pytest.mark.parametrize("index_error", (False, True))
def test_olap_information_schema_preserves_type_index_comment_and_partial_error(
    db_type: str, index_error: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = get_adapter(db_type)
    connection = MetadataConnection(index_error=index_error)

    @contextmanager
    def connected(_config: DbConnectionConfig, _timeout: int) -> Iterator[MetadataConnection]:
        yield connection

    monkeypatch.setattr(adapter, "_connection", connected)
    metadata = adapter.extract_metadata(config(db_type))
    indexes_unavailable = index_error or db_type == "starrocks"
    assert metadata["dbType"] == db_type
    assert metadata["tables"] == [
        {
            "name": "order`items",
            "comment": "orders",
            "rowCount": 7,
            "columns": [
                {"name": "id", "type": "BIGINT", "nullable": False, "primaryKey": True, "comment": None}
            ],
            "indexes": [] if indexes_unavailable else [{"name": "PRIMARY", "columns": ["id"]}],
        }
    ]
    assert metadata["incomplete"] is indexes_unavailable
    if db_type == "starrocks":
        assert "not implemented" in (metadata["errorMessage"] or "")
        assert not any("information_schema.STATISTICS" in sql for sql, _ in connection.queries)
    elif index_error:
        assert "statistics unavailable" in (metadata["errorMessage"] or "")
    else:
        assert metadata["errorMessage"] is None
        assert "order`items" in adapter.generate_document(config(db_type))
    assert all(parameters["database"] == "tenant_db" for _, parameters in connection.queries)
    assert connection.rollback.call_count == (1 if indexes_unavailable else 2)
