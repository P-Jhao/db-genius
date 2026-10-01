"""HTTP model simulation for the production Mongo workflow hooks."""

import json
import threading
from collections.abc import Iterator
from unittest.mock import Mock

import pytest
from test_model_protocol import Provider, frame, model

from app.adapters.mongodb_command import UnsafeMongoCommand, parse_command
from app.agent.graph import RunContext, run_graph
from app.agent.streaming import ModelStream
from app.agent.tools import RunTools
from app.agent.types import ChatRequest, Usage
from app.agent.workflow import WorkflowProgress
from app.services import database_tools, file_tools


@pytest.fixture
def provider() -> Iterator[Provider]:
    server = Provider([])
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    yield server
    server.shutdown()
    server.server_close()
    worker.join(timeout=2)


def command(operation: str, **arguments: object) -> str:
    return json.dumps({"collection": "items", "operation": operation, **arguments})


def call(name: str, args: dict[str, object], call_id: str) -> list[bytes]:
    return [frame({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": call_id,
             "function": {"name": name, "arguments": json.dumps(args)}}]}}]}), frame("[DONE]")]


def answer(content: str) -> list[bytes]:
    return [frame({"choices": [{"delta": {"content": content}}]}), frame("[DONE]")]


def prepare(monkeypatch: pytest.MonkeyPatch) -> Mock:
    monkeypatch.setattr(database_tools, "get_schema", lambda user, db: {
        "dbType": "mongodb", "databaseName": "synthetic", "tables": [],
        "schemaInferred": True, "sampleSize": 50,
    } if (user, db) == (7, 12) else None)
    def read(_user: int, _database: int, statement: str) -> dict[str, object]:
        operation = parse_command(statement).operation
        payload: object = 1 if operation == "count" else {"values": ["x"]} if operation == "distinct" else [{"value": 1}]
        return {"success": True, "rowCount": 1, "result": payload, "truncated": False}

    execute = Mock(side_effect=read)
    monkeypatch.setattr(database_tools, "execute_statement", execute)
    return execute


async def run(provider: Provider, *, attached: bool = False) -> str:
    async def emit(_kind: str, _content: object, _step: int) -> None:
        return None

    request = ChatRequest.model_validate({"message": "Run a read-only Mongo workflow",
                                         "dbConfigIds": [12], "fileIds": [5] if attached else [],
                                         "confirmedIntent": "workflow"})
    context = RunContext(request, [], "en", ModelStream(model(provider), emit, Usage()),
                         RunTools(7, request), emit)
    return (await run_graph(context))["answer"]


@pytest.mark.asyncio
async def test_ordinary_read_workflow_runs_all_four_json_operations(
    provider: Provider, monkeypatch: pytest.MonkeyPatch,
) -> None:
    execute = prepare(monkeypatch)
    commands = [command("find"), command("count"), command("distinct", field="tag"),
                command("aggregate", pipeline=[{"$match": {"active": True}}])]
    for index, statement in enumerate(commands):
        provider.replies.append(call("executeSql", {"db_id": 12, "statement": statement}, f"read{index}"))
    provider.replies.append(answer("Four reads completed."))
    assert await run(provider) == "Four reads completed."
    assert execute.call_count == 4 and len(provider.requests) == 5
    assert [called.args[2] for called in execute.call_args_list] == commands


@pytest.mark.asyncio
async def test_schema_only_cannot_claim_a_mongo_read_succeeded(
    provider: Provider, monkeypatch: pytest.MonkeyPatch,
) -> None:
    execute = prepare(monkeypatch)
    provider.replies = [answer("Mongo query completed.")]
    assert "No MongoDB read command succeeded" in await run(provider)
    execute.assert_not_called()


@pytest.mark.asyncio
async def test_mongo_reads_with_attachment_cannot_claim_import(
    provider: Provider, monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare(monkeypatch)
    monkeypatch.setattr(file_tools, "read_file", lambda _user, _file: {
        "success": True, "headers": ["value"], "data": [{"value": 1}], "totalRows": 1,
        "truncated": False,
    })
    provider.replies = [call("readFile", {"file_id": 5}, "file"),
                        call("executeSql", {"db_id": 12, "statement": command("find")}, "read"),
                        answer("The attached rows were imported.")]
    result = await run(provider, attached=True)
    assert "No database write was confirmed" in result and "imported" not in result


@pytest.mark.asyncio
async def test_mongo_write_is_rejected_before_service_dispatch(
    provider: Provider, monkeypatch: pytest.MonkeyPatch,
) -> None:
    execute = prepare(monkeypatch)
    provider.replies = [call("executeSql", {"db_id": 12, "statement": command("insert")}, "write")]
    with pytest.raises(UnsafeMongoCommand):
        await run(provider)
    execute.assert_not_called()


@pytest.mark.asyncio
async def test_read_error_changed_read_and_grounded_summary(
    provider: Provider, monkeypatch: pytest.MonkeyPatch,
) -> None:
    execute = prepare(monkeypatch)
    execute.side_effect = [
        {"success": False, "error": "unknown top level operator", "errorCode": 2},
        {"success": True, "rowCount": 1, "result": 63, "truncated": False},
    ]
    bad = command("count", filter={"$notAnOperator": 1})
    changed = command("count", filter={"active": True})
    provider.replies = [call("executeSql", {"db_id": 12, "statement": bad}, "bad"),
                        call("executeSql", {"db_id": 12, "statement": changed}, "fixed"),
                        answer("There are 63 active documents.")]
    assert await run(provider) == "There are 63 active documents."
    assert execute.call_count == 2 and len(provider.requests) == 3
    assert [called.args[2] for called in execute.call_args_list] == [bad, changed]


@pytest.mark.parametrize("payload", (True, "63", [{"count": 63}], {"values": "bad"}))
def test_mongo_evidence_never_fabricates_valid_count_from_data(payload: object) -> None:
    progress = WorkflowProgress(set())
    progress.schema.register(12, {"dbType": "mongodb", "tables": []})
    with pytest.raises(TypeError):
        progress.after_call("executeSql", {"db_id": 12, "statement": command("count")},
                            {"success": True, "rowCount": 1, "result": payload, "truncated": False})
    assert "No MongoDB read command succeeded" in str(progress.status())


def test_full_result_failure_is_reported_and_json_is_not_a_sql_dialect() -> None:
    progress = WorkflowProgress(set())
    progress.schema.register(12, {"dbType": "mongodb", "tables": []})
    progress.after_call("executeSql", {"db_id": 12, "statement": command("count")},
                        {"success": False, "error": "read unavailable"})
    assert "read unavailable" in str(progress.status())
    assert progress.schema.dialects[12] == "mongodb"
    with pytest.raises(TypeError, match="full service result"):
        progress.after_call("executeSql", {"db_id": 12, "statement": command("find")},
                            {"marker": "artifact"})
