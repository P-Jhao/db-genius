"""Full comparison reports, inferred Mongo schemas and cancellation boundaries."""

import json
import threading
from typing import cast

import pytest
from test_compare_graph import call
from test_model_protocol import Provider, model
from test_schema_diff import _column, _schema, _table

from app.adapters.types import SchemaMetadata
from app.agent.cancellation import RunAborted
from app.agent.compare import CompareProgress
from app.agent.graph import RunContext, run_graph
from app.agent.streaming import ModelStream
from app.agent.tools import RunTools
from app.agent.types import ChatRequest, Usage
from app.services import database_tools, schema_diff

pytest_plugins = ["test_chat_api"]


def _report() -> dict[str, object]:
    return {"success": True, "complete": True, "preComplete": True, "testComplete": True,
            "preDatabase": "pre", "testDatabase": "test", "preDbType": "postgresql",
            "testDbType": "postgresql", "preSchemaInferred": False, "testSchemaInferred": False,
            "newTables": [{"table": f"new_table_{index}", "columnCount": 1} for index in range(200)],
            "droppedTables": [], "alteredTables": [],
            "preSchema": _schema("pre", "postgresql"),
            "testSchema": _schema("test", "postgresql", *[
                _table(f"new_table_{index}", {**_column("id", "INTEGER", False), "primaryKey": True},
                       _column("required_note", "VARCHAR(42)", False)) for index in range(200)])}


@pytest.mark.asyncio
async def test_truncated_report_requires_full_matching_pages_not_repeated_previews() -> None:
    tools = RunTools(7, ChatRequest(message="compare", preDbConfigId=12, testDbConfigId=13))
    progress = CompareProgress()
    report = _report()
    try:
        output = tools.bound(report, "compareDatabases")
        progress.observe(output, report)
        artifact_id = json.loads(output)["artifactId"]
        assert progress.output_truncated is True
        assert progress.must_stop is False  # Full authoritative report is pageable.
        first = json.loads(await tools.read_output(artifact_id, 0, 16000))
        progress.observe_page({"artifact_id": "different-task-artifact"}, first)
        assert progress.read_ranges == []
        progress.observe_page({"artifact_id": artifact_id}, first)
        progress.observe_page({"artifact_id": artifact_id}, first)
        assert "truncated" in progress.status()
        assert progress.safe_report() is not None  # A preview cannot authorize a complete migration summary.
        offset = first["nextOffset"]
        while offset < len(progress.full_text):
            page = json.loads(await tools.read_output(artifact_id, offset, 16000))
            progress.observe_page({"artifact_id": artifact_id}, page)
            offset = page["nextOffset"]
        assert progress.status() is None
        assert progress.safe_report() is None
        assert '"preSchema"' in progress.full_text and '"testSchema"' in progress.full_text
        assert '"required_note"' in progress.full_text and '"nullable": false' in progress.full_text
        assert '"primaryKey": true' in progress.full_text
    finally:
        tools.close()


def test_mismatched_report_page_cannot_clear_truncation() -> None:
    progress = CompareProgress()
    progress.observe('{"marker":"[TRUNCATED:TOOL_OUTPUT_TOO_LONG]","artifactId":"known"}', _report())
    with pytest.raises(ValueError, match="authoritative result"):
        progress.observe_page({"artifact_id": "known"}, {"offset": 0, "nextOffset": 4,
            "content": "fake", "totalCharacters": len(progress.full_text)})
    assert progress.output_truncated is True


@pytest.mark.parametrize("field,value", [("schemaInferred", 1), ("schemaInferred", "false"),
    ("schemaInferred", None), ("sampleSize", True), ("sampleSize", -1),
    ("sampleSize", "50"), ("sampleSize", None)])
def test_inferred_metadata_fields_are_strictly_validated(
    monkeypatch: pytest.MonkeyPatch, field: str, value: object,
) -> None:
    pre = cast(SchemaMetadata, {**_schema("pre", "mongodb"), field: value})
    test = _schema("test", "mongodb")
    monkeypatch.setattr(database_tools, "get_schema", lambda _user, db_id: pre if db_id == 12 else test)
    with pytest.raises(TypeError, match=field):
        schema_diff.compare_databases(7, 12, 13)


@pytest.mark.parametrize("partial,cross_engine", [(False, False), (True, False), (False, True)])
def test_inferred_samples_do_not_imply_exact_equality_or_reliable_migrations(
    monkeypatch: pytest.MonkeyPatch, partial: bool, cross_engine: bool,
) -> None:
    pre = cast(SchemaMetadata, {**_schema("pre", "mongodb", incomplete=partial),
                               "schemaInferred": True, "sampleSize": 50})
    test = (_schema("test", "postgresql") if cross_engine else
            cast(SchemaMetadata, {**_schema("test", "mongodb"), "schemaInferred": True, "sampleSize": 3}))
    monkeypatch.setattr(database_tools, "get_schema", lambda _user, db_id: pre if db_id == 12 else test)
    report = schema_diff.compare_databases(7, 12, 13)
    assert report["complete"] is (not partial)
    assert report["preSchemaInferred"] is True and report["preSampleSize"] == 50
    assert report["testSchemaInferred"] is (not cross_engine)
    if not cross_engine:
        assert report["testSampleSize"] == 3
    progress = CompareProgress()
    progress.observe(json.dumps(report), report)
    assert progress.must_stop is True
    safe = progress.safe_report()
    assert "up to 50 sample documents per collection" in safe
    assert "unobserved fields may still exist" in safe
    assert "No directly executable migration SQL" in safe
    assert "absence of a listed change does not prove" in safe


@pytest.mark.asyncio
async def test_cancel_after_pre_metadata_prevents_test_read_and_final_model(
    monkeypatch: pytest.MonkeyPatch, provider: Provider,
) -> None:
    signal = threading.Event()
    calls: list[int] = []

    def schema(_user_id: int, db_id: int) -> SchemaMetadata:
        calls.append(db_id)
        signal.set()
        return _schema("pre", "postgresql")

    monkeypatch.setattr(database_tools, "get_schema", schema)
    provider.replies = [call("compareDatabases", {"pre_id": 12, "test_id": 13}, "compare")]
    request = ChatRequest(message="compare", preDbConfigId=12, testDbConfigId=13, confirmedIntent="db_compare")
    usage = Usage()

    async def emit(_kind: str, _content: object, _step: int) -> None:
        pass

    context = RunContext(request, [], "en", ModelStream(model(provider), emit, usage, signal),
                         RunTools(7, request, signal), emit, signal)
    with pytest.raises(RunAborted):
        await run_graph(context)
    assert calls == [12]
    assert len(provider.requests) == 0
    assert (usage.callCount, usage.totalTokens) == (0, 0)
