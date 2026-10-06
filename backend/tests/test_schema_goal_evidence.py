"""Schema completeness is about target coverage and actual visible evidence."""

import json
import logging

import pytest
from chat_terminal_fixtures import schema as ten_table_schema
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from task_goal_fixtures import goal_value
from test_task_goal import schema

from app.agent.output_guard import OutputArtifacts, bound_json
from app.agent.prompts import summary_prompt_messages, system_prompt
from app.agent.schema_evidence import SchemaEvidence
from app.agent.sql_terminal_diagnostics import logger as terminal_logger
from app.agent.sql_terminal_diagnostics import observe_completion
from app.agent.task_goal import TaskGoal
from app.agent.tools import RunTools
from app.agent.types import ChatRequest
from app.core.config import Settings
from app.core.observability_logging import SafeLogFilter


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


def paged_ledger() -> tuple[SchemaEvidence, TaskGoal, str]:
    value = ten_table_schema()
    text = json.dumps(value, ensure_ascii=False)
    assert len(text) == 11889
    ledger = SchemaEvidence()
    ledger.register(12, value, json.dumps({"artifactId": "overlap"}))
    goal = TaskGoal.model_validate(goal_value(mode="metadata_only"))
    return ledger, goal, text


def page(text: str, start: int, end: int) -> dict[str, object]:
    return {"content": text[start:end], "offset": start, "nextOffset": end,
            "totalCharacters": len(text), "hasMore": end < len(text)}


@pytest.mark.parametrize("reverse", [False, True])
def test_actual_mysql_five_pages_merge_overlapping_out_of_order_union(reverse: bool) -> None:
    ledger, goal, text = paged_ledger()
    intervals = [(0, 3407), (8000, 11419), (3407, 6803), (11419, 11889), (6803, 8003)]
    if reverse:
        intervals.reverse()
    for index, (start, end) in enumerate(intervals):
        ledger.observe_page("overlap", page(text, start, end))
        assert ledger.status(goal)["complete"] is (index == 4)
    assert len(ledger.status(goal)["databases"][0]["observedTables"]) == 10


@pytest.mark.parametrize("intervals", [
    [(0, 3407), (3407, 6803), (8000, 11419), (11419, 11889)],
    [(0, 3407), (4000, 7402), (8000, 11419), (11419, 11889), (7402, 8102)],
])
def test_overlap_union_with_gap_cannot_complete_even_when_has_more_false(
    intervals: list[tuple[int, int]],
) -> None:
    ledger, goal, text = paged_ledger()
    for start, end in intervals:
        value = page(text, start, end)
        value["hasMore"] = False
        ledger.observe_page("overlap", value)
    assert ledger.status(goal)["complete"] is False
    assert ledger.status(goal)["databases"][0]["limitation"] == "schema_output_truncated"


@pytest.mark.parametrize("start", [0, 3400])
def test_conflicting_overlap_raises_without_corrupting_evidence(start: int) -> None:
    ledger, goal, text = paged_ledger()
    ledger.observe_page("overlap", page(text, 0, 3407))
    conflicting = page(text, start, 3500)
    content = conflicting["content"]
    assert isinstance(content, str)
    conflicting["content"] = "!" + content[1:]
    with pytest.raises(ValueError, match="conflicting overlap"):
        ledger.observe_page("overlap", conflicting)
    assert ledger.observations[12].pages == {0: text[:3407]}
    assert ledger.status(goal)["complete"] is False


def test_same_offset_shorter_reread_preserves_longer_verified_evidence() -> None:
    ledger, goal, text = paged_ledger()
    ledger.observe_page("overlap", page(text, 0, 3407))
    ledger.observe_page("overlap", page(text, 0, 20))
    assert ledger.observations[12].pages[0] == text[:3407]
    ledger.observe_page("overlap", page(text, 3407, len(text)))
    assert ledger.status(goal)["complete"] is True
    ledger.observe_page("overlap", page(text, 3407, 3450))
    assert ledger.status(goal)["complete"] is True
    assert ledger.observations[12].pages[3407] == text[3407:]


@pytest.mark.parametrize("changed", [{"offset": -1, "nextOffset": 9},
                                     {"totalCharacters": 5}, {"totalCharacters": -1}])
def test_paging_bounds_are_explicit_errors(changed: dict[str, object]) -> None:
    ledger, goal, text = paged_ledger()
    invalid = {**page(text, 0, 10), **changed}
    with pytest.raises(ValueError, match="out of bounds"):
        ledger.observe_page("overlap", invalid)
    assert ledger.status(goal)["complete"] is False
    assert ledger.observations[12].pages == {}


def test_total_change_and_complete_source_mismatch_are_rejected() -> None:
    ledger, goal, text = paged_ledger()
    ledger.observe_page("overlap", page(text, 0, 100))
    changed = {**page(text, 100, 200), "totalCharacters": len(text) + 1}
    with pytest.raises(ValueError, match="total changed"):
        ledger.observe_page("overlap", changed)
    assert ledger.observations[12].pages == {0: text[:100]}
    assert ledger.status(goal)["complete"] is False
    different = text.replace("AI聊天消息", "AI聊天记录")
    fresh, _, _ = paged_ledger()
    with pytest.raises(ValueError, match="differs from its registered schema"):
        fresh.observe_page("overlap", page(different, 0, len(different)))
    assert fresh.observations[12].delivered is False
    assert fresh.observations[12].pages == {}


