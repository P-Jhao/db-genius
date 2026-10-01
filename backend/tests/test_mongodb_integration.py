"""Real MongoDB acceptance; missing explicit target settings are skips."""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from bson import Binary, Decimal128, Int64, ObjectId, json_util
from pymongo import MongoClient

from app.adapters import DatabaseExecutionInterrupted, DbConnectionConfig
from app.adapters.mongodb import MongoDbAdapter
from app.adapters.mongodb_command import UnsafeMongoCommand
from app.adapters.types import QueryResult


@pytest.fixture
def mongo_target() -> Iterator[tuple[MongoDbAdapter, DbConnectionConfig, MongoClient[dict[str, object]]]]:
    host = os.environ.get("SQLCHAT_TEST_MONGO_HOST")
    port = os.environ.get("SQLCHAT_TEST_MONGO_PORT")
    if host is None or port is None:
        pytest.skip("real MongoDB target host/port are not configured")
    if host not in {"localhost", "127.0.0.1"} or int(port) != 17017:
        raise ValueError("MongoDB tests require the dedicated loopback target on port 17017")
    name = f"s12_mongo_{uuid4().hex}"
    username = os.environ.get("SQLCHAT_TEST_MONGO_USER", "")
    password = os.environ.get("SQLCHAT_TEST_MONGO_PASSWORD", "")
    config = DbConnectionConfig("mongodb", host, int(port), name, username, password)
    client = MongoDbAdapter()._client(config, 5)
    client.admin.command("ping")
    try:
        collection = client[name]["items"]
        collection.insert_many([
            {"_id": ObjectId(), "n": number, "tag": f"tag-{number % 5}", "active": number % 2 == 0,
             "amount": Decimal128("12.50"), "at": datetime(2026, 9, 1, tzinfo=UTC),
             "nullable": None, "large": 2**40, "stored_long": Int64(7), "binary": Binary(b"sample", 0),
             "nested": {"label": "中文"}, "list": [1, "two"],
             **({"late_only": "outside sample"} if number == 50 else {})}
            for number in range(125)
        ])
        collection.create_index([("tag", 1), ("n", -1)], name="tag_n_idx")
        yield MongoDbAdapter(), config, client
    finally:
        # Drop only the random database created by this fixture; no instance/volume removal.
        client.drop_database(name)
        assert name not in client.list_database_names()
        client.close()


def _command(operation: str, **arguments: object) -> str:
    return json.dumps({"collection": "items", "operation": operation, **arguments})


def documents(result: QueryResult) -> list[dict[str, object]]:
    payload = result["result"]
    assert isinstance(payload, list)
    return payload


def test_real_find_count_distinct_aggregate_and_row_bounds(
    mongo_target: tuple[MongoDbAdapter, DbConnectionConfig, MongoClient[dict[str, object]]],
) -> None:
    adapter, config, _client = mongo_target
    assert adapter.test_connection(config) is True
    found = adapter.execute(config, _command("find", filter={"n": {"$gte": 0}}, limit=300))
    assert found["rowCount"] == 100 and found["truncated"] is True
    assert [row["n"] for row in documents(found)] == list(range(100))
    bounded = adapter.execute(config, _command("find", limit=30), max_rows=3, trial_mode=True)
    assert [row["n"] for row in documents(bounded)] == [0, 1, 2]
    assert bounded["truncated"] is True
    assert adapter.execute(config, _command("count", filter={"active": True}))["result"] == 63
    distinct = adapter.execute(config, _command("distinct", field="tag"))
    assert distinct["result"] == {"values": [f"tag-{number}" for number in range(5)]}
    assert distinct["truncated"] is False
    capped = adapter.execute(config, _command("distinct", field="n"), max_rows=3)
    assert capped["result"] == {"values": [0, 1, 2]} and capped["truncated"] is True
    pipeline = [{"$group": {"_id": "$tag", "total": {"$sum": "$n"}, "count": {"$sum": 1}}},
                {"$sort": {"_id": 1}}]
    aggregated = adapter.execute(config, _command("aggregate", pipeline=pipeline))
    assert aggregated["result"] == [
        {"_id": f"tag-{group}", "total": sum(range(group, 125, 5)), "count": 25}
        for group in range(5)
    ]
    bounded_aggregate = adapter.execute(config, _command("aggregate", pipeline=pipeline), max_rows=2)
    assert bounded_aggregate["rowCount"] == 2 and bounded_aggregate["truncated"] is True


