"""Verify typed file evidence and use the selected database's own SQL dialect."""

from decimal import Decimal

import pytest

from app.agent.workflow import WorkflowProgress
from app.agent.workflow_rows import covers, rows


def progress(db_type: str = "postgresql") -> WorkflowProgress:
    result = WorkflowProgress({5})
    result.schema.register(12, {"dbType": db_type, "databaseName": "test", "tables": [{
        "name": "order items", "columns": [
            {"name": "identifier", "type": "VARCHAR(20)"},
            {"name": "amount", "type": "DECIMAL(10,2)"},
            {"name": "label value", "type": "TEXT"},
        ],
    }]})
    return result


def test_null_and_literal_marker_are_distinct_typed_values() -> None:
    assert not covers([{"name": None}], [{"name": "<NULL>"}])
    assert not covers([{"name": "<NULL>"}], [{"name": None}])
    assert not covers([{"name": None}], [{"name": "None"}])
    assert covers([{"name": None}], [{"name": None}])


def test_decimal_normalization_uses_numeric_columns_and_preserves_text_identifiers() -> None:
    types = {"amount": "NUMERIC(10,2)", "identifier": "VARCHAR(20)"}
    assert covers([{"amount": "1.00", "identifier": "001"}],
                  [{"amount": 1, "identifier": "001"}], types)
    assert covers([{"amount": Decimal("1.25")}], [{"amount": "1.250"}], types)
    assert not covers([{"amount": "1.00", "identifier": "001"}],
                      [{"amount": 1, "identifier": 1}], types)
    assert covers([{"amount": "1.00"}], [{"amount": "1.00"}], {"amount": "TEXT"})
    assert not covers([{"amount": "1.00"}], [{"amount": 1}], {"amount": "TEXT"})
    assert not covers([{"amount": True}], [{"amount": 1}], types)


@pytest.mark.parametrize("db_type,quote", [("mysql", "`"), ("postgresql", '"')])
@pytest.mark.parametrize("wrong_text_identifier", [False, True])
def test_dialect_and_target_column_types_control_import_verification(
    db_type: str, quote: str, wrong_text_identifier: bool,
) -> None:
    state = progress(db_type)
    source = [{"identifier": "001", "amount": "1.00", "label value": None}]
    state.after_call("readFile", {"file_id": 5}, {"success": True, "totalRows": 1,
                     "headers": list(source[0]), "data": source, "truncated": False})
    q = quote
    identifier = "1" if wrong_text_identifier else "'001'"
    insert = (f"INSERT INTO {q}order items{q} ({q}identifier{q},{q}amount{q},{q}label value{q}) "
              f"VALUES ({identifier},1.00,NULL)")
    state.before_call("executeSql", {"db_id": 12, "statement": insert})
    state.after_call("executeSql", {"db_id": 12, "statement": insert}, {"success": True, "affectedRows": 1})
    selected = [{"identifier": "1" if wrong_text_identifier else "001", "amount": 1, "label value": None}]
    namespace = "public." if db_type == "postgresql" else "test."
    state.after_call("executeSql", {"db_id": 12,
                     "statement": f"SELECT * FROM {namespace}{q}order items{q}"},
                     {"success": True, "data": selected, "truncated": False})
    if wrong_text_identifier:
        assert "do not cover the source rows" in str(state.status())
    else:
        assert state.status() is None


def test_file_row_null_cannot_be_verified_by_marker_text_from_sql() -> None:
    state = progress()
    source = [{"label value": None}]
    state.after_call("readFile", {"file_id": 5}, {"success": True, "totalRows": 1,
                     "headers": ["label value"], "data": source, "truncated": False})
    state.after_call("executeSql", {"db_id": 12,
                     "statement": 'INSERT INTO "order items" ("label value") VALUES (NULL)'},
                     {"success": True, "affectedRows": 1})
    state.after_call("executeSql", {"db_id": 12, "statement": 'SELECT "label value" FROM "order items"'},
                     {"success": True, "data": [{"label value": "<NULL>"}], "truncated": False})
    assert "lack a successful subsequent SELECT" in str(state.status())


def test_selected_database_dialects_are_independent() -> None:
    state = WorkflowProgress(set())
    for db_id, db_type in [(12, "mysql"), (13, "postgresql")]:
        state.schema.register(db_id, {"dbType": db_type, "tables": []})
    for db_id, quote in [(12, "`"), (13, '"')]:
        update = f"UPDATE {quote}order items{quote} SET {quote}label value{quote}='test'"
        state.after_call("executeSql", {"db_id": db_id, "statement": update},
                         {"success": True, "affectedRows": 1})
        state.after_call("executeSql", {"db_id": db_id, "statement": f"SELECT * FROM {quote}order items{quote}"},
                         {"success": True, "data": [{"label value": "test"}], "truncated": False})
    assert state.status() is None


@pytest.mark.parametrize("query", [
    'SELECT NULL AS "label value" FROM "order items"',
    'WITH fake AS (SELECT NULL AS "label value" FROM "order items") SELECT "label value" FROM fake',
])
def test_computed_query_values_cannot_replace_stored_row_evidence(query: str) -> None:
    state = progress()
    source = [{"label value": None}]
    state.after_call("readFile", {"file_id": 5}, {"success": True, "totalRows": 1,
                     "headers": ["label value"], "data": source, "truncated": False})
    state.after_call("executeSql", {"db_id": 12,
                     "statement": 'INSERT INTO "order items" ("label value") VALUES (NULL)'},
                     {"success": True, "affectedRows": 1})
    state.after_call("executeSql", {"db_id": 12, "statement": query},
                     {"success": True, "data": source, "truncated": False})
    assert "lack a successful subsequent SELECT" in str(state.status())


def test_case_insensitive_column_collision_is_an_explicit_error() -> None:
    with pytest.raises(ValueError, match="collide"):
        rows([{"Name": "different", "name": "value"}], "mysql")


def test_create_if_exists_does_not_replace_known_real_column_types() -> None:
    from app.agent.workflow_rows import expression

    state = progress()
    state.schema.created_table(12, expression('CREATE TABLE IF NOT EXISTS "order items" (identifier INT)',
                                             "postgres"))
    assert state.schema.column_types[(12, ("order items",))]["identifier"] == "VARCHAR(20)"
