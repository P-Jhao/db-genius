"""T-27/T-28: real bounds, ownership, context governance, and loop convergence."""

import json
from collections.abc import Sequence
from typing import cast

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from task_goal_fixtures import goal_value

from app.agent import context_runtime, output_guard
from app.agent.context_runtime import RepeatedCalls, govern_messages, summary_request
from app.agent.graph import RunContext, run_graph
from app.agent.output_guard import OutputArtifacts, bound_json
from app.agent.streaming import ModelStream
from app.agent.tools import RunTools
from app.agent.types import ChatRequest, Usage
from app.core.config import Settings
from app.core.errors import BusinessError


def test_default_runtime_controls() -> None:
    settings = Settings()
    assert (settings.observation_elision_enabled, settings.observation_elision_threshold,
            settings.observation_elision_keep_last_steps) == (True, 0.6, 3)
    assert (settings.step_summary_enabled, settings.step_summary_threshold,
            settings.step_summary_keep_last_steps) == (True, 0.8, 4)
    assert not settings.stale_reasoning_discard_enabled
    assert (settings.repeated_tool_call_warning_count, settings.repeated_tool_call_stop_count) == (3, 5)
    assert (settings.tool_output_max_characters, settings.tool_output_max_rows,
            settings.tool_artifact_ttl_seconds, settings.tool_artifact_max_per_task) == (4000, 50, 1800, 20)


def test_repetition_normalizes_argument_order() -> None:
    calls = RepeatedCalls()
    assert calls.record("executeSql", {"db_id": 1, "statement": "SELECT 1"}) == (False, False)
    assert calls.record("executeSql", {"statement": "SELECT 1", "db_id": 1}) == (False, False)
    assert calls.record("executeSql", {"db_id": 1, "statement": "SELECT 1"}) == (True, False)
    assert calls.record("executeSql", {"db_id": 1, "statement": "SELECT 1"}) == (False, False)
    assert calls.record("executeSql", {"db_id": 1, "statement": "SELECT 1"}) == (False, True)


@pytest.mark.asyncio
async def test_structured_bound_and_scoped_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(tool_output_max_characters=450, tool_output_max_rows=2)
    monkeypatch.setattr(output_guard, "get_settings", lambda: settings)
    tools = RunTools(7, ChatRequest.model_validate({"message": "query"}), task_id="task-a")
    result = {"success": True, "rowCount": 100, "truncated": True, "totalRows": 500,
              "incomplete": True, "data": [
        {"name": f"row {index}", "text": "长文本\n" * 30} for index in range(100)
    ]}
    bounded = tools.bound(result)
    parsed = json.loads(bounded)
    assert len(bounded) <= 450
    assert parsed["truncated"] is True
    assert parsed["marker"] == "[TRUNCATED:TOOL_OUTPUT_TOO_LONG]"
    assert parsed["sourceTruncated"] is True
    assert parsed["sourceTotalRows"] == 500
    assert parsed["sourceIncomplete"] is True
    assert parsed["success"] is True
    assert len(parsed["data"]) <= 2
    artifact_id = parsed["artifactId"]
    page = json.loads(await tools.read_output(artifact_id, 0, 20))
    assert page["content"] == json.dumps(result, ensure_ascii=False)[:20]
    assert page["hasMore"] is True
    large_page_text = await tools.read_output(artifact_id, 0, 16000)
    large_page = json.loads(large_page_text)
    assert len(large_page_text) <= 450
    assert large_page["nextOffset"] > 0
    assert large_page["hasMore"] is True
    with pytest.raises(BusinessError):
        tools.artifacts.read(artifact_id, user_id=8, task_id="task-a", offset=0, length=20)
    with pytest.raises(BusinessError):
        tools.artifacts.read(artifact_id, user_id=7, task_id="task-b", offset=0, length=20)
    other = RunTools(7, ChatRequest.model_validate({"message": "query"}), task_id="task-b")
    with pytest.raises(BusinessError):
        await other.read_output(artifact_id)
    tools.close()
    with pytest.raises(BusinessError):
        await tools.read_output(artifact_id)


