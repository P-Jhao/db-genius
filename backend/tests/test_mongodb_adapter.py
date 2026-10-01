"""MongoDB adapter protocol and security checks without a live target server."""

from __future__ import annotations

import json
import threading
from contextlib import nullcontext
from unittest.mock import MagicMock, Mock

import pytest
from bson import Code, Int64, ObjectId
from pymongo.errors import ExecutionTimeout, NetworkTimeout, OperationFailure

from app.adapters import DatabaseExecutionInterrupted, DbConnectionConfig, get_adapter
from app.adapters.mongodb import MongoDbAdapter
from app.adapters.mongodb_command import UnsafeMongoCommand


def config(*, username: str = "", password: str = "") -> DbConnectionConfig:
    return DbConnectionConfig("mongodb", "localhost", 27017, "sample", username, password)


def command(operation: str, **other: object) -> str:
    return json.dumps({"collection": "items", "operation": operation, **other})


def fake_client(monkeypatch: pytest.MonkeyPatch, adapter: MongoDbAdapter) -> MagicMock:
    client = MagicMock()
    monkeypatch.setattr(adapter, "_client", Mock(return_value=nullcontext(client)))
    return client


def test_registry_preserves_all_database_types() -> None:
    for db_type in ("mysql", "postgresql", "mariadb", "tidb", "doris", "starrocks", "oceanbase"):
        assert get_adapter(db_type).db_type == db_type
    assert isinstance(get_adapter("mongodb"), MongoDbAdapter)


def test_no_auth_and_authenticated_client_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    constructor = Mock(return_value=MagicMock())
    monkeypatch.setattr("app.adapters.mongodb.MongoClient", constructor)
    adapter = MongoDbAdapter()
    adapter._client(config(), 30)
    assert "username" not in constructor.call_args.kwargs
    assert "password" not in constructor.call_args.kwargs
    adapter._client(config(username="name", password="p@:/#word"), 30)
    assert constructor.call_args.kwargs["username"] == "name"
    assert constructor.call_args.kwargs["password"] == "p@:/#word"
    assert constructor.call_args.kwargs["socketTimeoutMS"] == 30000
    with pytest.raises(ValueError):
        adapter.validate_config(config(username="name"))


