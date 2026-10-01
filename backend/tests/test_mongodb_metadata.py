"""Corrupt or partly unavailable Mongo metadata cannot appear complete."""

from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from bson import ObjectId
from pymongo.errors import OperationFailure
from test_mongodb_adapter import config, fake_client

from app.adapters.document import render_document
from app.adapters.mongodb import MongoDbAdapter
from app.adapters.types import SchemaMetadata, TableMetadata


def target(monkeypatch: pytest.MonkeyPatch) -> tuple[MongoDbAdapter, MagicMock]:
    adapter = MongoDbAdapter()
    client = fake_client(monkeypatch, adapter)
    database = client["sample"]
    database.list_collection_names.return_value = ["items"]
    collection = database["items"]
    collection.find.return_value.limit.return_value.max_time_ms.return_value.__iter__.return_value = iter(
        [{"_id": ObjectId(), "label": "synthetic"}],
    )
    collection.list_indexes.return_value = [{"name": "_id_", "key": {"_id": 1}}]
    collection.estimated_document_count.return_value = 125
    return adapter, collection


def result(adapter: MongoDbAdapter) -> tuple[SchemaMetadata, TableMetadata]:
    metadata = adapter.extract_metadata(config())
    assert len(metadata["tables"]) == 1
    return metadata, metadata["tables"][0]


@pytest.mark.parametrize("bad, diagnostic", [
    ({}, "index name"), ({"name": None, "key": {}}, "index name"),
    ({"name": "", "key": {}}, "index name"), ({"name": "  ", "key": {}}, "index name"),
    ({"name": 7, "key": {"a": 1}}, "index name"), ({"name": "bad"}, "key"),
    ({"name": "bad", "key": None}, "key"), ({"name": "bad", "key": {}}, "key"),
    ({"name": "bad", "key": []}, "key"), ({"name": "bad", "key": {"": 1}}, "column names"),
    ({"name": "bad", "key": {"  ": 1}}, "column names"),
    ({"name": "bad", "key": {None: 1}}, "column names"),
    (None, "must be an object"),
])
def test_invalid_index_is_partial_and_preserves_fields_count_and_reliable_indexes(
    monkeypatch: pytest.MonkeyPatch, bad: object, diagnostic: str,
) -> None:
    adapter, collection = target(monkeypatch)
    collection.list_indexes.return_value = [
        {"name": "_id_", "key": {"_id": 1}}, bad, {"name": "ix_label", "key": {"label": 1}},
    ]
    metadata, table = result(adapter)
    assert metadata["incomplete"] is True
    assert isinstance(metadata["errorMessage"], str)
    assert "items indexes entry 2" in metadata["errorMessage"] and diagnostic in metadata["errorMessage"]
    assert table["indexes"] == [{"name": "_id_", "columns": ["_id"]},
                                {"name": "ix_label", "columns": ["label"]}]
    assert [column["name"] for column in table["columns"]] == ["_id", "label"]
    assert table["rowCount"] == 125
    assert "Error reading metadata" in render_document(metadata)


@pytest.mark.parametrize("component", ("fields", "indexes", "rowCount"))
def test_component_driver_failure_preserves_other_metadata(
    monkeypatch: pytest.MonkeyPatch, component: str,
) -> None:
    adapter, collection = target(monkeypatch)
    operation = {"fields": collection.find, "indexes": collection.list_indexes,
                 "rowCount": collection.estimated_document_count}[component]
    operation.side_effect = OperationFailure("synthetic component unavailable", code=13)
    metadata, table = result(adapter)
    assert metadata["incomplete"] is True and isinstance(metadata["errorMessage"], str)
    assert f"items {component}: OperationFailure" in metadata["errorMessage"]
    assert bool(table["columns"]) is (component != "fields")
    assert bool(table["indexes"]) is (component != "indexes")
    assert table["rowCount"] == (None if component == "rowCount" else 125)


@pytest.mark.parametrize("component", ("fields", "indexes"))
def test_partial_cursor_failure_keeps_preceding_observations(
    monkeypatch: pytest.MonkeyPatch, component: str,
) -> None:
    adapter, collection = target(monkeypatch)

    def interrupted() -> Iterator[dict[str, object]]:
        yield {"label": "observed"} if component == "fields" else {"name": "ix_label", "key": {"label": 1}}
        raise OperationFailure("cursor interrupted", code=13)

    if component == "fields":
        collection.find.return_value.limit.return_value.max_time_ms.return_value.__iter__.side_effect = interrupted
    else:
        collection.list_indexes.return_value = interrupted()
    metadata, table = result(adapter)
    assert metadata["incomplete"] is True and isinstance(metadata["errorMessage"], str)
    assert f"items {component}" in metadata["errorMessage"] and "cursor interrupted" in metadata["errorMessage"]
    if component == "fields":
        assert [column["name"] for column in table["columns"]] == ["label"]
    else:
        assert table["indexes"] == [{"name": "ix_label", "columns": ["label"]}]
    assert table["rowCount"] == 125


@pytest.mark.parametrize("count", (None, True, -1, "125", 1.5))
def test_unknown_or_invalid_count_is_none_with_warning(
    monkeypatch: pytest.MonkeyPatch, count: object,
) -> None:
    adapter, collection = target(monkeypatch)
    collection.estimated_document_count.return_value = count
    metadata, table = result(adapter)
    assert table["rowCount"] is None and table["columns"] and table["indexes"]
    assert metadata["incomplete"] is True and isinstance(metadata["errorMessage"], str)
    assert "rowCount" in metadata["errorMessage"] and "nonnegative integer" in metadata["errorMessage"]
    assert "Row count: ~unknown" in render_document(metadata)


def test_all_components_failing_keeps_known_collection_with_all_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, collection = target(monkeypatch)
    for operation in (collection.find, collection.list_indexes, collection.estimated_document_count):
        operation.side_effect = OperationFailure("unavailable", code=13)
    metadata, table = result(adapter)
    assert table["name"] == "items" and table["rowCount"] is None
    assert table["columns"] == [] and table["indexes"] == []
    assert metadata["incomplete"] is True and isinstance(metadata["errorMessage"], str)
    assert all(f"items {component}:" in metadata["errorMessage"] for component in ("fields", "indexes", "rowCount"))


def test_valid_metadata_stays_complete_and_zero_is_a_known_count(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter, collection = target(monkeypatch)
    collection.estimated_document_count.return_value = 0
    metadata, table = result(adapter)
    assert metadata["incomplete"] is False and metadata["errorMessage"] is None
    assert metadata["schemaInferred"] is True and metadata["sampleSize"] == 50
    assert table["rowCount"] == 0 and table["columns"] and table["indexes"]