def test_capacity_ttl_and_impossible_limit_fail_explicitly(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [100.0]
    monkeypatch.setattr(output_guard, "monotonic", lambda: clock[0])
    settings = Settings(tool_artifact_max_per_task=1, tool_artifact_ttl_seconds=2)
    monkeypatch.setattr(output_guard, "get_settings", lambda: settings)
    artifacts = OutputArtifacts(1, "one")
    first = artifacts.add("first")
    with pytest.raises(BusinessError, match="capacity"):
        artifacts.add("second")
    clock[0] = 103.0
    with pytest.raises(BusinessError):
        artifacts.read(first, user_id=1, task_id="one", offset=0, length=1)
    artifacts.add("second")
    tiny = Settings(tool_output_max_characters=10)
    monkeypatch.setattr(output_guard, "get_settings", lambda: tiny)
    with pytest.raises(ValueError, match="cannot fit"):
        bound_json({"data": ["x" * 100]}, OutputArtifacts(1, "tiny"))


def test_short_rows_and_multiline_text_are_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(tool_output_max_characters=4000, tool_output_max_rows=3)
    monkeypatch.setattr(output_guard, "get_settings", lambda: settings)
    artifacts = OutputArtifacts(1, "task")
    value = {"data": list(range(100)), "text": "a\n" * 20, "success": True}
    assert json.loads(bound_json(value, artifacts)) == value


def test_non_finite_json_is_rejected() -> None:
    with pytest.raises(ValueError, match="Out of range float"):
        bound_json({"value": float("nan")}, OutputArtifacts(1, "task"))


@pytest.mark.asyncio
async def test_elision_then_real_summary_and_summary_failure() -> None:
    messages: list[BaseMessage] = [SystemMessage(content="rules"), HumanMessage(content="query")]
    for index in range(6):
        messages.extend([
            AIMessage(content="", tool_calls=[{"name": "executeSql", "args": {"db_id": 1},
                                               "id": f"call-{index}"}]),
            ToolMessage(content=json.dumps({"success": True, "rowCount": index,
                                            "data": ["x" * 1000]}), tool_call_id=f"call-{index}"),
        ])
    calls: list[Sequence[BaseMessage]] = []
    async def summarize(old: list[BaseMessage]) -> str:
        calls.append(old)
        return "Six queries were attempted; earlier result counts are retained."
    result = await govern_messages(messages, context_window=200, summarize=summarize)
    assert calls
    assert any(isinstance(item, SystemMessage) and "Six queries" in str(item.content) for item in result)
    assert len([item for item in result if isinstance(item, ToolMessage)]) == 4
    assert messages[3].content != ""  # source history was not changed
    async def fail(_old: list[BaseMessage]) -> str:
        return ""
    with pytest.raises(ValueError, match="empty"):
        await govern_messages(messages, context_window=200, summarize=fail)


@pytest.mark.asyncio
async def test_elided_observation_marker_is_valid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(context_runtime, "get_settings", lambda: Settings(step_summary_enabled=False))
    messages: list[BaseMessage] = [HumanMessage(content="query")]
    for index in range(4):
        messages.extend([
            AIMessage(content="", tool_calls=[{"name": "executeSql", "args": {}, "id": str(index)}]),
            ToolMessage(content=json.dumps({"success": True, "rowCount": 1,
                                            "data": ["x" * 1000]}), tool_call_id=str(index)),
        ])
    async def unused(_old: list[BaseMessage]) -> str:
        raise AssertionError("Summary is disabled")
    result = await govern_messages(messages, context_window=200, summarize=unused)
    first = result[2]
    assert isinstance(first, ToolMessage)
    payload = json.loads(str(first.content))
    assert payload["marker"] == "[ELIDED:STALE_OBSERVATION]"
    assert payload["observationElided"] is True
    assert payload["rowCount"] == 1


def test_step_summary_prompt_uses_source_template_and_locale() -> None:
    messages: list[BaseMessage] = [ToolMessage(content='{"success":false,"error":"bad SQL"}',
                                               tool_call_id="call-1")]
    english = summary_request(messages, "en")
    chinese = summary_request(messages, "zh-CN")
    assert "Known errors" in str(english[0].content)
    assert "已知错误" in str(chinese[0].content)
    assert "bad SQL" in str(chinese[1].content)
    assert "{transcript}" not in str(chinese[1].content)


class RepeatingModel:
    def __init__(self) -> None:
        self.calls = 0
        self.messages: list[list[BaseMessage]] = []
        self.usage = Usage()
    async def call(self, messages: list[BaseMessage], **kwargs: object) -> AIMessage:
        if kwargs.get("json_contract") == "task_goal":
            return AIMessage(content=json.dumps(goal_value()))
        self.calls += 1
        self.messages.append(messages)
        if kwargs.get("event") == "summary_delta":
            return AIMessage(content="All done.")
        if self.calls <= 5:
            return AIMessage(content="", tool_calls=[{
                "name": "executeSql", "args": {"db_id": 12, "statement": "SELECT 1"},
                "id": f"call-{self.calls}",
            }])
        return AIMessage(content="All done.")


class CompactingModel:
    def __init__(self) -> None:
        self.decisions = 0
        self.summaries = 0
        self.summary_messages: list[list[BaseMessage]] = []
        self.usage = Usage(contextWindow=200)
    async def call(self, messages: list[BaseMessage], **kwargs: object) -> AIMessage:
        if kwargs.get("json_contract") == "task_goal":
            return AIMessage(content=json.dumps(goal_value()))
        if kwargs.get("tools") is None:
            self.summaries += 1
            self.summary_messages.append(messages)
            return AIMessage(content="Earlier SELECT statements succeeded with one row each.")
        self.decisions += 1
        if self.decisions > 6:
            return AIMessage(content="Queries finished.")
        return AIMessage(content="", tool_calls=[{
            "name": "executeSql", "args": {"db_id": 12, "statement": f"SELECT {self.decisions}"},
            "id": f"call-{self.decisions}",
        }])


@pytest.mark.parametrize(("locale", "start_text", "end_text"), [
    ("en", "Compacting", "Context compacted"),
    ("zh-CN", "正在压缩", "上下文已压缩"),
])
@pytest.mark.asyncio
async def test_graph_emits_compaction_phase_events(
    monkeypatch: pytest.MonkeyPatch, locale: str, start_text: str, end_text: str,
) -> None:
    from app.services import database_tools
    monkeypatch.setattr(database_tools, "get_schema", lambda _user, _db: {"tables": []})
    monkeypatch.setattr(database_tools, "execute_statement", lambda _user, _db, _sql:
                        {"success": True, "rowCount": 1, "data": [{"text": "x" * 1000}]})
    model = CompactingModel()
    events: list[tuple[str, object, int]] = []
    async def emit(kind: str, content: object, step: int) -> None:
        events.append((kind, content, step))
    request = ChatRequest.model_validate({"message": "Run several queries", "dbConfigIds": [12],
                                          "confirmedIntent": "sql_query"})
    result = await run_graph(RunContext(request, [], locale, cast(ModelStream, model),
                                        RunTools(7, request), emit))
    assert result["answer"] == "Queries finished."
    assert model.summaries > 0
    if locale == "zh-CN":
        assert "已知错误" in str(model.summary_messages[0][0].content)
    compact = [(content, step) for kind, content, step in events if kind == "context_compact"]
    assert compact
    for tier in ("elide", "summarize"):
        matching = [(content, step) for content, step in compact
                    if isinstance(content, dict) and content.get("tier") == tier]
        assert len(matching) >= 2
        assert matching[0][0]["phase"] == "start"
        assert matching[1][0]["phase"] == "end"
        assert matching[0][0]["beforeTokens"] > 0
        assert matching[1][0]["afterTokens"] > 0
        assert matching[1][0]["affectedUnits"] > 0
        assert matching[0][1] == matching[1][1]
        assert start_text in matching[0][0]["message"]
        assert end_text in matching[1][0]["message"]


@pytest.mark.asyncio
async def test_repeated_call_stops_before_fifth_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import database_tools
    executions = 0
    def execute(_user: int, _db: int, _sql: str) -> dict[str, object]:
        nonlocal executions
        executions += 1
        return {"success": True, "rowCount": 1, "data": [{"value": 1}]}
    monkeypatch.setattr(database_tools, "get_schema", lambda _user, _db: {"tables": []})
    monkeypatch.setattr(database_tools, "execute_statement", execute)
    model = RepeatingModel()
    events: list[tuple[str, object]] = []
    async def emit(kind: str, content: object, _step: int) -> None:
        events.append((kind, content))

    request = ChatRequest.model_validate({"message": "Run query", "dbConfigIds": [12],
                                          "confirmedIntent": "sql_query"})
    tools = RunTools(7, request)
    context = RunContext(request, [], "en", cast(ModelStream, model), tools, emit)
    result = await run_graph(context)
    assert executions == 4
    assert model.calls == 6
    assert any("Change strategy" in str(message.content) for message in model.messages[3]
               if isinstance(message, SystemMessage))
    assert tools.loop_stop_reason is not None
    assert "unfinished work" in result["answer"].lower()
    assert any(kind == "summary" and "unfinished work" in str(content).lower()
               for kind, content in events)


@pytest.mark.asyncio
async def test_step_limit_reports_unfinished(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.agent import graph
    from app.services import database_tools

    monkeypatch.setattr(graph, "get_settings", lambda: Settings(sql_agent_max_steps=1))
    monkeypatch.setattr(database_tools, "get_schema", lambda _user, _db: {"tables": []})
    monkeypatch.setattr(database_tools, "execute_statement", lambda _user, _db, _sql:
                        {"success": True, "rowCount": 1, "data": [{"value": 1}]})
    model = RepeatingModel()

    async def emit(_kind: str, _content: object, _step: int) -> None:
        pass

    request = ChatRequest.model_validate({"message": "Run query", "dbConfigIds": [12],
                                          "confirmedIntent": "sql_query"})
    result = await run_graph(RunContext(request, [], "en", cast(ModelStream, model),
                                        RunTools(7, request), emit))
    assert model.calls == 2
    assert result["step"] == 1
    assert "Step limit reached" in result["answer"]
