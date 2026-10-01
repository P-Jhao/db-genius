"""Ordinary workflows and known SQL failures retain the original execution scope."""

import sqlite3
from pathlib import Path

import pytest
from test_model_protocol import Provider
from test_workflow_graph import (
    answer,
    call,
    run,
    sqlite_target,
)
from test_workflow_graph import (
    provider as provider_fixture,
)

from app.agent.types import ChatRequest
from app.agent.workflow import WorkflowProgress

provider = provider_fixture


@pytest.mark.asyncio
@pytest.mark.parametrize("write,verify,expected", [
    ("UPDATE imports SET name='Eve' WHERE id=1", "SELECT id,name FROM imports", [(1, "Eve")]),
    ("DELETE FROM imports WHERE id=1", "SELECT COUNT(*) AS count FROM imports", []),
    ("CREATE TABLE new_imports (id INTEGER)", "SELECT id FROM new_imports", [(1, "Ada")]),
])
async def test_unattached_update_delete_create_are_verified(
    provider: Provider, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    write: str, verify: str, expected: list[tuple[int, str]],
) -> None:
    target = sqlite_target(monkeypatch, tmp_path)
    with sqlite3.connect(target) as connection:
        connection.execute("INSERT INTO imports VALUES (1,'Ada')")
    provider.replies = [call("executeSql", {"db_id": 12, "statement": write}, "write"),
                        call("executeSql", {"db_id": 12, "statement": verify}, "verify"),
                        call("doTerminate", {"reason": "verified"}, "done"),
                        answer("The workflow operation was executed and queried.")]
    request = ChatRequest.model_validate({"message": "Change the database", "dbConfigIds": [12],
                                          "confirmedIntent": "workflow"})
    result, _ = await run(provider, request)
    assert result == "The workflow operation was executed and queried."
    with sqlite3.connect(target) as connection:
        assert connection.execute("SELECT id,name FROM imports").fetchall() == expected
        if write.startswith("CREATE"):
            assert connection.execute("SELECT id FROM new_imports").fetchall() == []


def test_overlapping_queries_do_not_count_source_duplicates_twice() -> None:
    progress = WorkflowProgress({5})
    source = [{"label": "same"}, {"label": "same"}]
    progress.after_call("readFile", {"file_id": 5}, {"success": True, "totalRows": 2,
                        "headers": ["label"], "data": source, "truncated": False})
    progress.after_call("executeSql", {"db_id": 12,
                        "statement": "INSERT INTO imports(label) VALUES ('same'),('same')"},
                        {"success": True, "affectedRows": 2})
    for query in ["SELECT label FROM imports LIMIT 1", "SELECT label FROM imports WHERE label='same' LIMIT 1"]:
        progress.after_call("executeSql", {"db_id": 12, "statement": query},
                            {"success": True, "data": [{"label": "same"}], "truncated": False})
    assert "lack a successful subsequent SELECT" in str(progress.status())
    progress.after_call("executeSql", {"db_id": 12, "statement": "SELECT label FROM imports"},
                        {"success": True, "data": source, "truncated": False})
    assert progress.status() is None


def test_another_write_invalidates_previous_query_evidence() -> None:
    progress = WorkflowProgress(set())
    progress.after_call("executeSql", {"db_id": 12, "statement": "UPDATE imports SET name='Eve'"},
                        {"success": True, "affectedRows": 1})
    progress.after_call("executeSql", {"db_id": 12, "statement": "SELECT name FROM imports"},
                        {"success": True, "data": [{"name": "Eve"}], "truncated": False})
    assert progress.status() is None
    progress.after_call("executeSql", {"db_id": 12, "statement": "DELETE FROM imports"},
                        {"success": True, "affectedRows": 1})
    assert progress.status() is not None


def test_disjoint_ordered_pages_can_verify_duplicate_source_rows() -> None:
    progress = WorkflowProgress({5})
    source = [{"label": "same"}] * 200
    progress.after_call("readFile", {"file_id": 5}, {"success": True, "totalRows": 200,
                        "headers": ["label"], "data": source, "truncated": False})
    values = ",".join("('same')" for _ in source)
    progress.after_call("executeSql", {"db_id": 12, "statement": f"INSERT INTO imports(label) VALUES {values}"},
                        {"success": True, "affectedRows": 200})
    for offset in [0, 100]:
        progress.after_call("executeSql", {"db_id": 12,
                            "statement": f"SELECT label FROM imports ORDER BY label LIMIT 100 OFFSET {offset}"},
                            {"success": True, "data": source[:100], "truncated": False})
    assert progress.status() is None
