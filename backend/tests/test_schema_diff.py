import pytest

from app.adapters.types import ColumnMetadata, SchemaMetadata, TableMetadata
from app.core.errors import BusinessError
from app.services import database_tools
from app.services.schema_diff import compare_databases


def _column(name: str, type_name: str, nullable: bool) -> ColumnMetadata:
    return {
        "name": name,
        "type": type_name,
        "nullable": nullable,
        "primaryKey": False,
        "comment": None,
    }


def _table(name: str, *columns: ColumnMetadata) -> TableMetadata:
    return {
        "name": name,
        "comment": None,
        "rowCount": None,
        "columns": list(columns),
        "indexes": [],
    }


def _schema(
    database_name: str,
    db_type: str,
    *tables: TableMetadata,
    incomplete: bool = False,
    error_message: str | None = None,
) -> SchemaMetadata:
    return {
        "dbType": db_type,
        "databaseName": database_name,
        "host": "db.internal",
        "port": 5432 if db_type == "postgresql" else 3306,
        "tables": list(tables),
        "incomplete": incomplete,
        "errorMessage": error_message,
    }


def _install_schemas(
    monkeypatch: pytest.MonkeyPatch,
    schemas: dict[int, SchemaMetadata],
) -> list[tuple[int, int]]:
    calls: list[tuple[int, int]] = []

    def get_schema(user_id: int, db_id: int) -> SchemaMetadata:
        calls.append((user_id, db_id))
        return schemas[db_id]

    monkeypatch.setattr(database_tools, "get_schema", get_schema)
    return calls


def test_diff_reports_pre_to_test_changes_with_stable_order(monkeypatch: pytest.MonkeyPatch) -> None:
    pre = _schema(
        "production_mirror",
        "mysql",
        _table("z_legacy", _column("id", "INT", False)),
        _table(
            "orders",
            _column("status", "VARCHAR(20)", True),
            _column("removed", "TEXT", True),
            _column("id", "INT(11)", False),
        ),
    )
    test = _schema(
        "test_target",
        "postgresql",
        _table("orders", _column("id", "int4", True),
               _column("created_at", "timestamp without time zone", True),
               _column("status", "VARCHAR(40)", True)),
        _table("new_archive", _column("new_id", "BIGSERIAL", False)),
    )
    calls = _install_schemas(monkeypatch, {11: pre, 12: test})

    report = compare_databases(user_id=7, pre_id=11, test_id=12)

    assert calls == [(7, 11), (7, 12)]
    assert report == {
        "success": True,
        "complete": True,
        "preComplete": True,
        "testComplete": True,
        "preDatabase": "production_mirror",
        "testDatabase": "test_target",
        "preDbType": "mysql",
        "testDbType": "postgresql",
        "preSchemaInferred": False,
        "testSchemaInferred": False,
        "summary": {"newTables": 1, "droppedTables": 1, "alteredTables": 1},
        "newTables": [{"table": "new_archive", "columnCount": 1}],
        "droppedTables": [{"table": "z_legacy", "columnCount": 1}],
        "alteredTables": [{
            "table": "orders",
            "changes": [
                {"change": "ADD_COLUMN", "column": "created_at", "type": "timestamp without time zone"},
                {"change": "MODIFY_COLUMN", "column": "id", "preType": "INT(11)", "testType": "int4"},
                {"change": "MODIFY_NULLABLE", "column": "id", "preNullable": False,
                 "testNullable": True},
                {"change": "DROP_COLUMN", "column": "removed", "type": "TEXT"},
                {"change": "MODIFY_COLUMN", "column": "status", "preType": "VARCHAR(20)",
                 "testType": "VARCHAR(40)"},
            ],
        }],
        "preSchema": pre,
        "testSchema": test,
    }
    assert report["preDbType"] == "mysql"
    assert report["testDbType"] == "postgresql"
    assert report["complete"] is True


