"""Protocol tests for cancellation dispatch and truthful execution outcomes."""

from __future__ import annotations

import threading
from unittest.mock import Mock

import pytest
from adapter_cancel_fakes import DriverError, FakeConnection, Result, config, install_connection
from sqlalchemy.exc import DBAPIError

from app.adapters import DatabaseExecutionInterrupted, get_adapter
from app.adapters.cancellation import DatabaseWriteOutcomeUnknown, ExecutionWatchdog


def test_pre_cancel_never_connects(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = get_adapter("postgresql")
    connect = Mock(side_effect=AssertionError("must not connect"))
    monkeypatch.setattr(adapter, "_connection", connect)
    signal = threading.Event()
    signal.set()
    with pytest.raises(DatabaseExecutionInterrupted) as captured:
        adapter.execute(config("postgresql"), "UPDATE sample SET value = 1", cancel_event=signal)
    assert captured.value.reason == "cancelled"
    assert captured.value.write_outcome_unknown is False
    assert captured.value.cancel_request_sent is False
    connect.assert_not_called()


def test_postgresql_driver_cancel_confirmation(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = get_adapter("postgresql")
    signal = threading.Event()
    entered = threading.Event()
    cancelled = threading.Event()

    def execute(_statement: str) -> Result:
        entered.set()
        assert cancelled.wait(3)
        raise DBAPIError("UPDATE sample SET value = 1", {}, DriverError(sqlstate="57014"))

    execution = FakeConnection(Mock(side_effect=execute))
    execution.connection.driver_connection.cancel_safe.side_effect = lambda *, timeout: cancelled.set()
    install_connection(monkeypatch, adapter, execution)
    output: list[DatabaseExecutionInterrupted] = []

    def run() -> None:
        try:
            adapter.execute(config("postgresql"), "UPDATE sample SET value = 1", cancel_event=signal)
        except DatabaseExecutionInterrupted as exc:
            output.append(exc)

    worker = threading.Thread(target=run)
    worker.start()
    assert entered.wait(3)
    signal.set()
    worker.join(4)
    assert not worker.is_alive()
    assert len(output) == 1
    assert output[0].cancel_request_sent is True
    assert output[0].server_termination_confirmed is True
    assert output[0].write_outcome_unknown is True
    assert execution.commits == 0
    assert execution.rollbacks == 1


def test_postgresql_cancel_request_can_arrive_after_statement_completes(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = get_adapter("postgresql")
    signal = threading.Event()
    entered = threading.Event()
    cancel_sent = threading.Event()

    def execute(_statement: str) -> Result:
        entered.set()
        assert cancel_sent.wait(3)
        return Result()

    execution = FakeConnection(Mock(side_effect=execute))
    execution.connection.driver_connection.cancel_safe.side_effect = lambda *, timeout: cancel_sent.set()
    install_connection(monkeypatch, adapter, execution)
    output: list[DatabaseExecutionInterrupted] = []

    def run() -> None:
        try:
            adapter.execute(config("postgresql"), "UPDATE sample SET value = 1", cancel_event=signal)
        except DatabaseExecutionInterrupted as exc:
            output.append(exc)

    worker = threading.Thread(target=run)
    worker.start()
    assert entered.wait(3)
    signal.set()
    worker.join(4)
    assert not worker.is_alive()
    assert len(output) == 1
    assert output[0].cancel_request_sent is True
    assert output[0].server_termination_confirmed is False
    assert output[0].write_outcome_unknown is True
    assert execution.commits == 0


def test_mysql_kill_permission_failure_is_not_confirmation(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = get_adapter("mysql")
    signal = threading.Event()
    entered = threading.Event()
    release = threading.Event()

    def execute(_statement: str) -> Result:
        entered.set()
        assert release.wait(3)
        return Result()

    execution = FakeConnection(Mock(side_effect=execute))
    control = FakeConnection(Mock(side_effect=DBAPIError("KILL QUERY 42", {}, DriverError(1227))))
    install_connection(monkeypatch, adapter, execution, control)
    output: list[DatabaseExecutionInterrupted] = []

    def run() -> None:
        try:
            adapter.execute(config("mysql"), "UPDATE sample SET value = 1", cancel_event=signal)
        except DatabaseExecutionInterrupted as exc:
            output.append(exc)

    worker = threading.Thread(target=run)
    worker.start()
    assert entered.wait(3)
    signal.set()
    threading.Event().wait(0.1)
    release.set()
    worker.join(4)
    assert not worker.is_alive()
    assert len(output) == 1
    assert output[0].cancel_request_sent is False
    assert output[0].server_termination_confirmed is False
    assert output[0].write_outcome_unknown is True
    assert isinstance(output[0].cancel_error, DBAPIError)
    control.statement_result.assert_called_once_with("KILL QUERY 42")
    assert execution.commits == 0


def test_mysql_kill_query_requires_server_error_for_confirmation(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = get_adapter("mysql")
    signal = threading.Event()
    entered = threading.Event()
    killed = threading.Event()

    def execute(_statement: str) -> Result:
        entered.set()
        assert killed.wait(3)
        raise DBAPIError("UPDATE sample SET value = 1", {}, DriverError(1317))

    execution = FakeConnection(Mock(side_effect=execute))
    control = FakeConnection(Mock(side_effect=lambda _sql: (killed.set(), Result())[1]))
    install_connection(monkeypatch, adapter, execution, control)
    output: list[DatabaseExecutionInterrupted] = []

    def run() -> None:
        try:
            adapter.execute(config("mysql"), "UPDATE sample SET value = 1", cancel_event=signal)
        except DatabaseExecutionInterrupted as exc:
            output.append(exc)

    worker = threading.Thread(target=run)
    worker.start()
    assert entered.wait(3)
    signal.set()
    worker.join(4)
    assert not worker.is_alive()
    assert len(output) == 1
    assert output[0].cancel_request_sent is True
    assert output[0].server_termination_confirmed is True
    assert output[0].write_outcome_unknown is True
    control.statement_result.assert_called_once_with("KILL QUERY 42")


def test_mysql_write_timeout_uses_kill_query(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = get_adapter("mysql")
    killed = threading.Event()

    def execute(_statement: str) -> Result:
        assert killed.wait(3)
        raise DBAPIError("UPDATE sample SET value = 1", {}, DriverError(1317))

    execution = FakeConnection(Mock(side_effect=execute))
    control = FakeConnection(Mock(side_effect=lambda _sql: (killed.set(), Result())[1]))
    install_connection(monkeypatch, adapter, execution, control)
    with pytest.raises(DatabaseExecutionInterrupted) as captured:
        adapter.execute(config("mysql"), "UPDATE sample SET value = 1", timeout_seconds=1)
    assert captured.value.reason == "timeout"
    assert captured.value.cancel_request_sent is True
    assert captured.value.server_termination_confirmed is True
    assert captured.value.write_outcome_unknown is True
    assert execution.commits == 0


def test_statement_finished_before_signal_never_sends_mysql_kill(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = get_adapter("mysql")
    signal = threading.Event()
    execution = FakeConnection(Mock(return_value=Result()))
    control = FakeConnection(Mock(return_value=Result()))
    install_connection(monkeypatch, adapter, execution, control)
    original_stop = ExecutionWatchdog.stop

    def stop_after_statement(self: ExecutionWatchdog) -> None:
        original_stop(self)
        signal.set()

    monkeypatch.setattr(ExecutionWatchdog, "stop", stop_after_statement)
    with pytest.raises(DatabaseExecutionInterrupted) as captured:
        adapter.execute(config("mysql"), "UPDATE sample SET value = 1", cancel_event=signal)
    assert captured.value.cancel_request_sent is False
    assert captured.value.server_termination_confirmed is False
    assert execution.commits == 0
    control.statement_result.assert_not_called()


def test_cancel_before_commit_does_not_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = get_adapter("postgresql")
    signal = threading.Event()
    result = Result()
    result.close = signal.set  # type: ignore[method-assign]
    execution = FakeConnection(Mock(return_value=result))
    install_connection(monkeypatch, adapter, execution)
    with pytest.raises(DatabaseExecutionInterrupted) as captured:
        adapter.execute(config("postgresql"), "UPDATE sample SET value = 1", cancel_event=signal)
    assert captured.value.server_termination_confirmed is False
    assert captured.value.write_outcome_unknown is True
    assert execution.commits == 0


def test_cancel_after_commit_reports_committed_result(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = get_adapter("postgresql")
    signal = threading.Event()
    execution = FakeConnection(Mock(return_value=Result()))
    execution.on_commit = Mock(side_effect=signal.set)
    install_connection(monkeypatch, adapter, execution)
    response = adapter.execute(config("postgresql"), "UPDATE sample SET value = 1", cancel_event=signal)
    assert response["affectedRows"] == 1
    assert execution.commits == 1


def test_failed_commit_preserves_unknown_write_outcome(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = get_adapter("postgresql")
    execution = FakeConnection(Mock(return_value=Result()))
    execution.on_commit = Mock(side_effect=DBAPIError("COMMIT", {}, DriverError()))
    install_connection(monkeypatch, adapter, execution)
    with pytest.raises(DatabaseWriteOutcomeUnknown):
        adapter.execute(config("postgresql"), "UPDATE sample SET value = 1")


def test_connection_loss_during_write_preserves_unknown_outcome(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = get_adapter("postgresql")
    lost = DBAPIError("UPDATE sample SET value = 1", {}, DriverError(), connection_invalidated=True)
    execution = FakeConnection(Mock(side_effect=lost))
    install_connection(monkeypatch, adapter, execution)
    with pytest.raises(DatabaseWriteOutcomeUnknown) as captured:
        adapter.execute(config("postgresql"), "UPDATE sample SET value = 1")
    assert captured.value.__cause__ is lost
    assert execution.commits == 0
