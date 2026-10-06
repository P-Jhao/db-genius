"""Source-compatible row limits, per-tool overrides, and full SSE observations."""

import json
from typing import cast

import pytest
from langchain_core.messages import AIMessage, BaseMessage
from pydantic import ValidationError
from task_goal_fixtures import goal_value

from app.agent import output_guard
from app.agent.graph import RunContext, run_graph
from app.agent.output_guard import OutputArtifacts, bound_json
from app.agent.streaming import ModelStream
from app.agent.tools import OutputInput, RunTools
from app.agent.types import ChatRequest, Usage
from app.core.config import Settings
from app.services import database_tools


@pytest.mark.parametrize("field", ["data", "result", "rows", "values"])
def test_oversized_row_sets_preserve_shape_and_fifty_rows(field: str) -> None:
    source = {"success": True, "rowCount": 100, field: [{"id": index, "note": "x" * 45}
                                                     for index in range(100)]}
    result = json.loads(bound_json(source, OutputArtifacts(1, "task"), tool_name="executeSql"))
    assert result["success"] is True and result["rowCount"] == 100
    assert len(result[field]) == 50
    assert result["returnedItems"] == 50 and result["totalItems"] == 100
    assert result["marker"] == "[TRUNCATED:TOOL_OUTPUT_TOO_LONG]"


def test_per_tool_limit_is_used_and_rejects_malformed_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(tool_output_per_tool_max_characters="executeSql=8000,readToolOutput=900")
    monkeypatch.setattr(output_guard, "get_settings", lambda: settings)
    value = {"data": ["x" * 50 for _ in range(100)]}
    assert json.loads(bound_json(value, OutputArtifacts(1, "one"), tool_name="executeSql")) == value
    assert json.loads(bound_json(value, OutputArtifacts(1, "two"), tool_name="readFile"))["truncated"]
    artifacts = OutputArtifacts(1, "page")
    artifact_id = artifacts.add("x" * 5000)
    assert len(artifacts.read(artifact_id, user_id=1, task_id="page", offset=0, length=4000)) <= 900
    for invalid in ["executeSql=0", "executeSql=4000,executeSql=8000", "not an entry", {"readFile": True}]:
        with pytest.raises(ValidationError):
            Settings(tool_output_per_tool_max_characters=invalid)


def test_override_environment_supports_source_pairs_and_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SQLCHAT_TOOL_OUTPUT_PER_TOOL_MAX_CHARACTERS", "readFile=6000")
    assert Settings().tool_output_per_tool_max_characters == {"readFile": 6000}
    monkeypatch.setenv("SQLCHAT_TOOL_OUTPUT_PER_TOOL_MAX_CHARACTERS", '{"readFile": 7000}')
    assert Settings().tool_output_per_tool_max_characters == {"readFile": 7000}


def test_paging_tool_and_artifact_describe_actual_next_offset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(output_guard, "get_settings", lambda: Settings(tool_output_max_characters=950))
    artifacts = OutputArtifacts(1, "paging-contract")
    envelope = json.loads(bound_json({"notes": "x" * 5000}, artifacts, tool_name="getDatabaseSchema"))
    instruction = envelope["instruction"]
    assert "returned nextOffset" in instruction and "length cap may shrink" in instruction
    assert "hasMore=false" in instruction and "tail≠no gaps" in instruction
    tools = RunTools(1, ChatRequest.model_validate({"message": "synthetic"}))
    definition = next(tool for tool in tools.for_intent("sql_query") if tool.name == "readToolOutput")
    assert "returned nextOffset" in definition.description and "offset + requested length" in definition.description
    assert "hasMore=false" in definition.description and "earlier gaps" in definition.description
    properties = OutputInput.model_json_schema()["properties"]
    assert "returned nextOffset" in properties["offset"]["description"]
    assert "upper bound" in properties["length"]["description"]
    first = json.loads(artifacts.read(envelope["artifactId"], user_id=1, task_id="paging-contract",
                                    offset=0, length=8000))
    assert first["nextOffset"] < 8000
    second = json.loads(artifacts.read(envelope["artifactId"], user_id=1, task_id="paging-contract",
                                     offset=first["nextOffset"], length=8000))
    assert second["offset"] == first["nextOffset"]


class QueryModel:
    def __init__(self) -> None:
        self.usage = Usage()
        self.calls: list[list[BaseMessage]] = []

    async def call(self, messages: list[BaseMessage], **kwargs: object) -> AIMessage:
        if kwargs.get("json_contract") == "task_goal":
            return AIMessage(content=json.dumps(goal_value()))
        self.calls.append(messages)
        if len(self.calls) == 1:
            return AIMessage(content="", tool_calls=[{"name": "executeSql", "id": "query",
                                                      "args": {"db_id": 12, "statement": "SELECT rows"}}])
        return AIMessage(content="One hundred rows returned.")


@pytest.mark.asyncio
async def test_graph_bounds_model_only_and_keeps_full_sse_result(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [{"id": index, "note": "x" * 60} for index in range(100)]
    source = {"success": True, "rowCount": 100, "data": rows}
    monkeypatch.setattr(database_tools, "get_schema", lambda _user, _db: {"tables": []})
    monkeypatch.setattr(database_tools, "execute_statement", lambda _user, _db, _sql: source)
    request = ChatRequest(message="query", dbConfigIds=[12], confirmedIntent="sql_query")
    model = QueryModel()
    events: list[tuple[str, object]] = []

    async def emit(kind: str, content: object, _step: int) -> None:
        events.append((kind, content))

    tools = RunTools(1, request)
    await run_graph(RunContext(request, [], "en", cast(ModelStream, model), tools, emit))
    observation = json.loads(str(model.calls[1][-1].content))
    assert observation["truncated"] is True and len(observation["data"]) < 100
    display = next(str(content) for kind, content in events
                   if kind == "step" and str(content).startswith("executeSql: "))
    assert json.loads(display.removeprefix("executeSql: ")) == source
    assert tools.last_result == source
