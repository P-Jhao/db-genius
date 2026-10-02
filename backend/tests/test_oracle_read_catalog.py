"""Oracle field evidence uses the owned configuration, exact names and bound values."""

import threading
from contextlib import contextmanager
from unittest.mock import Mock

import oracledb
import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.adapters.cancellation import DatabaseExecutionInterrupted
from app.adapters.oracle import OracleAdapter
from app.adapters.safety import UnsafeStatement
from app.adapters.types import DbConnectionConfig


def config() -> DbConnectionConfig:
    return DbConnectionConfig("oracle", "127.0.0.1", 1521, "SERVICE", "login", "fake-secret")


def install(monkeypatch: pytest.MonkeyPatch, *, exists: bool = True, failure: bool = False):
    adapter = OracleAdapter()
    connection = Mock()
    connection.connection.driver_connection = Mock(spec=oracledb.Connection)
    calls: list[tuple[str, object]] = []
    opens: list[tuple[DbConnectionConfig, int]] = []
    def query(statement: str, parameters: object = None) -> Mock:
        calls.append((statement, parameters))
        result = Mock()
        if "CURRENT_SCHEMA" in statement:
            result.scalar_one.return_value = "ActualUser"
        elif "ALL_TAB_COLUMNS" in statement:
            if failure:
                raise SQLAlchemyError("catalog unavailable")
            result.scalar_one_or_none.return_value = 1 if exists else None
        elif statement != "SET TRANSACTION READ ONLY":
            pytest.fail("Unverified read reached target SQL")
        return result
    connection.exec_driver_sql.side_effect = query
    @contextmanager
    def connected(target: DbConnectionConfig, timeout: int):
        opens.append((target, timeout))
        yield connection
    monkeypatch.setattr(adapter, "_connection", connected)
    return adapter, calls, opens


@pytest.mark.parametrize("statement,owner,table", [
    ('SELECT t."NEXTVAL",t."NEXTVAL" FROM items t', "ActualUser", "ITEMS"),
    ('SELECT "t"."NEXTVAL" FROM "MixedTable" "t"', "ActualUser", "MixedTable"),
    ('SELECT t."NEXTVAL" FROM "OtherUser"."lower" t', "OtherUser", "lower"),
    ('SELECT OTHER.items."NEXTVAL" FROM OTHER.items', "OTHER", "ITEMS"),
    ('SELECT t."NEXTVAL" FROM "table\'quote" t', "ActualUser", "table'quote"),
])
def test_catalog_uses_exact_parameterized_identifiers_and_a_per_check_cache(
    monkeypatch: pytest.MonkeyPatch, statement: str, owner: str, table: str,
) -> None:
    adapter, calls, opens = install(monkeypatch)
    target = config()
    assert adapter.is_read_only_for_config(target, statement, timeout_seconds=7) is True
    assert opens == [(target, 7)]
    catalog = [(sql, parameters) for sql, parameters in calls if "ALL_TAB_COLUMNS" in sql]
    assert len(catalog) == 1
    assert catalog[0][1] == {"owner": owner, "table_name": table, "column_name": "NEXTVAL"}
    assert "table_name=:table_name" in catalog[0][0].lower()
    assert calls[0] == ("SET TRANSACTION READ ONLY", None)


def test_missing_field_proof_rejects_direct_adapter_trial_before_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter, calls, opens = install(monkeypatch, exists=False)
    statement = 'SELECT seq."NEXTVAL" FROM DUAL seq'
    assert adapter.is_read_only_for_config(config(), statement) is False
    with pytest.raises(UnsafeStatement):
        adapter.execute(config(), statement, trial_mode=True)
    assert len(opens) == 2 and all(statement != sql for sql, _params in calls)


def test_catalog_failure_is_an_explicit_readonly_rejection(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter, _calls, _opens = install(monkeypatch, failure=True)
    with pytest.raises(UnsafeStatement, match="catalog"):
        adapter.execute(config(), 'SELECT t."NEXTVAL" FROM items t', trial_mode=True)


def test_static_cte_projection_does_not_open_a_catalog_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter, calls, opens = install(monkeypatch)
    assert adapter.is_read_only_for_config(config(), 'WITH c("NEXTVAL") AS (SELECT 1 FROM DUAL) '
                                                   'SELECT c."NEXTVAL" FROM c') is True
    assert calls == [] and opens == []


def test_pre_cancelled_field_read_does_not_open_a_catalog_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter, calls, opens = install(monkeypatch)
    signal = threading.Event()
    signal.set()
    with pytest.raises(DatabaseExecutionInterrupted) as captured:
        adapter.execute(config(), 'SELECT t."NEXTVAL" FROM items t', trial_mode=True, cancel_event=signal)
    assert captured.value.write_outcome_unknown is False
    assert calls == [] and opens == []
