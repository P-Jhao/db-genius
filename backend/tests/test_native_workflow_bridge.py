"""Native metadata/AST spelling and authoritative import evidence stay consistent."""

from __future__ import annotations

import pytest
from sqlglot import parse_one

from app.adapters import get_adapter
from app.agent.workflow import WorkflowProgress
from app.agent.workflow_rows import rows
from app.agent.workflow_schema import WorkflowSchema


def schema(db_type: str, table: str, column: str, type_name: str = "NUMBER(12, 2)") -> dict[str, object]:
    return {"dbType": db_type, "databaseName": "SERVICE", "schemaName": "SCOTT", "tables": [
        {"name": table, "columns": [{"name": column, "type": type_name}]}]}


def test_registry_retains_all_ten_accepted_adapter_types() -> None:
    for name in ("mysql", "postgresql", "mariadb", "tidb", "doris", "starrocks", "oceanbase",
                 "mongodb", "oracle", "sqlserver"):
        assert get_adapter(name).db_type == name


@pytest.mark.parametrize("table_sql,expected", [
    ("items", ("ITEMS",)), ('"items"', ("items",)), ('"MixedCase"', ("MixedCase",)),
    ("SCOTT.items", ("ITEMS",)), ('"SCOTT"."items"', ("items",)),
    ('"other"."items"', ("other", "items")),
])
def test_oracle_table_case_and_authorized_namespace(table_sql: str, expected: tuple[str, ...]) -> None:
    registered = WorkflowSchema()
    registered.register(1, schema("oracle", "ITEMS", "AMOUNT"))
    table = parse_one(f"SELECT * FROM {table_sql}", read="oracle").args["from_"].this
    assert registered.table_name(1, table) == expected
    assert registered.dialects[1] == "oracle"


def test_sqlserver_dbo_is_namespace_not_database_name() -> None:
    registered = WorkflowSchema()
    registered.register(1, schema("sqlserver", "items", "amount", "MONEY"))
    table = parse_one("SELECT * FROM [dbo].[items]", read="tsql").args["from_"].this
    assert registered.table_name(1, table) == ("items",)
    assert registered.column_types[(1, ("items",))]["amount"] == "MONEY"


@pytest.mark.parametrize("column_sql,actual_column,header", [
    ("amount", "AMOUNT", "amount"), ('"amount"', "amount", "amount"),
    ('"MixedAmount"', "MixedAmount", "MixedAmount"),
])
def test_oracle_file_import_verifies_actual_upper_lower_and_mixed_columns(
    column_sql: str, actual_column: str, header: str,
) -> None:
    progress = WorkflowProgress({9})
    progress.after_call("getDatabaseSchema", {"db_id": 1}, schema("oracle", "ITEMS", actual_column))
    progress.after_call("readFile", {"file_id": 9}, {"success": True, "headers": [header],
        "data": [{header: "1.00"}], "totalRows": 1, "truncated": False})
    write = f"INSERT INTO items ({column_sql}) VALUES (1.00)"
    progress.after_call("executeSql", {"db_id": 1, "statement": write},
                        {"success": True, "affectedRows": 1})
    assert progress.status() is not None
    progress.after_call("executeSql", {"db_id": 1, "statement": f"SELECT {column_sql} FROM items"},
                        {"success": True, "data": [{actual_column: "1"}], "truncated": False})
    assert progress.status() is None


def test_oracle_real_keys_are_not_globally_upper_or_merged() -> None:
    assert rows([{"NAME": "one", "name": "two", "Name": "three"}], "oracle") == [
        {"NAME": "one", "name": "two", "Name": "three"}]
    registered = WorkflowSchema()
    registered.register(1, schema("oracle", "ITEMS", "NAME"))
    with pytest.raises(ValueError, match="collide"):
        registered.source_row(1, {"name": 1, "NAME": 2}, {"NAME"})
    assert registered.source_row(1, {"name": "two"}, {"NAME", "name"}) == {"name": "two"}


def test_oracle_wrong_case_result_cannot_verify_a_write() -> None:
    progress = WorkflowProgress(set())
    progress.after_call("getDatabaseSchema", {"db_id": 1}, schema("oracle", "items", "name"))
    progress.after_call("executeSql", {"db_id": 1, "statement": 'UPDATE "items" SET "name"=1'},
                        {"success": True, "affectedRows": 1})
    progress.after_call("executeSql", {"db_id": 1, "statement": "SELECT * FROM ITEMS"},
                        {"success": True, "data": [{"NAME": 1}], "truncated": False})
    assert progress.status() is not None
    assert (1, ("items",)) in progress.pending_verification


def test_oracle_schema_name_is_explicitly_validated() -> None:
    registered = WorkflowSchema()
    value = schema("oracle", "ITEMS", "AMOUNT")
    value["schemaName"] = 42
    with pytest.raises(TypeError, match="database name"):
        registered.register(1, value)


@pytest.mark.parametrize("dialect", ["oracle", "tsql"])
def test_national_text_literal_evidence_does_not_accept_dynamic_expression(dialect: str) -> None:
    from app.agent.workflow_rows import insert_values
    assert insert_values("INSERT INTO items(note) VALUES (N'中文')", [], dialect) == [
        {"NOTE" if dialect == "oracle" else "note": "中文"}]
    assert insert_values("INSERT INTO items(note) VALUES (CONCAT(N'中文',N'计算'))", [], dialect) == []
