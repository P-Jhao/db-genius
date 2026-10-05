"""S10 workflow execution against HTTP model replies and a real SQLite target."""

import json
import sqlite3
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from test_model_protocol import Provider, frame, model

from app.agent.cancellation import RunAborted
from app.agent.graph import RunContext, run_graph
from app.agent.streaming import ModelStream
from app.agent.tools import RunTools
from app.agent.types import ChatRequest, Usage
from app.core.errors import BusinessError


@pytest.fixture
def provider() -> Iterator[Provider]:
    service = Provider([])
    thread = threading.Thread(target=service.serve_forever, daemon=True)
    thread.start()
    yield service
    service.shutdown()
    service.server_close()
    thread.join(timeout=2)


def answer(content: str) -> list[bytes]:
    return [frame({"choices": [{"delta": {"content": content}}]}), frame("[DONE]")]


def call(name: str, arguments: dict[str, object], call_id: str) -> list[bytes]:
    return [frame({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": call_id,
             "function": {"name": name, "arguments": json.dumps(arguments)}}]}}]}), frame("[DONE]")]


def simultaneous_calls(first: tuple[str, dict[str, object]],
                       second: tuple[str, dict[str, object]]) -> list[bytes]:
    return [frame({"choices": [{"delta": {"tool_calls": [
        {"index": index, "id": f"call_{index}", "function": {
            "name": name, "arguments": json.dumps(arguments)}}
        for index, (name, arguments) in enumerate((first, second))]}}]}), frame("[DONE]")]


def workflow_request(*, classified: bool = False) -> ChatRequest:
    return ChatRequest.model_validate({"message": "Import", "dbConfigIds": [12],
                                       "fileIds": [5],
                                       "confirmedIntent": None if classified else "workflow"})


