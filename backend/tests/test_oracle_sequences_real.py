"""Real quoted pseudocolumn advancement and the trial/comparison read boundary."""

from uuid import uuid4

import pytest
from native_database_fixtures import oracle_target as oracle_fixture
from native_database_fixtures import wait_oracle_ddl
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError
from test_workflow_integration import DB_ID, USER_ID, install_target

from app.adapters.oracle import OracleAdapter
from app.adapters.safety import UnsafeStatement
from app.adapters.types import DbConnectionConfig
from app.core.errors import BusinessError
from app.services import database_tools

oracle_target = oracle_fixture


def test_real_quoted_sequences_are_denied_without_rejecting_ordinary_fields(
    oracle_target: tuple[DbConnectionConfig, Engine], monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, engine = oracle_target
    table = "field_" + uuid4().hex[:12]
    sequence = "adv_" + uuid4().hex[:12]
    created: list[str] = []
    catalog_calls: list[dict[str, object]] = []
    def observe(_connection, _cursor, statement, parameters, _context, _many):
        if statement.startswith("SELECT 1 FROM ALL_TAB_COLUMNS"):
            assert isinstance(parameters, dict)
            catalog_calls.append(parameters.copy())
    event.listen(Engine, "before_cursor_execute", observe)
    adapter = OracleAdapter()
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(f"CREATE SEQUENCE {sequence} NOCACHE")
            created.append("sequence")
            connection.exec_driver_sql(f'CREATE TABLE {table} ("NEXTVAL" NUMBER, "nextval" NUMBER)')
            created.append("table")
            connection.exec_driver_sql(f"INSERT INTO {table} VALUES (701,702)")
        wait_oracle_ddl(engine, [sequence.upper(), table.upper()])
        with engine.connect() as connection:
            owner = connection.exec_driver_sql("SELECT SYS_CONTEXT('USERENV','CURRENT_SCHEMA') FROM DUAL").scalar_one()
            assert isinstance(owner, str) and owner
            qualified = connection.dialect.identifier_preparer.quote_identifier(owner) + "." + table
        install_target(monkeypatch, config)
        def next_number() -> int:
            with engine.connect() as connection:
                return int(connection.exec_driver_sql(
                    "SELECT last_number FROM user_sequences WHERE sequence_name=:name",
                    {"name": sequence.upper()},
                ).scalar_one())
        assert next_number() == 1
        denied = [f"SELECT {sequence}.NEXTVAL FROM DUAL", f'SELECT {sequence}."NEXTVAL" FROM DUAL',
                  f'SELECT {sequence}."NEXTVAL" FROM DUAL {sequence}',
                  f'WITH c AS (SELECT {sequence}."NEXTVAL" AS value FROM DUAL) SELECT value FROM c',
                  f'SELECT * FROM (SELECT {sequence}."NEXTVAL" AS value FROM DUAL)',
                  f'SELECT {sequence}."NEXTVAL" FROM DUAL WHERE EXISTS (SELECT 1 FROM {table} {sequence})']
        for statement in denied:
            with pytest.raises(UnsafeStatement):
                adapter.execute(config, statement, trial_mode=True)
            with pytest.raises(BusinessError, match="migration writes"):
                database_tools.execute_comparison_read(USER_ID, DB_ID, statement)
        for operation, expected in (("UNION ALL", [{"NEXTVAL": 1}, {"NEXTVAL": 1}]),
                                    ("UNION", [{"NEXTVAL": 1}]), ("INTERSECT", [{"NEXTVAL": 1}]),
                                    ("MINUS", [])):
            statement = ("WITH c AS (SELECT 1 AS NEXTVAL FROM DUAL) SELECT c.NEXTVAL FROM c "
                         + operation + " SELECT c.NEXTVAL FROM c")
            before_calls = len(catalog_calls)
            assert adapter.execute(config, statement, trial_mode=True)["data"] == expected
            assert database_tools.execute_comparison_read(USER_ID, DB_ID, statement)["data"] == expected
            assert len(catalog_calls) == before_calls
            advancing = statement.replace("1 AS NEXTVAL", f'{sequence}."NEXTVAL" AS NEXTVAL')
            with pytest.raises(UnsafeStatement):
                adapter.execute(config, advancing, trial_mode=True)
            with pytest.raises(BusinessError, match="migration writes"):
                database_tools.execute_comparison_read(USER_ID, DB_ID, advancing)
        assert next_number() == 1
        ordinary = adapter.execute(config, f'SELECT {sequence}."NEXTVAL" AS value FROM DUAL')
        assert ordinary["data"] == [{"VALUE": 1}]
        assert next_number() == 2
        fields = [f'SELECT {table}.NEXTVAL AS a,{table}."NEXTVAL" AS b,{table}."nextval" AS c FROM {table}',
                  f'SELECT t."NEXTVAL" AS a,t."NEXTVAL" AS b,t."nextval" AS c FROM {table} t',
                  (f'WITH c AS (SELECT "NEXTVAL","nextval" FROM {table}) '
                   'SELECT c."NEXTVAL" AS a,c."NEXTVAL" AS b,c."nextval" AS c FROM c'),
                  (f'SELECT {sequence}."NEXTVAL" AS a,{sequence}."NEXTVAL" AS b,{sequence}."nextval" AS c '
                   f'FROM {table} {sequence}'),
                  (f'WITH c AS (SELECT * FROM {table}) '
                   'SELECT c."NEXTVAL" AS a,c."NEXTVAL" AS b,c."nextval" AS c FROM c'),
                  (f'SELECT c."NEXTVAL" AS a,c."NEXTVAL" AS b,c."nextval" AS c '
                   f'FROM (SELECT * FROM {table}) c'),
                  (f'SELECT {qualified}."NEXTVAL" AS a,{qualified}."NEXTVAL" AS b,{qualified}."nextval" AS c '
                   f'FROM {qualified}')]
        for statement in fields:
            before_calls = len(catalog_calls)
            result = database_tools.execute_comparison_read(USER_ID, DB_ID, statement)
            assert result["data"] == [{"A": 701, "B": 701, "C": 702}]
            observed = catalog_calls[before_calls:]
            expected_calls = 0 if statement.startswith("WITH c AS (SELECT \"NEXTVAL\"") else 3
            assert len(observed) == expected_calls
            assert all(parameters == {"owner": owner, "table_name": table.upper(), "column_name": "NEXTVAL"}
                       for parameters in observed)
        print("Oracle actual bound catalog calls:", len(catalog_calls))
        assert next_number() == 2
        with pytest.raises(DBAPIError) as invalid:
            adapter.execute(config, f'SELECT {sequence}."nextval" FROM DUAL')
        assert getattr(invalid.value.orig.args[0], "code", None) == 904
        assert next_number() == 2
    finally:
        event.remove(Engine, "before_cursor_execute", observe)
        with engine.begin() as connection:
            if "table" in created:
                connection.exec_driver_sql(f"DROP TABLE {table} PURGE")
            if "sequence" in created:
                connection.exec_driver_sql(f"DROP SEQUENCE {sequence}")