def test_real_extended_json_preserves_bson_types_and_filters(
    mongo_target: tuple[MongoDbAdapter, DbConnectionConfig, MongoClient[dict[str, object]]],
) -> None:
    adapter, config, client = mongo_target
    original = client[config.db_name]["items"].find_one({"n": 0})
    assert original is not None
    result = adapter.execute(config, _command("find", filter={"_id": {"$oid": str(original["_id"])}}))
    assert result["rowCount"] == 1 and result["truncated"] is False
    row = documents(result)[0]
    assert row["_id"] == {"$oid": str(original["_id"])}
    assert row["amount"] == {"$numberDecimal": "12.50"}
    assert row["at"] == {"$date": "2026-09-01T00:00:00Z"}
    assert row["binary"] == {"$binary": {"base64": "c2FtcGxl", "subType": "00"}}
    assert row["large"] == 2**40 and row["nullable"] is None and row["active"] is True
    assert row["nested"] == {"label": "中文"} and row["list"] == [1, "two"]
    filters = {"n": 0, "at": {"$date": "2026-09-01T00:00:00Z"},
               "amount": {"$numberDecimal": "12.50"},
               "binary": {"$binary": {"base64": "c2FtcGxl", "subType": "00"}}}
    assert adapter.execute(config, _command("count", filter=filters))["result"] == 1
    assert json_util.loads(json.dumps(row))["amount"] == Decimal128("12.50")


def test_real_metadata_sampling_indexes_and_document(
    mongo_target: tuple[MongoDbAdapter, DbConnectionConfig, MongoClient[dict[str, object]]],
) -> None:
    adapter, config, _client = mongo_target
    metadata = adapter.extract_metadata(config)
    assert metadata["incomplete"] is False and metadata["errorMessage"] is None
    assert metadata["schemaInferred"] is True and metadata["sampleSize"] == 50
    assert metadata["dbType"] == "mongodb" and metadata["databaseName"] == config.db_name
    assert len(metadata["tables"]) == 1
    table = metadata["tables"][0]
    assert table["name"] == "items" and table["rowCount"] == 125
    columns = {column["name"]: column for column in table["columns"]}
    assert "late_only" not in columns
    expected = {"_id": "objectId", "n": "int", "tag": "string", "active": "bool",
                "amount": "decimal", "at": "date", "nullable": "null", "large": "long",
                "stored_long": "long", "binary": "binData", "nested": "object", "list": "array"}
    assert {name: column["type"] for name, column in columns.items()} == expected
    assert columns["_id"]["primaryKey"] is True
    assert {index["name"]: index["columns"] for index in table["indexes"]} == {
        "_id_": ["_id"], "tag_n_idx": ["tag", "n"],
    }
    document = adapter.generate_document(config)
    assert "## Table: items" in document and "tag_n_idx" in document
    assert "at most 50 sample documents per collection" in document
    assert "approximate row counts" in document


def test_real_malformed_read_returns_failure_then_changed_read_succeeds(
    mongo_target: tuple[MongoDbAdapter, DbConnectionConfig, MongoClient[dict[str, object]]],
) -> None:
    adapter, config, client = mongo_target
    failed = adapter.execute(config, _command("count", filter={"$notAnOperator": 1}))
    assert failed["success"] is False and failed["errorCode"] == 2
    assert isinstance(failed["error"], str) and "operator" in failed["error"].lower()
    assert "result" not in failed and "data" not in failed
    repaired = adapter.execute(config, _command("count", filter={"active": True}))
    assert repaired["success"] is True and repaired["result"] == 63
    assert client[config.db_name]["items"].count_documents({}) == 125


@pytest.mark.parametrize("operation,arguments", [
    ("insert", {}), ("update", {}), ("delete", {}), ("drop", {}), ("mapReduce", {}),
    ("aggregate", {"pipeline": [{"$out": "forbidden_output"}]}),
    ("aggregate", {"pipeline": [{"$merge": {"into": "forbidden_output"}}]}),
    ("aggregate", {"pipeline": [{"$facet": {"nested": [{"$out": "forbidden_output"}]}}]}),
    ("find", {"filter": {"$where": "return true"}}),
])
def test_real_rejected_commands_leave_database_unchanged(
    mongo_target: tuple[MongoDbAdapter, DbConnectionConfig, MongoClient[dict[str, object]]],
    operation: str, arguments: dict[str, object],
) -> None:
    adapter, config, client = mongo_target
    database = client[config.db_name]
    before = list(database["items"].find({}).sort("n", 1))
    collections = database.list_collection_names()
    with pytest.raises(UnsafeMongoCommand):
        adapter.execute(config, _command(operation, **arguments))
    assert list(database["items"].find({}).sort("n", 1)) == before
    assert database.list_collection_names() == collections


def test_real_precancel_does_not_claim_driver_cancel(
    mongo_target: tuple[MongoDbAdapter, DbConnectionConfig, MongoClient[dict[str, object]]],
) -> None:
    adapter, config, client = mongo_target
    signal = threading.Event()
    signal.set()
    with pytest.raises(DatabaseExecutionInterrupted) as raised:
        adapter.execute(config, _command("count"), cancel_event=signal)
    assert raised.value.reason == "cancelled"
    assert raised.value.cancel_request_sent is False
    assert raised.value.server_termination_confirmed is False
    assert raised.value.write_outcome_unknown is False
    assert client[config.db_name]["items"].count_documents({}) == 125
