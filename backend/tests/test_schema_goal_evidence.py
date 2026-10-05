"""Schema completeness is about target coverage and actual visible evidence."""

import json

import pytest
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from task_goal_fixtures import goal_value
from test_task_goal import schema

from app.agent.output_guard import OutputArtifacts, bound_json
from app.agent.prompts import summary_prompt_messages, system_prompt
from app.agent.schema_evidence import SchemaEvidence
from app.agent.task_goal import TaskGoal
from app.agent.types import ChatRequest
from app.core.config import Settings


def test_named_scope_and_known_null_are_distinct_from_omitted_attributes() -> None:
    ledger = SchemaEvidence()
    value = schema()
    ledger.register(12, value, json.dumps(value))
    goal = TaskGoal.model_validate(goal_value(mode="metadata_only", tables=["orders"]))
    status = ledger.status(goal)
    assert status["complete"] is True
    assert "orders.id.comment" in status["databases"][0]["knownNullAttributes"]
    assert "orders.id.defaultValue" in status["databases"][0]["omittedAttributes"]
    missing = ledger.status(TaskGoal.model_validate(goal_value(mode="metadata_only", tables=["missing"])))
    assert missing["complete"] is False
    assert missing["databases"][0]["missingTables"] == ["missing"]


def test_truncated_schema_requires_full_contiguous_delivery(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.agent import output_guard

    monkeypatch.setattr(output_guard, "get_settings", lambda: Settings(tool_output_max_characters=950))
    artifacts = OutputArtifacts(7, "goal-evidence")
    value = schema()
    value["notes"] = "A" * 3500
    output = bound_json(value, artifacts, tool_name="getDatabaseSchema")
    metadata = json.loads(output)
    ledger = SchemaEvidence()
    ledger.register(12, value, output)
    goal = TaskGoal.model_validate(goal_value(mode="metadata_only", tables=["orders"]))
    assert ledger.status(goal)["complete"] is False
    assert ledger.status(goal)["databases"][0]["observedTables"] == []
    offset = 0
    while True:
        page = json.loads(artifacts.read(metadata["artifactId"], user_id=7, task_id="goal-evidence",
                                         offset=offset, length=400))
        ledger.observe_page(metadata["artifactId"], page)
        offset = page["nextOffset"]
        if not page["hasMore"]:
            break
        assert ledger.status(goal)["complete"] is False
    assert ledger.status(goal)["complete"] is True
    artifacts.clear()


def test_all_goal_databases_must_have_complete_evidence() -> None:
    ledger = SchemaEvidence()
    value = schema()
    ledger.register(12, value, json.dumps(value))
    goal = TaskGoal.model_validate(goal_value([12, 13], mode="metadata_only"))
    assert ledger.status(goal)["complete"] is False
    ledger.register(13, value, json.dumps(value))
    assert ledger.status(goal)["complete"] is True


@pytest.mark.parametrize("locale,marker", [("en", "concise Markdown summarizer"),
                                            ("zh-CN", "Markdown 总结助手")])
def test_summary_restores_source_role_history_request_and_schema(locale: str, marker: str) -> None:
    request = ChatRequest(message="Describe orders", dbConfigIds=[12])
    agent = system_prompt("sql_query", request, locale)
    history = [SystemMessage(content=agent),
               SystemMessage(content="Database 12 schema: orders.id INTEGER"),
               HumanMessage(content="Describe orders"),
               ToolMessage(content='{"success":true}', tool_call_id="query")]
    result = summary_prompt_messages(history, request, locale, "sql_query")
    assert marker in result[0].content
    assert all(message.content != agent for message in result)
    assert result[1:] == [*history[1:], result[-1]]
    assert "orders.id INTEGER" in result[1].content and "Describe orders" in result[-1].content
