"""Family cancellation and setup failures retain accepted execution semantics."""

from __future__ import annotations

import threading
from unittest.mock import Mock

import pytest
from adapter_cancel_fakes import FakeConnection, Result, install_connection
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError
from test_mysql_family import FAMILY, config

from app.adapters import DatabaseExecutionInterrupted, DbConnectionConfig, get_adapter


@pytest.mark.parametrize("db_type", FAMILY)
def test_precancelled_family_statement_never_connects(db_type: str, monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = get_adapter(db_type)
    connection = Mock(side_effect=AssertionError("must not connect"))
    monkeypatch.setattr(adapter, "_connection", connection)
    signal = threading.Event()
    signal.set()
    with pytest.raises(DatabaseExecutionInterrupted) as captured:
        adapter.execute(config(db_type), "UPDATE sample SET value = 1", cancel_event=signal)
    assert captured.value.cancel_request_sent is False
    assert captured.value.server_termination_confirmed is False
    assert captured.value.write_outcome_unknown is False
    connection.assert_not_called()


@pytest.mark.parametrize("db_type", FAMILY)
def test_timeout_setup_failure_never_dispatches_sql(db_type: str, monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = get_adapter(db_type)
    execution = FakeConnection(Mock(return_value=Result()))
    install_connection(monkeypatch, adapter, execution)
    monkeypatch.setattr(adapter, "_set_timeout", Mock(side_effect=SQLAlchemyError("variable unsupported")))
    with pytest.raises(SQLAlchemyError, match="variable unsupported"):
        adapter.execute(config(db_type), "INSERT INTO sample VALUES (1)")
    execution.statement_result.assert_not_called()
    assert execution.commits == 0 and execution.rollbacks == 1


@pytest.mark.parametrize("db_type", ("tidb", "doris", "starrocks", "oceanbase"))
@pytest.mark.parametrize("read_only", (False, True))
def test_inflight_proxy_cancel_preserves_unconfirmed_outcome(
    db_type: str, read_only: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = get_adapter(db_type)
    signal, entered, cancel_attempted = threading.Event(), threading.Event(), threading.Event()
    original_cancel = adapter._cancel_running_statement

    def cancel(target: DbConnectionConfig, connection: Connection, connection_id: int | None) -> None:
        try:
            original_cancel(target, connection, connection_id)
        finally:
            cancel_attempted.set()

    def execute(_statement: str) -> Result:
        entered.set()
        assert cancel_attempted.wait(3), "cancel was not observed"
        return Result()

    execution = FakeConnection(Mock(side_effect=execute))
    control = FakeConnection(Mock(return_value=Result()))
    install_connection(monkeypatch, adapter, execution, control)
    monkeypatch.setattr(adapter, "_cancel_running_statement", cancel)
    errors: list[Exception] = []

    def run() -> None:
        try:
            adapter.execute(config(db_type), "SELECT 1" if read_only else "UPDATE sample SET value = 1",
                            cancel_event=signal)
        except Exception as exc:  # noqa: BLE001 - checked after worker returns
            errors.append(exc)

    worker = threading.Thread(target=run)
    worker.start()
    try:
        assert entered.wait(3)
        signal.set()
        worker.join(4)
        assert not worker.is_alive()
        assert len(errors) == 1 and isinstance(errors[0], DatabaseExecutionInterrupted)
        interrupted = errors[0]
        assert interrupted.reason == "cancelled"
        assert interrupted.cancel_request_sent is False
        assert interrupted.server_termination_confirmed is False
        assert interrupted.write_outcome_unknown is (not read_only)
        assert isinstance(interrupted.cancel_error, RuntimeError)
        assert "unpinned proxy" in str(interrupted.cancel_error)
        assert execution.commits == 0 and execution.rollbacks == 1
        control.statement_result.assert_not_called()
    finally:
        signal.set()
        cancel_attempted.set()
        worker.join(4)
