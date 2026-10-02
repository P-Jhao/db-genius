"""Protocol-family workflow dialects retain quoted names and typed row evidence."""

from __future__ import annotations

import pytest
from sqlglot import exp
from test_mysql_family import FAMILY

from app.agent.workflow import WorkflowProgress
from app.agent.workflow_rows import expression
from app.agent.workflow_schema import WorkflowSchema

TABLE = "S12 Order`Items"
QUOTED = "`S12 Order``Items`"


def metadata(db_type: str) -> dict[str, object]:
    return {"dbType": db_type, "databaseName": "tenant_db", "tables": [{
        "name": TABLE, "columns": [{"name": "Identifier", "type": "VARCHAR(20)"},
                                    {"name": "Amount", "type": "DECIMAL(10,2)"},
                                    {"name": "Label Value", "type": "TEXT"}],
    }]}


@pytest.mark.parametrize("db_type", FAMILY)
def test_family_schema_register_uses_mysql_namespace_and_column_semantics(db_type: str) -> None:
    schema = WorkflowSchema()
    schema.register(12, metadata(db_type))
    assert schema.dialects[12] == "mysql"
    assert schema.default_namespaces[12] == "tenant_db"
    assert schema.column_types[(12, (TABLE,))] == {
        "identifier": "VARCHAR(20)", "amount": "DECIMAL(10,2)", "label value": "TEXT",
    }
    parsed = expression(f"SELECT * FROM `tenant_db`.{QUOTED}", "mysql")
    table = next(parsed.find_all(exp.Table))
    assert schema.table_name(12, table) == (TABLE,)
    schema.created_table(12, expression(f"CREATE TABLE IF NOT EXISTS {QUOTED} (`Amount` INT)", "mysql"))
    assert schema.column_types[(12, (TABLE,))]["amount"] == "DECIMAL(10,2)"


@pytest.mark.parametrize("db_type", FAMILY)
@pytest.mark.parametrize("fault", (None, "text_identifier", "amount", "null_marker"))
def test_family_quoted_numeric_workflow_evidence_cannot_accept_wrong_values(
    db_type: str, fault: str | None,
) -> None:
    state = WorkflowProgress({5})
    state.after_call("getDatabaseSchema", {"db_id": 12}, metadata(db_type))
    source = [{"Identifier": "001", "Amount": "1.00", "Label Value": None}]
    state.after_call("readFile", {"file_id": 5}, {"success": True, "totalRows": 1,
                     "headers": list(source[0]), "data": source, "truncated": False})
    identifier = "1" if fault == "text_identifier" else "'001'"
    amount = "1.25" if fault == "amount" else "1.00"
    insert = (f"INSERT INTO {QUOTED} (`IDENTIFIER`,`AMOUNT`,`LABEL VALUE`) "
              f"VALUES ({identifier},{amount},NULL)")
    state.before_call("executeSql", {"db_id": 12, "statement": insert})
    state.after_call("executeSql", {"db_id": 12, "statement": insert}, {"success": True, "affectedRows": 1})
    selected = [{"IDENTIFIER": "1" if fault == "text_identifier" else "001",
                 "AMOUNT": "1.250" if fault == "amount" else 1,
                 "LABEL VALUE": "<NULL>" if fault == "null_marker" else None}]
    state.after_call("executeSql", {"db_id": 12,
                     "statement": f"SELECT * FROM `tenant_db`.{QUOTED}"},
                     {"success": True, "data": selected, "truncated": False})
    if fault is None:
        assert state.status() is None
    elif fault == "null_marker":
        assert "lack a successful subsequent SELECT" in str(state.status())
    else:
        assert "do not cover the source rows" in str(state.status())


def test_unknown_workflow_database_type_is_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported database type"):
        WorkflowSchema().register(12, metadata("unsupported-test-database"))
