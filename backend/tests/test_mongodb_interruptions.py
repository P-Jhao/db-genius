"""Actual bounded read interruptions without claiming a Mongo cancel RPC."""

from __future__ import annotations

import json
import threading
from time import monotonic, sleep

from pymongo import MongoClient
from test_mongodb_integration import mongo_target as mongo_target_fixture

from app.adapters import DatabaseExecutionInterrupted, DbConnectionConfig
from app.adapters.mongodb import MongoDbAdapter

mongo_target = mongo_target_fixture
Target = tuple[MongoDbAdapter, DbConnectionConfig, MongoClient[dict[str, object]]]


def slow_command() -> str:
    return json.dumps({"collection": "items", "operation": "aggregate", "pipeline": [
        {"$project": {"v": {"$range": [0, 500000]}}}, {"$unwind": "$v"},
        {"$group": {"_id": None, "total": {"$sum": "$v"}}},
    ]})


def active(client: MongoClient[dict[str, object]], database: str) -> int:
    reply = client.admin.command({"currentOp": 1, "$ownOps": True, "active": True,
                                  "ns": f"{database}.items", "command.aggregate": "items"})
    operations = reply.get("inprog")
    if not isinstance(operations, list):
        raise TypeError("currentOp must return an operation array")
    return len(operations)


def wait_exit(client: MongoClient[dict[str, object]], database: str) -> None:
    deadline = monotonic() + 5
    while active(client, database):
        assert monotonic() < deadline, "server read remains active after its maxTimeMS"
        sleep(0.05)


def test_real_read_timeout_distinguishes_server_confirmation_from_driver_timeout(mongo_target: Target) -> None:
    adapter, config, client = mongo_target
    before = client[config.db_name]["items"].count_documents({})
    started = monotonic()
    try:
        adapter.execute(config, slow_command(), timeout_seconds=1)
    except DatabaseExecutionInterrupted as error:
        assert error.reason == "timeout"
        assert error.cancel_request_sent is False
        assert error.write_outcome_unknown is False
        assert isinstance(error.server_termination_confirmed, bool)
        if error.server_termination_confirmed:
            from pymongo.errors import ExecutionTimeout
            assert isinstance(error.__cause__, ExecutionTimeout)
        else:
            from pymongo.errors import NetworkTimeout
            assert isinstance(error.__cause__, NetworkTimeout)
    else:
        raise AssertionError("bounded synthetic aggregation completed without timeout")
    assert monotonic() - started < 5
    wait_exit(client, config.db_name)
    assert client[config.db_name]["items"].count_documents({}) == before


def test_real_inflight_cancel_is_observed_without_claiming_instant_server_kill(mongo_target: Target) -> None:
    adapter, config, client = mongo_target
    signal = threading.Event()
    errors: list[Exception] = []

    def run() -> None:
        try:
            adapter.execute(config, slow_command(), timeout_seconds=2, cancel_event=signal)
        except Exception as error:  # noqa: BLE001 - checked after worker returns
            errors.append(error)

    worker = threading.Thread(target=run)
    worker.start()
    try:
        deadline = monotonic() + 3
        while not active(client, config.db_name):
            assert worker.is_alive() and monotonic() < deadline, "read never became visible on server"
            sleep(0.01)
        signal.set()
        worker.join(6)
        assert not worker.is_alive()
        assert len(errors) == 1 and isinstance(errors[0], DatabaseExecutionInterrupted)
        interrupted = errors[0]
        assert interrupted.reason == "cancelled"
        assert interrupted.cancel_request_sent is False
        assert interrupted.write_outcome_unknown is False
        wait_exit(client, config.db_name)
        assert client[config.db_name]["items"].count_documents({}) == 125
    finally:
        signal.set()
        worker.join(6)
