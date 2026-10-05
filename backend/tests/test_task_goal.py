"""Model semantic goals gate SQL without changing public intents or SSE payloads."""

import json

import pytest
from task_goal_fixtures import goal_reply, goal_value
from test_chat_graph import response
from test_model_parameters import tool_reply
from test_model_protocol import Provider, model

from app.agent.graph import RunContext, run_graph
from app.agent.streaming import ModelStream
from app.agent.task_goal import ClassifiedTask, TaskGoal
from app.agent.tools import RunTools
from app.agent.types import ChatRequest, Usage
from app.core.errors import BusinessError
from app.services import database_tools

pytest_plugins = ["test_model_protocol"]


async def run(provider: Provider, request: ChatRequest) -> tuple[str, RunTools, list[tuple[str, object]]]:
    events: list[tuple[str, object]] = []

    async def emit(kind: str, content: object, _step: int) -> None:
        events.append((kind, content))

    tools = RunTools(7, request)
    result = await run_graph(RunContext(request, [], "en", ModelStream(model(provider), emit, Usage()),
                                        tools, emit))
    return result["answer"], tools, events


def schema() -> dict[str, object]:
    return {"tables": [{"name": "orders", "comment": None, "columns": [
        {"name": "id", "type": "INTEGER", "nullable": False, "comment": None},
    ]}], "incomplete": False, "errorMessage": None}


@pytest.mark.parametrize("confirmed", [False, True])
@pytest.mark.parametrize("terminate", [False, True])
async def test_metadata_uses_preparation_evidence_without_sql(
    provider: Provider, monkeypatch: pytest.MonkeyPatch, confirmed: bool, terminate: bool,
) -> None:
    monkeypatch.setattr(database_tools, "get_schema", lambda *_args: schema())

    def forbidden(*_args: object) -> None:
        pytest.fail("Metadata inspection must never execute SQL")

    monkeypatch.setattr(database_tools, "execute_statement", forbidden)
    goal = goal_value(mode="metadata_only", tables=["orders"])
    provider.replies = [goal_reply(mode="metadata_only", tables=["orders"]) if confirmed else
                        response(json.dumps({"intent": "sql_query", "confidence": 0.99,
                            "reasoning": "Structure requested", "needsClarification": False,
                            "taskGoal": goal}))]
    report = "orders.id is INTEGER; the observed comment is null."
    provider.replies.extend([tool_reply("doTerminate", {"reason": "Schema read"}),
                             response(json.dumps({"report": report, "complete": True}))]
                            if terminate else [response(report)])
    request = ChatRequest(message="Describe orders structure, including the word SELECT as a label",
                          dbConfigIds=[12], confirmedIntent="sql_query" if confirmed else None)
    answer, tools, events = await run(provider, request)
    assert answer == report and tools.statements_attempted == tools.statements_executed == 0
    assert {tool.name for tool in tools.for_intent("sql_query")} == {
        "getDatabaseSchema", "readToolOutput", "doTerminate"}
    assert "tools" not in provider.requests[0]
    assert provider.requests[0]["thinking"] == {"type": "disabled"}
    assert any(kind == "classified" for kind, _ in events) is (not confirmed)
    for kind, content in events:
        if kind == "classified":
            assert isinstance(content, dict)
            assert set(content) == {"intent", "confidence", "reasoning", "needsClarification"}
    status = tools.schema_evidence.status(TaskGoal.model_validate(goal))
    assert status["complete"] is True
    assert "orders.comment" in status["databases"][0]["knownNullAttributes"]


@pytest.mark.parametrize("terminate", [False, True])
@pytest.mark.parametrize("source", [None, {"tables": None}, {"tables": [], "incomplete": True},
                                   {"tables": []},
                                   {"tables": [], "errorMessage": "catalog unavailable"},
                                   {"tables": [{"name": "orders", "columns": None}]}])
async def test_incomplete_metadata_never_becomes_complete(
    provider: Provider, monkeypatch: pytest.MonkeyPatch, terminate: bool, source: object,
) -> None:
    monkeypatch.setattr(database_tools, "get_schema", lambda *_args: source)
    provider.replies = [goal_reply(mode="metadata_only", tables=["orders"]),
                        tool_reply("doTerminate", {"reason": "Everything completed"}) if terminate
                        else response("Everything completed")]
    answer, tools, _ = await run(provider, ChatRequest(message="Show orders schema", dbConfigIds=[12],
                                                       confirmedIntent="sql_query"))
    assert "metadata is incomplete" in answer and "Everything completed" not in answer
    assert tools.statements_attempted == 0 and len(provider.requests) == 2