def sqlite_target(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    from app.services import database_tools

    target = tmp_path / "target.sqlite"
    with sqlite3.connect(target) as connection:
        connection.execute("CREATE TABLE imports (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
        connection.execute("CREATE TABLE unrelated (id INTEGER PRIMARY KEY)")
        connection.execute("INSERT INTO unrelated VALUES (99)")

    def schema(user_id: int, db_id: int) -> dict[str, object]:
        assert (user_id, db_id) == (7, 12)
        return {"dbType": "sqlite", "tables": [{"name": "imports", "columns": [
                    {"name": "id", "type": "INTEGER"}, {"name": "name", "type": "TEXT"}]}],
                "incomplete": False}

    def execute(user_id: int, db_id: int, statement: str) -> dict[str, object]:
        assert (user_id, db_id) == (7, 12)
        with sqlite3.connect(target) as connection:
            cursor = connection.execute(statement)
            if cursor.description:
                return {"success": True, "rowCount": len(rows := [dict(zip(
                    [column[0] for column in cursor.description], row, strict=True))
                    for row in cursor.fetchall()]), "data": rows, "truncated": False}
            return {"success": True, "affectedRows": cursor.rowcount}

    monkeypatch.setattr(database_tools, "get_schema", schema)
    monkeypatch.setattr(database_tools, "execute_statement", execute)
    return target


async def run(provider: Provider, request: ChatRequest,
              cancel_event: threading.Event | None = None) -> tuple[str, list[tuple[str, object]]]:
    events: list[tuple[str, object]] = []

    async def emit(kind: str, content: object, _step: int) -> None:
        events.append((kind, content))

    context = RunContext(request, [], "en", ModelStream(model(provider), emit, Usage(), cancel_event),
                         RunTools(7, request, cancel_event), emit, cancel_event)
    result = await run_graph(context)
    return result["answer"], events


@pytest.mark.asyncio
@pytest.mark.parametrize("classified", [False, True])
async def test_import_reads_writes_and_selects(provider: Provider, monkeypatch: pytest.MonkeyPatch,
                                                tmp_path: Path, classified: bool) -> None:
    from app.services import file_tools

    target = sqlite_target(monkeypatch, tmp_path)
    monkeypatch.setattr(file_tools, "read_file", lambda user_id, file_id: {
        "success": True, "fileName": "people.csv", "headers": ["id", "name"],
        "totalRows": 1, "data": [{"id": 1, "name": "Ada"}], "truncated": False,
    } if (user_id, file_id) == (7, 5) else None)
    provider.replies = [
        call("readFile", {"file_id": 5}, "file"),
        call("executeSql", {"db_id": 12, "statement": "INSERT INTO imports VALUES (1, 'Ada')"}, "write"),
        call("executeSql", {"db_id": 12, "statement": "SELECT id, name FROM imports"}, "verify"),
        call("doTerminate", {"reason": "verified"}, "done"),
        answer(json.dumps({"report": "Imported and verified Ada.", "complete": True})),
    ]
    if classified:
        provider.replies.insert(0, answer(json.dumps({"intent": "workflow", "confidence": 0.99,
                                                      "reasoning": "import", "needsClarification": False, "taskGoal": None})))
    request = workflow_request(classified=classified)
    result, events = await run(provider, request)
    assert result == "Imported and verified Ada."
    with sqlite3.connect(target) as connection:
        assert connection.execute("SELECT id, name FROM imports").fetchall() == [(1, "Ada")]
    assert [kind for kind, _ in events if kind == "step"] == ["step"] * 5
    assert "SELECT id, name FROM imports" in json.dumps(provider.requests[4 if classified else 3])


@pytest.mark.asyncio
@pytest.mark.parametrize("truncated,verify,expected", [
    (True, True, "partial import"), (False, False, "lack a successful subsequent SELECT"),
    (False, True, "Only 1 of 2000 source rows were inserted"),
])
async def test_import_status_is_bound_to_evidence(
    provider: Provider, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    truncated: bool, verify: bool, expected: str,
) -> None:
    from app.services import file_tools

    sqlite_target(monkeypatch, tmp_path)
    monkeypatch.setattr(file_tools, "read_file", lambda _user, _file: {
        "success": True, "totalRows": 2000, "data": [{"id": 1}], "truncated": truncated,
    })
    provider.replies = [call("readFile", {"file_id": 5}, "file"),
                        call("executeSql", {"db_id": 12,
                                            "statement": "INSERT INTO imports VALUES (1, 'Ada')"}, "write")]
    if verify:
        provider.replies.append(call("executeSql", {"db_id": 12,
                                                    "statement": "SELECT id FROM imports"}, "verify"))
    provider.replies.extend([call("doTerminate", {"reason": "done"}, "done"),
                             answer(json.dumps({"report": "Everything imported successfully.", "complete": True}))])
    result, events = await run(provider, workflow_request())
    assert expected in result
    summary = next(content for kind, content in events if kind == "summary")
    assert isinstance(summary, str) and expected in summary


@pytest.mark.asyncio
async def test_failed_read_stops_before_write(provider: Provider, monkeypatch: pytest.MonkeyPatch,
                                              tmp_path: Path) -> None:
    from app.services import file_tools

    target = sqlite_target(monkeypatch, tmp_path)
    monkeypatch.setattr(file_tools, "read_file", lambda _user, _file: {
        "success": False, "error": "Unsupported format"})
    provider.replies = [simultaneous_calls(
        ("readFile", {"file_id": 5}),
        ("executeSql", {"db_id": 12, "statement": "INSERT INTO imports VALUES (1, 'Ada')"})),
                        answer(json.dumps({"report": "I imported everything.", "complete": True}))]
    result, _ = await run(provider, workflow_request())
    assert "readFile did not succeed" in result
    with sqlite3.connect(target) as connection:
        assert connection.execute("SELECT COUNT(*) FROM imports").fetchone() == (0,)
    assert len(provider.requests) == 2


@pytest.mark.asyncio
async def test_image_ocr_truncation_is_reported(provider: Provider,
                                                monkeypatch: pytest.MonkeyPatch,
                                                tmp_path: Path) -> None:
    from app.services import file_tools

    sqlite_target(monkeypatch, tmp_path)
    monkeypatch.setattr(file_tools, "read_image", lambda user_id, file_id: {
        "success": True, "text": "Ada", "truncated": True,
    } if (user_id, file_id) == (7, 5) else None)
    provider.replies = [call("readImage", {"file_id": 5}, "image"),
                        answer("All image contents imported.")]
    result, _ = await run(provider, workflow_request())
    assert "partial import" in result
    assert "No database write was confirmed" in result


@pytest.mark.asyncio
async def test_unrelated_select_does_not_verify_import(
    provider: Provider, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from app.services import file_tools

    sqlite_target(monkeypatch, tmp_path)
    monkeypatch.setattr(file_tools, "read_file", lambda _user, _file: {
        "success": True, "data": [{"id": 1}], "truncated": False})
    provider.replies = [call("readFile", {"file_id": 5}, "file"),
                        call("executeSql", {"db_id": 12,
                                            "statement": "INSERT INTO imports VALUES (1, 'Ada')"}, "write"),
                        call("executeSql", {"db_id": 12,
                                            "statement": "SELECT id FROM unrelated"}, "wrong_verify"),
                        answer("Everything imported and verified.")]
    result, _ = await run(provider, workflow_request())
    assert "lack a successful subsequent SELECT" in result


@pytest.mark.asyncio
@pytest.mark.parametrize("verification", [
    "SELECT COUNT(*) AS count FROM imports",
    "SELECT id, name FROM imports WHERE id = 1",
])
async def test_preexisting_source_row_cannot_verify_wrong_insert(
    provider: Provider, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, verification: str,
) -> None:
    from app.services import file_tools

    target = sqlite_target(monkeypatch, tmp_path)
    with sqlite3.connect(target) as connection:
        connection.execute("INSERT INTO imports VALUES (1, 'Ada')")
    monkeypatch.setattr(file_tools, "read_file", lambda _user, _file: {
        "success": True, "headers": ["id", "name"], "totalRows": 1,
        "data": [{"id": 1, "name": "Ada"}], "truncated": False})
    provider.replies = [call("readFile", {"file_id": 5}, "file"),
                        call("executeSql", {"db_id": 12,
                                            "statement": "INSERT INTO imports VALUES (2, 'Eve')"}, "wrong_write"),
                        call("executeSql", {"db_id": 12, "statement": verification}, "verify"),
                        answer("The file was fully imported and verified.")]
    result, _ = await run(provider, workflow_request())
    assert "lack a successful subsequent SELECT matching source rows" in result
    with sqlite3.connect(target) as connection:
        assert connection.execute("SELECT id, name FROM imports ORDER BY id").fetchall() == [
            (1, "Ada"), (2, "Eve")]


@pytest.mark.asyncio
async def test_unattached_workflow_cannot_finish_without_tool_success(
    provider: Provider, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    sqlite_target(monkeypatch, tmp_path)
    provider.replies = [answer("Workflow completed successfully.")]
    request = ChatRequest.model_validate({"message": "Plan a workflow", "dbConfigIds": [12],
                                          "confirmedIntent": "workflow"})
    result, events = await run(provider, request)
    assert "No workflow tool succeeded" in result
    summary = next(content for kind, content in events if kind == "summary")
    assert isinstance(summary, str) and "No workflow tool succeeded" in summary


@pytest.mark.asyncio
async def test_unattached_workflow_can_verify_actual_write(
    provider: Provider, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    target = sqlite_target(monkeypatch, tmp_path)
    provider.replies = [call("executeSql", {"db_id": 12,
                                            "statement": "INSERT INTO imports (id, name) VALUES (1, 'Ada')"},
                             "write"),
                        call("executeSql", {"db_id": 12,
                                            "statement": "SELECT id, name FROM imports"}, "verify"),
                        answer("The row was inserted and verified.")]
    request = ChatRequest.model_validate({"message": "Insert a row", "dbConfigIds": [12],
                                          "confirmedIntent": "workflow"})
    result, _ = await run(provider, request)
    assert result == "The row was inserted and verified."
    with sqlite3.connect(target) as connection:
        assert connection.execute("SELECT id, name FROM imports").fetchall() == [(1, "Ada")]


@pytest.mark.asyncio
async def test_file_authorization_and_cancel_prevent_later_tools(
    provider: Provider, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from app.services import file_tools

    target = sqlite_target(monkeypatch, tmp_path)
    monkeypatch.setattr(file_tools, "read_file", lambda _user, _file: {
        "success": True, "data": [{"id": 1}], "truncated": False})
    provider.replies = [call("readFile", {"file_id": 99}, "other")]
    with pytest.raises(BusinessError, match="not attached"):
        await run(provider, workflow_request())
    cancel = threading.Event()
    provider.replies = [call("readFile", {"file_id": 5}, "file")]
    original = file_tools.read_file

    def read_then_cancel(user_id: int, file_id: int) -> dict[str, object]:
        result = original(user_id, file_id)
        cancel.set()
        return result

    monkeypatch.setattr(file_tools, "read_file", read_then_cancel)
    with pytest.raises(RunAborted):
        await run(provider, workflow_request(), cancel)
    with sqlite3.connect(target) as connection:
        assert connection.execute("SELECT COUNT(*) FROM imports").fetchone() == (0,)
