"""The Oracle-specific read check and execution share one owned service config."""

from types import SimpleNamespace
from unittest.mock import Mock

from app.adapters.oracle import OracleAdapter
from app.adapters.types import DbConnectionConfig
from app.services import database_tools


def test_oracle_catalog_policy_and_execution_use_one_config(monkeypatch) -> None:
    config = DbConnectionConfig("oracle", "127.0.0.1", 1521, "SERVICE", "owner", "test-only")
    row = SimpleNamespace(db_type="oracle")
    ready = Mock(return_value=row)
    decode = Mock(return_value=config)
    adapter = OracleAdapter()
    policy = Mock(return_value=True)
    execution = Mock(return_value={"success": True, "data": [{"NEXTVAL": 1}]})
    monkeypatch.setattr(database_tools, "_ready_config", ready)
    monkeypatch.setattr(database_tools, "connection_for", decode)
    selected = Mock(return_value=adapter)
    monkeypatch.setattr(database_tools, "get_adapter", selected)
    monkeypatch.setattr(adapter, "is_read_only_for_config", policy)
    monkeypatch.setattr(adapter, "execute", execution)
    statement = 'SELECT t."NEXTVAL" FROM items t'
    database_tools.execute_comparison_read(7, 12, statement)
    ready.assert_called_once_with(7, 12)
    selected.assert_called_once_with("oracle")
    decode.assert_called_once_with(row)
    assert policy.call_args.args == (config, statement)
    assert execution.call_args.args == (config, statement)
    assert execution.call_args.kwargs["trial_mode"] is True
