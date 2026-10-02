"""Metrics use full results and retain verification/status semantics."""

import json
from unittest.mock import Mock

import pytest
from sqlalchemy.orm import Session, sessionmaker
from test_db_config_partial import adapter_for

from app.agent.cancellation import RunAborted
from app.agent.tools import RunTools
from app.agent.types import ChatRequest
from app.core.config import get_settings
from app.core.observability_metrics import REGISTRY
from app.core.observability_runtime import observe_tool
from app.models import DbConfig
from app.services import db_config_worker

pytest_plugins = ["test_db_config_partial"]


def sample(name: str, labels: dict[str, str]) -> float:
    value = REGISTRY.get_sample_value(name, labels)
    return 0.0 if value is None else value


@pytest.mark.asyncio
async def test_failed_artifact_counts_as_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "tool_output_max_characters", 650)
    tools = RunTools(1, ChatRequest.model_validate({"message": "synthetic"}))
    failure = {"success": False, "error": "synthetic diagnostic " * 200}

    async def function(**_kwargs: object) -> str:
        return tools.bound(failure, "executeSql")

    before = sample("sqlchat_tool_calls_total", {"tool": "executeSql", "outcome": "error"})
    output = await observe_tool(tools.task_id, "executeSql", function, lambda: tools.last_result)()
    assert json.loads(output)["truncated"] is True
    assert "success" not in json.loads(output)  # success=False is inside preview/full artifact
    assert sample("sqlchat_tool_calls_total", {"tool": "executeSql", "outcome": "error"}) == before + 1
    tools.close()


@pytest.mark.parametrize("reason,outcome", [("cancelled", "cancelled"), ("timeout", "timeout"),
                                           ("write_outcome_unknown", "write_outcome_unknown")])
@pytest.mark.asyncio
async def test_interruption_rethrows_and_has_separate_label(reason: str, outcome: str) -> None:
    async def function(**_kwargs: object) -> str:
        raise RunAborted(reason)

    labels = {"tool": "executeSql", "outcome": outcome}
    before = sample("sqlchat_tool_calls_total", labels)
    with pytest.raises(RunAborted, match=reason):
        await observe_tool("synthetic-task", "executeSql", function, lambda: None)()
    assert sample("sqlchat_tool_calls_total", labels) == before + 1


@pytest.mark.parametrize("mode,outcome", [("full", "done"), ("partial", "partial"),
                                         ("failure", "error"), ("stale", "stale")])
def test_verification_status_and_single_metadata_call(
    store: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch, mode: str, outcome: str,
) -> None:
    adapter: Mock = adapter_for(monkeypatch, partial=mode == "partial")
    if mode == "failure":
        adapter.test_connection.side_effect = ConnectionError("synthetic-password")
    if mode == "stale":
        with store() as session:
            config = session.get(DbConfig, 12)
            assert config is not None
            config.verification_version = 2
            session.commit()
    before = sample("sqlchat_verifications_total", {"outcome": outcome})
    db_config_worker.verify_and_generate(12, 1)
    assert sample("sqlchat_verifications_total", {"outcome": outcome}) == before + 1
    with store() as session:
        config = session.get(DbConfig, 12)
        assert config is not None
        assert config.status == (0 if mode == "stale" else 2 if mode == "failure" else 1)
        if mode == "partial":
            assert config.doc_content is not None and "Error reading metadata" in config.doc_content
        if mode == "failure":
            assert config.verification_error is not None and "synthetic-password" not in config.verification_error
    assert adapter.test_connection.call_count == (0 if mode == "stale" else 1)
    assert adapter.extract_metadata.call_count == (1 if mode in {"full", "partial"} else 0)
