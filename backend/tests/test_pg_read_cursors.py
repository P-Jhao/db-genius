"""Real PostgreSQL command cursors, bounded query streams and cancellation."""

import threading
from time import monotonic, sleep
from uuid import uuid4

import pytest
from sqlalchemy import event
from test_adapters_integration import _config

from app.adapters import DatabaseExecutionInterrupted, get_adapter
from app.adapters.safety import UnsafeStatement


@pytest.mark.parametrize("trial_mode", [False, True])
@pytest.mark.parametrize("statement,server_cursor", [
    ("SHOW ALL", False), ("SHOW statement_timeout", False),
    ("EXPLAIN SELECT * FROM generate_series(1,1000)", False),
    ("EXPLAIN ANALYZE SELECT 1", False),
    ("SELECT * FROM generate_series(1,10000)", True),
    ("WITH input AS (SELECT 7 AS value) SELECT value FROM input", True),
    ("SELECT 1 AS value UNION ALL SELECT 2", True),
    ("SELECT 1 AS value INTERSECT SELECT 1", True),
    ("SELECT 1 AS value EXCEPT SELECT 2", True),
])
def test_real_pg_read_commands_and_query_streams_are_bounded(
    monkeypatch: pytest.MonkeyPatch, trial_mode: bool, statement: str, server_cursor: bool,
) -> None:
    adapter = get_adapter("postgresql")
    config = _config("postgresql")
    original = adapter._engine
    seen: list[bool] = []

    def engine_for(*args):
        engine = original(*args)

        def observe(_connection, cursor, executed, _parameters, _context, _executemany):
            if executed == statement:
                seen.append(isinstance(getattr(cursor, "name", None), str))

        event.listen(engine, "after_cursor_execute", observe)
        return engine

    monkeypatch.setattr(adapter, "_engine", engine_for)
    result = adapter.execute(config, statement, trial_mode=trial_mode, max_rows=7)
    assert result["success"] is True and 0 < result["rowCount"] <= 7
    assert seen == [server_cursor]  # Inspect the real psycopg cursor, not a mocked option.
    if "10000" in statement or statement == "SHOW ALL":
        assert result["rowCount"] == 7 and result["truncated"] is True
    else:
        assert result["truncated"] is False


@pytest.mark.parametrize("statement", [
    "SELECT 1 INTO cursor_unwanted",
    "WITH changed AS (DELETE FROM orders RETURNING *) SELECT * FROM changed",
    "EXPLAIN ANALYZE DELETE FROM orders",
    "SELECT 1; DELETE FROM orders",
])
def test_read_only_write_rejection_occurs_before_opening_a_driver(
    monkeypatch: pytest.MonkeyPatch, statement: str,
) -> None:
    adapter = get_adapter("postgresql")
    config = _config("postgresql")
    monkeypatch.setattr(adapter, "_connection", lambda *_args:
                        pytest.fail("Unsafe read-only request opened a database connection"))
    with pytest.raises(UnsafeStatement):
        adapter.execute(config, statement, trial_mode=True)


def test_real_explain_analyze_command_cursor_is_cancelled_by_driver() -> None:
    adapter = get_adapter("postgresql")
    config = _config("postgresql")
    marker = f"cursor_cancel_{uuid4().hex}"
    statement = f"EXPLAIN ANALYZE SELECT pg_sleep(10) /* {marker} */"
    signal = threading.Event()
    errors: list[Exception] = []

    def run() -> None:
        try:
            adapter.execute(config, statement, trial_mode=True, cancel_event=signal, timeout_seconds=15)
        except Exception as error:  # noqa: BLE001 - inspect the exact driver outcome after joining
            errors.append(error)

    worker = threading.Thread(target=run)
    worker.start()
    observer_sql = ("SELECT COUNT(*) FROM pg_stat_activity WHERE pid <> pg_backend_pid() "
                    f"AND state='active' AND strpos(query,'{marker}')>0 "
                    "AND wait_event='PgSleep'")
    try:
        with adapter._connection(config, 5) as observer:
            deadline = monotonic() + 5
            while int(observer.exec_driver_sql(observer_sql).scalar_one()) == 0:
                assert monotonic() < deadline, "EXPLAIN ANALYZE did not begin the target query"
                observer.rollback()
                sleep(0.05)
        signal.set()
        worker.join(6)
        assert not worker.is_alive()
        assert len(errors) == 1 and isinstance(errors[0], DatabaseExecutionInterrupted)
        assert errors[0].reason == "cancelled" and errors[0].cancel_request_sent is True
        assert errors[0].server_termination_confirmed is True
        assert errors[0].write_outcome_unknown is False
        with adapter._connection(config, 5) as observer:
            assert observer.exec_driver_sql(observer_sql).scalar_one() == 0
    finally:
        signal.set()
        worker.join(16)
