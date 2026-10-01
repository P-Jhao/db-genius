"""Actual PostgreSQL/MySQL diagnostics can be repaired without replaying a committed write."""

import json

import pytest
from sqlalchemy.orm import Session, sessionmaker
from test_model_protocol import Provider
from test_workflow_integration import (
    DB_ID,
    actual_rows,
    answer_reply,
    install_target,
    run,
    target_table,
    tool_reply,
    upload_csv,
)
from test_workflow_integration import (
    provider as provider_fixture,
)
from test_workflow_integration import (
    upload_store as upload_store_fixture,
)

provider = provider_fixture
upload_store = upload_store_fixture


@pytest.mark.asyncio
@pytest.mark.parametrize("db_type", ["postgresql", "mysql"])
@pytest.mark.parametrize("repair", [True, False])
async def test_known_failed_insert_can_be_corrected_but_not_reported_as_success(
    db_type: str, repair: bool, provider: Provider, upload_store: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with target_table(db_type) as (config, table):
        install_target(monkeypatch, config)
        uploaded = upload_csv(upload_store)
        provider.replies = [tool_reply("readFile", {"file_id": uploaded.id}, "source"),
                            tool_reply("executeSql", {"db_id": DB_ID, "statement":
                                f"INSERT INTO {table} (missing_column) VALUES (1)"}, "bad")]
        if repair:
            provider.replies.extend([
                tool_reply("executeSql", {"db_id": DB_ID, "statement":
                    f"INSERT INTO {table} (id,name,city) VALUES (1,'Ada','杭州'),(2,'Lin','深圳')"}, "fixed"),
                tool_reply("executeSql", {"db_id": DB_ID, "statement":
                    f"SELECT id,name,city FROM {table} ORDER BY id"}, "verify"),
            ])
        provider.replies.extend([tool_reply("doTerminate", {"reason": "done"}, "done"),
                                 answer_reply("The file was completely imported and verified.")])
        result, events = await run(provider, uploaded.id)
        errors = [json.loads(content.removeprefix("executeSql: ")) for kind, content in events
                  if kind == "step" and isinstance(content, str) and content.startswith("executeSql: ")]
        assert errors[0]["success"] is False and "missing_column" in errors[0]["error"]
        if repair:
            assert result == "The file was completely imported and verified."
            assert actual_rows(config, table) == [(1, "Ada", "杭州"), (2, "Lin", "深圳")]
        else:
            assert "executeSql did not succeed" in result
            assert "Workflow is incomplete" in result
            assert "completely imported" not in result
            assert actual_rows(config, table) == []
