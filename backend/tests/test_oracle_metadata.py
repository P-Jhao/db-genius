"""Oracle catalog spellings and partial snapshot failures are authoritative."""

from contextlib import contextmanager, nullcontext
from unittest.mock import Mock

import oracledb
import pytest
from sqlalchemy.dialects.oracle import NUMBER
from sqlalchemy.dialects.oracle.base import OracleDialect
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.sql.elements import quoted_name

from app.adapters.oracle import OracleAdapter
from app.adapters.types import DbConnectionConfig


@pytest.mark.parametrize("count_failure", [False, True])
def test_metadata_distinguishes_upper_and_quoted_lower_pk_and_number_precision(
    monkeypatch: pytest.MonkeyPatch, count_failure: bool,
) -> None:
    adapter = OracleAdapter()
    connection = Mock(dialect=OracleDialect())
    connection.connection.driver_connection = Mock(spec=oracledb.Connection)
    connection.begin_nested.return_value = nullcontext()
    user = Mock()
    user.scalar_one.return_value = "SCOTT"
    count = Mock()
    count.scalar_one.return_value = 2
    def execute(statement: str) -> Mock:
        if "SESSION_USER" in statement:
            return user
        if count_failure and statement.startswith("SELECT COUNT"):
            raise SQLAlchemyError("ORA-01466: table definition has changed")
        return count
    connection.exec_driver_sql.side_effect = execute
    @contextmanager
    def connected(*_args: object):
        yield connection
    monkeypatch.setattr(adapter, "_connection", connected)
    inspector = Mock()
    inspector.get_table_names.return_value = ["items"]
    inspector.get_columns.return_value = [
        {"name": "id", "type": NUMBER(10), "nullable": False},
        {"name": quoted_name("id", True), "type": NUMBER(38, 12), "nullable": True},
    ]
    inspector.get_pk_constraint.return_value = {"name": "pk_items", "constrained_columns": ["id"]}
    inspector.get_indexes.return_value = []
    inspector.get_table_comment.return_value = {"text": None}
    monkeypatch.setattr("app.adapters.relational.inspect", lambda _connection: inspector)
    metadata = adapter.extract_metadata(DbConnectionConfig("oracle", "localhost", 1521, "SERVICE", "scott", "secret"))
    table = metadata["tables"][0]
    assert table["name"] == "ITEMS"
    assert [(column["name"], column["primaryKey"], column["type"]) for column in table["columns"]] == [
        ("ID", True, "NUMBER(10)"), ("id", False, "NUMBER(38, 12)")]
    assert table["indexes"] == [{"name": "PK_ITEMS", "columns": ["ID"]}]
    assert metadata["incomplete"] is count_failure
    assert table["rowCount"] == (None if count_failure else 2)
    if count_failure:
        assert metadata["errorMessage"] == "items: ORA-01466: table definition has changed"
    else:
        assert metadata["errorMessage"] is None
    assert sum(call.args[0].startswith("SELECT COUNT") for call in connection.exec_driver_sql.call_args_list) == 1
