"""SQL reporting carries actual string-zero evidence unchanged."""

import json

import pytest
from test_final_report_api import final_reply
from test_model_parameters import tool_reply
from test_model_protocol import Provider, model

from app.agent.final_report import REPORT_CONTRACT
from app.agent.graph import RunContext, run_graph
from app.agent.report_rules import SQL_EVIDENCE_RULE
from app.agent.streaming import ModelStream
from app.agent.tools import RunTools
from app.agent.types import ChatRequest, Usage
from app.services import database_tools

pytest_plugins = ["test_model_protocol"]


@pytest.mark.parametrize("framed", [False, True])
@pytest.mark.asyncio
async def test_sql_fact_rules_preserve_string_zero_without_extra_branch_probe(
    provider: Provider, monkeypatch: pytest.MonkeyPatch, framed: bool,
) -> None:
    observed = {"success": True, "rowCount": 1, "data": [{"label": "North", "total_amount": "0"}]}
    statement = (
        "SELECT c.label, COALESCE(SUM(o.amount), 0) AS total_amount FROM clients c "
        "LEFT JOIN purchases o ON o.client_id=c.id GROUP BY c.label"
    )
    statements: list[str] = []

    def execute(_user: int, _db: int, sql: str, **_kwargs: object) -> dict[str, object]:
        statements.append(sql)
        return observed

    monkeypatch.setattr(database_tools, "get_schema", lambda *_args: {"tables": []})
    monkeypatch.setattr(database_tools, "execute_statement", execute)
    report = "North: 0. The returned JSON value is the string \"0\"; no fallback cause was verified."
    provider.replies = [tool_reply("executeSql", {"db_id": 12, "statement": statement})]
    provider.replies.extend(
        [tool_reply("doTerminate", {"reason": "Done"}),
         final_reply(json.dumps({"report": report, "complete": True}))]
        if framed else [final_reply(report)]
    )
    events: list[tuple[str, object]] = []

    async def emit(kind: str, content: object, _step: int) -> None:
        events.append((kind, content))

    request = ChatRequest.model_validate({"message": "List totals by client", "dbConfigIds": [12],
                                          "confirmedIntent": "sql_query"})
    usage = Usage()
    tools = RunTools(7, request)
    result = await run_graph(RunContext(request, [], "en", ModelStream(model(provider), emit, usage),
                                        tools, emit))
    assert result["answer"] == report and events[-1] == ("summary", report)
    assert statements == [statement] and tools.statements_attempted == 1 and tools.completed_write_count == 0
    assert len(provider.requests) == usage.callCount == (3 if framed else 2)
    assert usage.totalTokens == 6 * usage.callCount
    for payload in provider.requests:
        messages = payload["messages"]
        assert isinstance(messages, list)
        assert any(item["role"] == "system" and item["content"] == SQL_EVIDENCE_RULE for item in messages)
    final_messages = provider.requests[-1]["messages"]
    assert isinstance(final_messages, list)
    tool_results = [json.loads(str(item["content"])) for item in final_messages
                    if item["role"] == "tool" and item["tool_call_id"] == "executeSql"]
    assert tool_results == [observed]
    assert isinstance(tool_results[0]["data"][0]["total_amount"], str)
    assert (final_messages[-1]["content"] == REPORT_CONTRACT) is framed