def test_partial_metadata_cannot_be_reported_as_a_complete_no_diff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pre = _schema("pre", "mysql", incomplete=True)
    test = _schema("test", "postgresql")
    _install_schemas(monkeypatch, {1: pre, 2: test})

    report = compare_databases(3, 1, 2)

    assert report["success"] is False
    assert report["complete"] is False
    assert report["preComplete"] is False
    assert report["testComplete"] is True
    assert report["preError"] == "Schema metadata is incomplete."
    assert report["newTables"] == []
    assert report["droppedTables"] == []
    assert report["alteredTables"] == []
    assert report["preSchema"] == pre and report["testSchema"] == test


def test_error_messages_mark_both_sides_incomplete_even_when_flag_is_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pre = _schema("pre", "mysql", error_message="orders: permission denied")
    test = _schema("test", "postgresql", error_message="catalog sampling stopped")
    _install_schemas(monkeypatch, {1: pre, 2: test})

    report = compare_databases(3, 1, 2)

    assert report["success"] is False
    assert report["complete"] is False
    assert report["preComplete"] is False
    assert report["testComplete"] is False
    assert report["preError"] == "orders: permission denied"
    assert report["testError"] == "catalog sampling stopped"


@pytest.mark.parametrize(
    ("failure_id", "failure", "expected_calls"),
    [
        (1, BusinessError(404, "error.dbConfig.notFound"), [(9, 1)]),
        (2, ConnectionError("database connection refused"), [(9, 1), (9, 2)]),
    ],
)
def test_ownership_and_connection_failures_propagate(
    monkeypatch: pytest.MonkeyPatch,
    failure_id: int,
    failure: Exception,
    expected_calls: list[tuple[int, int]],
) -> None:
    calls: list[tuple[int, int]] = []
    pre = _schema("pre", "mysql")

    def get_schema(user_id: int, db_id: int) -> SchemaMetadata:
        calls.append((user_id, db_id))
        if db_id == failure_id:
            raise failure
        return pre

    monkeypatch.setattr(database_tools, "get_schema", get_schema)

    with pytest.raises(type(failure)) as raised:
        compare_databases(9, 1, 2)

    assert raised.value is failure
    assert calls == expected_calls


def test_duplicate_metadata_names_fail_instead_of_silently_overwriting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pre = _schema("pre", "mysql", _table("orders"), _table("orders"))
    test = _schema("test", "mysql")
    _install_schemas(monkeypatch, {1: pre, 2: test})

    with pytest.raises(ValueError, match="Duplicate table name"):
        compare_databases(3, 1, 2)


def test_authoritative_schemas_preserve_new_table_and_required_column_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary: ColumnMetadata = {**_column("pk", "BIGINT", False), "primaryKey": True}
    pre = _schema("current", "postgresql", _table("orders", primary))
    test = _schema("desired", "postgresql",
        _table("orders", primary, _column("required_note", "VARCHAR(42)", False)),
        _table("new_table", primary, _column("optional_amount", "NUMERIC(12,2)", True)))
    calls = _install_schemas(monkeypatch, {11: pre, 12: test})
    report = compare_databases(7, 11, 12)
    assert calls == [(7, 11), (7, 12)]  # Keep this extraction's snapshots; do not read them again.
    assert report["preSchema"] is pre and report["testSchema"] is test
    assert report["newTables"] == [{"table": "new_table", "columnCount": 2}]
    assert test["tables"][0]["columns"][1] == {
        "name": "required_note", "type": "VARCHAR(42)", "nullable": False,
        "primaryKey": False, "comment": None,
    }
    assert test["tables"][1]["columns"] == [primary, _column("optional_amount", "NUMERIC(12,2)", True)]
    assert report["alteredTables"] == [{"table": "orders", "changes": [
        {"change": "ADD_COLUMN", "column": "required_note", "type": "VARCHAR(42)"},
    ]}]