def test_connection_pings_requested_database(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = MongoDbAdapter()
    client = fake_client(monkeypatch, adapter)
    client["sample"].command.return_value = {"ok": 1.0}
    assert adapter.test_connection(config()) is True
    client["sample"].command.assert_called_once_with("ping")
    client["sample"].command.side_effect = OperationFailure("synthetic authentication failure", code=18)
    assert adapter.test_connection(config()) is False


@pytest.mark.parametrize("statement", [
    '{"collection":"items","operation":"find","operation":"drop"}',
    '{"collection":"items","operation":"find"}{"collection":"other","operation":"find"}',
    command("drop"),
    command("find", filter={"$where": "sleep(10000)"}),
    command("find", filter={"$expr": {"$function": {"body": "return true"}}}),
    command("aggregate", pipeline=[{"$out": "other"}]),
    command("aggregate", pipeline=[{"$merge": {"into": "other"}}]),
    command("aggregate", pipeline=[{"$lookup": {"from": "other", "pipeline": [{"$out": "x"}]}}]),
    command("find", limit=0),
    command("find", limit=True),
    command("find", pipeline=[]),
    command("find", arbitrary=True),
    '[{"collection":"items","operation":"find"}]',
    'not JSON',
])
def test_unsafe_commands_never_open_connection(
    monkeypatch: pytest.MonkeyPatch, statement: str,
) -> None:
    adapter = MongoDbAdapter()
    opener = Mock(side_effect=AssertionError("unsafe command reached driver"))
    monkeypatch.setattr(adapter, "_client", opener)
    assert adapter.is_read_only(statement) is False
    with pytest.raises(UnsafeMongoCommand):
        adapter.execute(config(), statement)
    opener.assert_not_called()


def test_find_aggregate_count_distinct_and_row_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = MongoDbAdapter()
    client = fake_client(monkeypatch, adapter)
    collection = client["sample"]["items"]
    cursor = collection.find.return_value.limit.return_value.max_time_ms.return_value
    cursor.__iter__.return_value = iter([{"n": index} for index in range(4)])
    found = adapter.execute(config(), command("find", filter={"n": {"$gte": 0}}, limit=300), max_rows=3)
    assert found == {"success": True, "rowCount": 3,
                     "result": [{"n": 0}, {"n": 1}, {"n": 2}], "truncated": True}
    collection.find.return_value.limit.assert_called_with(4)
    collection.find.return_value.limit.return_value.max_time_ms.assert_called_with(30000)

    collection.aggregate.return_value.__iter__.return_value = iter([{"n": index} for index in range(4)])
    aggregated = adapter.execute(config(), command("aggregate", pipeline=[{"$match": {"n": 1}}]),
                                 max_rows=3)
    assert aggregated["rowCount"] == 3 and aggregated["truncated"] is True
    assert collection.aggregate.call_args.args[0][-1] == {"$limit": 4}
    assert collection.aggregate.call_args.kwargs["maxTimeMS"] == 30000

    collection.count_documents.return_value = 125
    counted = adapter.execute(config(), command("count", filter={"active": True}))
    assert counted["result"] == 125
    collection.count_documents.assert_called_with({"active": True}, maxTimeMS=30000)

    collection.distinct.return_value = [ObjectId(), "x", "y"]
    distinct = adapter.execute(config(), command("distinct", field="tag"), max_rows=2)
    payload = distinct["result"]
    assert isinstance(payload, dict)
    values = payload["values"]
    assert isinstance(values, list) and values[1] == "x"
    assert distinct["truncated"] is True
    collection.distinct.assert_called_with("tag", {}, maxTimeMS=30000)


def test_extended_json_filter_reaches_driver_as_bson(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = MongoDbAdapter()
    client = fake_client(monkeypatch, adapter)
    collection = client["sample"]["items"]
    collection.find.return_value.limit.return_value.max_time_ms.return_value.__iter__.return_value = iter([])
    target = ObjectId()
    adapter.execute(config(), command("find", filter={"_id": {"$oid": str(target)}}))
    assert collection.find.call_args.args[0] == {"_id": target}


def test_metadata_samples_50_and_marks_partial_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = MongoDbAdapter()
    client = fake_client(monkeypatch, adapter)
    database = client["sample"]
    database.list_collection_names.return_value = ["good", "bad"]
    good = MagicMock()
    bad = MagicMock()
    database.__getitem__.side_effect = {"good": good, "bad": bad}.__getitem__
    docs = [{"_id": ObjectId(), "first": "a"}, {"second": 2, "stored_long": Int64(7),
             "script": Code("return 1"), "scoped": Code("return n", {"n": 1})}]
    good.find.return_value.limit.return_value.max_time_ms.return_value.__iter__.return_value = iter(docs)
    good.list_indexes.return_value = [{"name": "ix_first", "key": {"first": 1}}]
    good.estimated_document_count.return_value = 230
    bad.find.side_effect = ExecutionTimeout("slow")
    metadata = adapter.extract_metadata(config())
    assert metadata["incomplete"] is True and "bad" in (metadata["errorMessage"] or "")
    good.find.return_value.limit.assert_called_with(50)
    table = metadata["tables"][0]
    assert table["rowCount"] == 230
    assert [column["name"] for column in table["columns"]] == [
        "_id", "first", "second", "stored_long", "script", "scoped",
    ]
    assert [column["type"] for column in table["columns"]][3:] == [
        "long", "javascript", "javascript_with_scope",
    ]
    assert table["columns"][0]["type"] == "objectId"
    assert table["columns"][0]["primaryKey"] is True
    assert table["indexes"] == [{"name": "ix_first", "columns": ["first"]}]
    assert "Error reading metadata" in adapter.generate_document(config())


def test_timeout_and_cancel_outcome_is_truthful(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = MongoDbAdapter()
    client = fake_client(monkeypatch, adapter)
    collection = client["sample"]["items"]
    signal = threading.Event()
    signal.set()
    with pytest.raises(DatabaseExecutionInterrupted) as before:
        adapter.execute(config(), command("count"), cancel_event=signal)
    assert before.value.cancel_request_sent is False
    collection.count_documents.assert_not_called()
    signal.clear()

    collection.count_documents.side_effect = ExecutionTimeout("maxTimeMS expired")
    with pytest.raises(DatabaseExecutionInterrupted) as timed:
        adapter.execute(config(), command("count"))
    assert timed.value.reason == "timeout" and timed.value.server_termination_confirmed is True
    collection.count_documents.side_effect = NetworkTimeout("socket timed out")
    with pytest.raises(DatabaseExecutionInterrupted) as network:
        adapter.execute(config(), command("count"))
    assert network.value.server_termination_confirmed is False

    def cancelled_count(*_args: object, **_kwargs: object) -> int:
        signal.set()
        return 1

    collection.count_documents.side_effect = cancelled_count
    with pytest.raises(DatabaseExecutionInterrupted) as after:
        adapter.execute(config(), command("count"), cancel_event=signal)
    assert after.value.reason == "cancelled"
    assert after.value.server_termination_confirmed is False


@pytest.mark.parametrize("exception, confirmed", [
    (ExecutionTimeout("maxTimeMS expired"), True),
    (NetworkTimeout("socket timed out"), False),
])
def test_inflight_cancellation_wins_over_elapsed_timeout(
    monkeypatch: pytest.MonkeyPatch, exception: Exception, confirmed: bool,
) -> None:
    adapter = MongoDbAdapter()
    client = fake_client(monkeypatch, adapter)
    signal = threading.Event()

    def interrupted_count(*_args: object, **_kwargs: object) -> int:
        signal.set()
        raise exception

    client["sample"]["items"].count_documents.side_effect = interrupted_count
    with pytest.raises(DatabaseExecutionInterrupted) as stopped:
        adapter.execute(config(), command("count"), cancel_event=signal)
    assert stopped.value.reason == "cancelled"
    assert stopped.value.cancel_request_sent is False
    assert stopped.value.server_termination_confirmed is confirmed
    assert stopped.value.write_outcome_unknown is False


@pytest.mark.parametrize("code", (2, 9, 14, 168))
def test_only_known_read_query_errors_return_safe_diagnostics(
    monkeypatch: pytest.MonkeyPatch, code: int,
) -> None:
    adapter = MongoDbAdapter()
    client = fake_client(monkeypatch, adapter)
    error = OperationFailure("unneeded full response", code=code,
                             details={"errmsg": "invalid filter synthetic@password", "private": "omit"})
    client["sample"]["items"].count_documents.side_effect = error
    failed = adapter.execute(config(username="user", password="synthetic@password"), command("count"))
    assert failed == {"success": False, "error": "invalid filter [REDACTED]", "errorCode": code}
    client["sample"]["items"].count_documents.assert_called_once()


@pytest.mark.parametrize("code", (13, 18, 50, 91, 99999))
def test_authorization_authentication_and_unknown_errors_never_enter_repair(
    monkeypatch: pytest.MonkeyPatch, code: int,
) -> None:
    adapter = MongoDbAdapter()
    client = fake_client(monkeypatch, adapter)
    error = OperationFailure("synthetic hard failure", code=code, details={"errmsg": "hard failure"})
    client["sample"]["items"].count_documents.side_effect = error
    with pytest.raises(OperationFailure) as failed:
        adapter.execute(config(), command("count"))
    assert failed.value is error
