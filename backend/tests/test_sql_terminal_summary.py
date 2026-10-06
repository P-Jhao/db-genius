"""SQL direct drafts use the same guarded report path as tool termination."""

import json
import logging
from uuid import UUID

import pytest
from chat_terminal_fixtures import DRAFT, PAGE_OFFSETS, REPORT, configure_paging, replies, schema
from langchain_core.messages import AIMessage, HumanMessage
from task_goal_fixtures import goal_reply
from test_chat_graph import response
from test_model_parameters import tool_reply
from test_model_protocol import Provider, model

from app.agent import output_guard
from app.agent.graph import RunContext, run_graph
from app.agent.streaming import ModelStream
from app.agent.tools import RunTools
from app.agent.types import ChatRequest, Usage
from app.services import database_tools

pytest_plugins = ["test_model_protocol"]


async def run(provider: Provider, monkeypatch: pytest.MonkeyPatch, *, terminate: bool,
              pages: int = 4, partial: bool = False,
              refresh_after_pages: int | None = None) -> tuple[str, RunTools, list[tuple[str, object]]]:
    configure_paging(monkeypatch)
    source = schema()
    if partial:
        source["incomplete"] = True
    monkeypatch.setattr(database_tools, "get_schema", lambda *_: source)

    def forbidden(*_args: object) -> None:
        pytest.fail("Metadata-only tasks cannot execute SQL")

    monkeypatch.setattr(database_tools, "execute_statement", forbidden)
    provider.replies = list(replies(1, terminate=terminate, pages=pages))
    if refresh_after_pages is not None:
        identities = iter([UUID(int=1), UUID(int=2)])
        monkeypatch.setattr(output_guard, "uuid4", lambda: next(identities))
        provider.replies.insert(1 + refresh_after_pages, tool_reply("getDatabaseSchema", {"db_id": 1}))
    if partial and pages == 4:
        provider.replies.pop()
    events: list[tuple[str, object]] = []

    async def emit(kind: str, content: object, _step: int) -> None:
        events.append((kind, content))

    request = ChatRequest.model_validate({"message": "有哪些表", "dbConfigIds": [1],
                                          "confirmedIntent": "sql_query"})
    tools = RunTools(7, request)
    previous = [HumanMessage(content="有哪些表"), AIMessage(content="无法访问数据库，请选择数据源。")]
    result = await run_graph(RunContext(request, previous, "zh-CN",
                                       ModelStream(model(provider), emit, Usage(contextWindow=100000)),
                                       tools, emit))
    return result["answer"], tools, events


@pytest.mark.parametrize("terminate", [False, True])
async def test_real_four_pages_direct_and_terminate_deliver_same_report(
    provider: Provider, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    terminate: bool,
) -> None:
    with caplog.at_level(logging.INFO, logger="app.agent.sql_terminal_diagnostics"):
        answer, tools, events = await run(provider, monkeypatch, terminate=terminate)
    assert answer == REPORT and DRAFT not in str(events)
    assert tools.statements_attempted == tools.statements_executed == 0
    assert len(provider.requests) == 7 and not provider.replies
    assert [content for kind, content in events if kind == "summary"] == [REPORT]
    assert "".join(str(content) for kind, content in events if kind == "summary_delta") == REPORT
    if not terminate:
        assert [content for kind, content in events if kind == "reasoning"] == [
            "schema inspection complete", "final check"]
    messages = provider.requests[-1]["messages"]
    assert isinstance(messages, list) and "tools" not in provider.requests[-1]
    assert any(message["content"] == "无法访问数据库，请选择数据源。" for message in messages)
    assert DRAFT not in json.dumps(messages, ensure_ascii=False)
    pages = [json.loads(message["content"]) for message in messages if message["role"] == "tool"
             and message["tool_call_id"] == "readToolOutput"]
    assert [page["offset"] for page in pages] == list(PAGE_OFFSETS)
    assert [page["nextOffset"] for page in pages] == [3407, 6803, 10204, 11889]
    assert len("".join(page["content"] for page in pages)) == 11889
    assert tools.task_goal is not None
    assert tools.schema_evidence.status(tools.task_goal)["complete"] is True
    diagnostics = [json.loads(record.message.removeprefix("SQL completion ")) for record in caplog.records
                   if record.name == "app.agent.sql_terminal_diagnostics"]
    assert diagnostics[-1] == {"taskId": tools.task_id, "taskGoalMode": "metadata_only",
        "terminalPath": "terminate" if terminate else "direct", "overrideApplied": False,
        "schemaEvidenceComplete": True, "statementsAttempted": 0, "statementsExecuted": 0}
    assert len(diagnostics) == (1 if terminate else 2)
    assert all(set(row) == set(diagnostics[-1]) for row in diagnostics)
    assert "ai_chat_messages" not in caplog.text and DRAFT not in caplog.text