@pytest.mark.parametrize("read_before_refresh", ["none", "partial", "complete"])
def test_same_source_refresh_preserves_original_artifact_delivery(read_before_refresh: str) -> None:
    ledger, goal, text = paged_ledger()
    if read_before_refresh == "partial":
        ledger.observe_page("overlap", page(text, 0, 3407))
    elif read_before_refresh == "complete":
        ledger.observe_page("overlap", page(text, 0, len(text)))
    ledger.register(12, ten_table_schema(), json.dumps({"artifactId": "refreshed"}))
    assert ledger.status(goal)["complete"] is (read_before_refresh == "complete")
    for start, end in ((0, 3407), (3407, 6803), (6803, 10204), (10204, 11889)):
        ledger.observe_page("overlap", page(text, start, end))
    assert ledger.status(goal)["complete"] is True
    assert ledger.artifacts["refreshed"][1].pages == {}
    assert len(ledger.artifacts["overlap"][1].pages) >= 4


def test_inline_same_source_delivery_survives_later_truncated_registration() -> None:
    ledger, goal, _ = paged_ledger()
    value = ten_table_schema()
    ledger.register(12, value, json.dumps(value, ensure_ascii=False))
    ledger.register(12, value, json.dumps({"artifactId": "later-truncated"}))
    assert ledger.status(goal)["complete"] is True
    assert ledger.artifacts["later-truncated"][1].pages == {}


@pytest.mark.parametrize("complete_old_first", [False, True])
def test_changed_source_invalidates_old_evidence(complete_old_first: bool) -> None:
    ledger, goal, text = paged_ledger()
    if complete_old_first:
        ledger.observe_page("overlap", page(text, 0, len(text)))
    changed = ten_table_schema()
    changed["observedVersion"] = 2
    new_text = json.dumps(changed, ensure_ascii=False)
    ledger.register(12, changed, json.dumps({"artifactId": "changed"}))
    ledger.observe_page("overlap", page(text, 0, len(text)))
    assert ledger.status(goal)["complete"] is False
    assert ledger.observations[12].pages == {}
    ledger.observe_page("changed", page(new_text, 0, len(new_text)))
    assert ledger.status(goal)["complete"] is True


def test_separate_artifacts_and_databases_cannot_combine_partial_evidence() -> None:
    ledger, _, text = paged_ledger()
    ledger.register(12, ten_table_schema(), json.dumps({"artifactId": "second"}))
    ledger.register(13, ten_table_schema(), json.dumps({"artifactId": "other-db"}))
    goal = TaskGoal.model_validate(goal_value([12, 13], mode="metadata_only"))
    ledger.observe_page("overlap", page(text, 0, 3407))
    ledger.observe_page("second", page(text, 3407, len(text)))
    ledger.observe_page("other-db", page(text, 3407, len(text)))
    assert ledger.status(goal)["complete"] is False
    assert all(db["complete"] is False for db in ledger.status(goal)["databases"])
    ledger.observe_page("overlap", page(text, 3407, len(text)))
    assert ledger.status(goal)["databases"][0]["complete"] is True
    assert ledger.status(goal)["databases"][1]["complete"] is False
    ledger.observe_page("other-db", page(text, 0, 3407))
    assert ledger.status(goal)["complete"] is True


def test_artifact_identity_cannot_be_registered_with_different_source_or_database() -> None:
    ledger, _, _ = paged_ledger()
    with pytest.raises(ValueError, match="different source"):
        ledger.register(13, ten_table_schema(), json.dumps({"artifactId": "overlap"}))
    with pytest.raises(ValueError, match="different source"):
        ledger.register(12, {"tables": []}, json.dumps({"artifactId": "overlap"}))


def test_sql_diagnostics_are_visible_with_warning_root_and_safe_log_filter(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(logging.getLogger(), "level", logging.WARNING)
    assert terminal_logger.getEffectiveLevel() == logging.INFO
    request = ChatRequest.model_validate({"message": "PRIVATE_REQUEST", "dbConfigIds": [12]})
    tools = RunTools(7, request, task_id="1" * 32)
    tools.task_goal = TaskGoal.model_validate(goal_value(mode="metadata_only"))
    tools.schema_evidence.register(12, schema(), json.dumps(schema()))
    observe_completion(tools, "direct", False)
    records = [record for record in caplog.records if record.name == terminal_logger.name]
    assert len(records) == 1
    assert SafeLogFilter(Settings()).filter(records[0]) is True
    payload = json.loads(records[0].getMessage().removeprefix("SQL completion "))
    assert payload == {"taskId": "1" * 32, "taskGoalMode": "metadata_only", "terminalPath": "direct",
                       "overrideApplied": False, "schemaEvidenceComplete": True,
                       "statementsAttempted": 0, "statementsExecuted": 0}
    assert "PRIVATE_REQUEST" not in records[0].getMessage() and "orders" not in records[0].getMessage()


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
