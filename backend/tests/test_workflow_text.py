"""Text attachments can guide verified operations without pretending to be table rows."""

import json
import sqlite3
from pathlib import Path

import pytest
from test_model_protocol import Provider
from test_workflow_graph import answer, call, run, sqlite_target, workflow_request
from test_workflow_graph import provider as provider_fixture

from app.services import file_tools

provider = provider_fixture


@pytest.mark.asyncio
@pytest.mark.parametrize("reader", ["readFile", "readImage"])
@pytest.mark.parametrize("truncated", [False, True])
async def test_document_and_ocr_instructions_can_update_and_verify(
    reader: str, truncated: bool, provider: Provider, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    target = sqlite_target(monkeypatch, tmp_path)
    with sqlite3.connect(target) as connection:
        connection.execute("INSERT INTO imports VALUES (1,'Ada')")
    result = {"success": True, "truncated": truncated,
              "content" if reader == "readFile" else "text": "Change id 1 name to Eve"}
    monkeypatch.setattr(file_tools, "read_file" if reader == "readFile" else "read_image",
                        lambda _user_id, _file_id: result)
    provider.replies = [call(reader, {"file_id": 5}, "source"),
                        call("executeSql", {"db_id": 12, "statement":
                             "UPDATE imports SET name='Eve' WHERE id=1"}, "write"),
                        call("executeSql", {"db_id": 12, "statement":
                             "SELECT id,name FROM imports WHERE id=1"}, "verify"),
                        call("doTerminate", {"reason": "verified"}, "done"),
                        answer(json.dumps({"report": "The attached instruction was applied; Eve was queried "
                                                     "from the database.", "complete": True}))]
    summary, _ = await run(provider, workflow_request())
    with sqlite3.connect(target) as connection:
        assert connection.execute("SELECT id,name FROM imports").fetchall() == [(1, "Eve")]
    if truncated:
        assert "truncated" in summary and "partial import" in summary
    else:
        assert summary == "The attached instruction was applied; Eve was queried from the database."
    prompt = provider.requests[0]["messages"]
    assert "does not prove a complete row import" in str(prompt)