@pytest.mark.parametrize("terminate", [False, True])
@pytest.mark.parametrize("refresh_after_pages", [0, 2, 4])
async def test_schema_refresh_does_not_discard_complete_original_artifact_pages(
    provider: Provider, monkeypatch: pytest.MonkeyPatch, terminate: bool, refresh_after_pages: int,
) -> None:
    answer, tools, events = await run(provider, monkeypatch, terminate=terminate,
                                     refresh_after_pages=refresh_after_pages)
    assert answer == REPORT and DRAFT not in str(events)
    assert len(provider.requests) == 8 and not provider.replies
    assert tools.task_goal is not None and tools.schema_evidence.status(tools.task_goal)["complete"] is True
    assert len(tools.schema_evidence.artifacts) == 2
    assert tools.schema_evidence.artifacts[UUID(int=2).hex][1].pages == {}
    assert tools.statements_attempted == tools.statements_executed == 0


@pytest.mark.parametrize("terminate", [False, True])
@pytest.mark.parametrize("pages,partial", [(3, False), (4, True)])
async def test_missing_page_and_partial_source_stop_without_final_model(
    provider: Provider, monkeypatch: pytest.MonkeyPatch, terminate: bool, pages: int, partial: bool,
) -> None:
    answer, tools, events = await run(provider, monkeypatch, terminate=terminate, pages=pages, partial=partial)
    assert "元数据不完整" in answer and DRAFT not in answer and answer != REPORT
    assert len(provider.requests) == pages + 2 and not provider.replies
    assert "summary_delta" not in [kind for kind, _ in events]
    assert tools.statements_attempted == tools.statements_executed == 0


@pytest.mark.parametrize("terminate", [False, True])
@pytest.mark.parametrize("failed", [False, True])
async def test_execution_goal_zero_success_stays_authoritative(
    provider: Provider, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    terminate: bool, failed: bool,
) -> None:
    monkeypatch.setattr(database_tools, "get_schema", lambda *_: schema())
    monkeypatch.setattr(database_tools, "execute_statement", lambda *_: {
        "success": False, "error": "Unknown table synthetic_missing"})
    provider.replies = [goal_reply([1])]
    if failed:
        provider.replies.append(tool_reply("executeSql", {"db_id": 1,
            "statement": "SELECT * FROM synthetic_missing"}))
    provider.replies.append(tool_reply("doTerminate", {"reason": "All complete"}) if terminate else
                            response("All complete"))

    async def emit(_kind: str, _content: object, _step: int) -> None:
        pass

    request = ChatRequest.model_validate({"message": "Query records", "dbConfigIds": [1],
                                          "confirmedIntent": "sql_query"})
    tools = RunTools(7, request)
    with caplog.at_level(logging.INFO, logger="app.agent.sql_terminal_diagnostics"):
        result = await run_graph(RunContext(request, [], "en", ModelStream(model(provider), emit, Usage()),
                                           tools, emit))
    assert "No database statement was successfully executed" in result["answer"]
    assert "All complete" not in result["answer"] and len(provider.requests) == 2 + int(failed)
    assert tools.statements_executed == 0 and tools.statements_attempted == int(failed)
    if failed:
        assert "Unknown table synthetic_missing" in result["answer"]
    assert '"overrideApplied": true' in caplog.text
    assert "synthetic_missing" not in caplog.text
