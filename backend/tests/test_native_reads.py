"""Quoted Oracle NEXTVAL advances sequences; ordinary field scopes remain readable."""

import pytest
from sqlglot import exp

from app.adapters.native_reads import sequence_read
from app.adapters.oracle import OracleAdapter


@pytest.mark.parametrize("statement", [
    "SELECT seq.NEXTVAL FROM DUAL", 'SELECT seq."NEXTVAL" FROM DUAL',
    'SELECT "SCOTT"."Seq"."NEXTVAL" FROM DUAL',
    'WITH c AS (SELECT seq."NEXTVAL" AS value FROM DUAL) SELECT * FROM c',
    'SELECT * FROM (SELECT seq."NEXTVAL" AS value FROM DUAL)',
    'SELECT seq."NEXTVAL" FROM DUAL WHERE EXISTS (SELECT 1 FROM items seq)',
    'SELECT 1 FROM items seq WHERE EXISTS (SELECT "other"."NEXTVAL" FROM DUAL)',
    'SELECT seq."NEXTVAL" FROM DUAL WHERE EXISTS (SELECT t."NEXTVAL" FROM items t)',
    'SELECT seq."NEXTVAL" FROM DUAL seq',
    'WITH c AS (SELECT * FROM DUAL) SELECT c."NEXTVAL" FROM c',
])
def test_quoted_sequence_and_unrelated_aliases_are_not_read_only(statement: str) -> None:
    assert sequence_read(statement, "oracle") is True
    assert OracleAdapter().is_read_only(statement) is False


@pytest.mark.parametrize("statement", [
    'SELECT seq."nextval" FROM DUAL', 'SELECT seq."NextVal" FROM DUAL',
    'SELECT "NEXTVAL" FROM items', 'SELECT items.NEXTVAL FROM items',
    'SELECT items."NEXTVAL" FROM items', 'SELECT t."NEXTVAL" FROM items t',
    'SELECT "t"."NEXTVAL" FROM items "t"',
    'SELECT "SCOTT".items."NEXTVAL" FROM "SCOTT".items',
    'WITH c AS (SELECT "NEXTVAL" FROM items) SELECT c."NEXTVAL" FROM c',
    'SELECT c."NEXTVAL" FROM (SELECT "NEXTVAL" FROM items) c',
    'SELECT 1 FROM items t WHERE EXISTS (SELECT 1 FROM DUAL WHERE t."NEXTVAL"=1)',
    'SELECT t."NEXTVAL" FROM items t JOIN other o ON t.id=o.id',
    'WITH c AS (SELECT * FROM items) SELECT c."NEXTVAL" FROM c',
    'SELECT c."NEXTVAL" FROM (SELECT * FROM items) c',
    'WITH c AS (SELECT t.* FROM items t) SELECT c."NEXTVAL" FROM c',
])
def test_ordinary_fields_and_exact_quoted_spelling_stay_read_only(statement: str) -> None:
    def verified(column: exp.Column, source: exp.Expression) -> bool:
        return isinstance(source, exp.Table) and source.name == "items" and column.name == "NEXTVAL"
    assert sequence_read(statement, "oracle", field_exists=verified) is False


def test_alias_presence_alone_does_not_prove_an_ordinary_field() -> None:
    assert OracleAdapter().is_read_only('SELECT t."NEXTVAL" FROM items t') is False
    assert OracleAdapter().is_read_only('SELECT c."NEXTVAL" FROM (SELECT 1 AS "NEXTVAL" FROM DUAL) c') is True


@pytest.mark.parametrize("operation", ["UNION ALL", "UNION", "INTERSECT", "MINUS"])
def test_set_operation_with_scope_keeps_cte_fields_and_sequence_rejection(operation: str) -> None:
    statement = ("WITH c AS (SELECT 1 AS NEXTVAL FROM DUAL) SELECT c.NEXTVAL FROM c "
                 + operation + " SELECT c.NEXTVAL FROM c")
    assert sequence_read(statement, "oracle", field_exists=lambda *_: False) is False
    assert OracleAdapter().is_read_only(statement) is True
    advancing = statement.replace("1 AS NEXTVAL", 'seq."NEXTVAL" AS NEXTVAL')
    assert sequence_read(advancing, "oracle", field_exists=lambda *_: False) is True
    assert OracleAdapter().is_read_only(advancing) is False