async def test_metadata_tool_and_direct_executor_cannot_bypass_goal(
    provider: Provider, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(database_tools, "get_schema", lambda *_args: schema())
    provider.replies = [goal_reply(mode="metadata_only"),
                        tool_reply("executeSql", {"db_id": 12, "statement": "SELECT * FROM orders"})]
    with pytest.raises(BusinessError, match="Unknown model tool"):
        await run(provider, ChatRequest(message="Show schema", dbConfigIds=[12], confirmedIntent="sql_query"))
    tools = RunTools(7, ChatRequest(message="schema", dbConfigIds=[12]))
    tools.task_goal = TaskGoal.model_validate(goal_value(mode="metadata_only"))
    with pytest.raises(BusinessError, match="Metadata-only"):
        await tools.execute(12, "INSERT INTO orders VALUES (1)")
    assert tools.statements_attempted == 0


@pytest.mark.parametrize("confirmed", [False, True])
@pytest.mark.parametrize("confidence,clarify", [(0.4, False), (0.99, True)])
async def test_goal_uncertainty_clarifies_before_metadata_or_sql(
    provider: Provider, confirmed: bool, confidence: float, clarify: bool,
) -> None:
    goal = goal_value(confidence=confidence, clarify=clarify)
    provider.replies = [goal_reply(confidence=confidence, clarify=clarify) if confirmed else
                        response(json.dumps({"intent": "sql_query", "confidence": 0.99,
                            "reasoning": "Goal ambiguous", "needsClarification": False, "taskGoal": goal}))]
    _, tools, events = await run(provider, ChatRequest(message="Do that to the selected database",
                                 dbConfigIds=[12], confirmedIntent="sql_query" if confirmed else None))
    assert events[-1][0] == "clarify" and len(provider.requests) == 1
    assert tools.schema_evidence.observations == {} and tools.statements_attempted == 0


@pytest.mark.parametrize("change", [
    {"mode": "unknown"}, {"dbIds": ["12"]}, {"needsClarification": "false"},
    {"extra": 1}, {"tableScope": [{"dbId": 12, "tables": []}]},
    {"tableScope": [{"dbId": 99, "tables": None}]},
])
def test_strict_goal_contract_rejects_invalid_fields(change: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        TaskGoal.model_validate({**goal_value(), **change})
    with pytest.raises(ValueError):
        ClassifiedTask.model_validate({"intent": "sql_query", "confidence": 0.99,
            "reasoning": "Reviewed", "needsClarification": False, "taskGoal": {**goal_value(), **change}})


@pytest.mark.parametrize("write", [False, True])
async def test_mixed_structure_and_operation_requires_statement_execution(
    provider: Provider, monkeypatch: pytest.MonkeyPatch, write: bool,
) -> None:
    monkeypatch.setattr(database_tools, "get_schema", lambda *_args: schema())
    statements: list[str] = []

    def execute(_user: int, _db: int, statement: str) -> dict[str, object]:
        statements.append(statement)
        return {"success": True, "affectedRows": 1} if write else {
            "success": True, "data": [{"n": 5}], "rowCount": 1}

    monkeypatch.setattr(database_tools, "execute_statement", execute)
    statement = "INSERT INTO orders VALUES (1)" if write else "SELECT COUNT(*) AS n FROM orders"
    report = "orders.id is INTEGER; 1 row inserted." if write else "orders.id is INTEGER; 5 rows."
    provider.replies = [goal_reply(), tool_reply("executeSql", {"db_id": 12,
        "statement": statement}), response(report)]
    message = "Show orders structure and insert row 1" if write else "Show orders structure and count rows"
    answer, tools, _ = await run(provider, ChatRequest(message=message,
                                   dbConfigIds=[12], confirmedIntent="sql_query"))
    assert statements == [statement] and tools.statements_executed == 1
    assert tools.completed_write_count == int(write) and answer == report
