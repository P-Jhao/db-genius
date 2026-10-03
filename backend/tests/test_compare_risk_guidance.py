"""Evidence-based comparison risk guidance in the delivered graph summary."""

import json
import threading
from collections.abc import Iterator

import pytest
from test_model_protocol import Provider, frame, model

from app.agent.final_report import REPORT_CONTRACT
from app.agent.graph import RunContext, run_graph
from app.agent.report_rules import COMPARE_REPORT_RULE
from app.agent.streaming import ModelStream
from app.agent.tools import RunTools
from app.agent.types import ChatRequest, Usage
from app.services import database_tools, schema_diff


@pytest.fixture
def provider() -> Iterator[Provider]:
    service = Provider([])
    thread = threading.Thread(target=service.serve_forever, daemon=True)
    thread.start()
    yield service
    service.shutdown()
    service.server_close()
    thread.join(timeout=2)


def answer(content: str) -> list[bytes]:
    return [frame({"choices": [{"delta": {"content": content}}]}), frame("[DONE]")]


def call(name: str, args: dict[str, object]) -> list[bytes]:
    return [frame({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": name,
             "function": {"name": name, "arguments": json.dumps(args)}}]}}]}), frame("[DONE]")]


def report(*, complete: bool = True) -> dict[str, object]:
    return {
        "success": complete, "complete": complete,
        "preDatabase": "current", "testDatabase": "desired",
        "preDbType": "postgresql", "testDbType": "postgresql",
        "newTables": [{"table": "ledger_archive", "columnCount": 2}],
        "droppedTables": [{"table": "retired_ledger", "columnCount": 2}],
        "alteredTables": [{"table": "ledger", "changes": [
            {"change": "MODIFY_COLUMN", "column": "balance", "preType": "NUMERIC(9,2)",
             "testType": "NUMERIC(11,2)"},
        ]}],
    }


def mysql_report() -> dict[str, object]:
    result = report()
    result["preDbType"] = "mysql"
    result["testDbType"] = "mysql"
    return result


async def run(provider: Provider) -> tuple[dict[str, object], list[tuple[str, object]], RunTools]:
    events: list[tuple[str, object]] = []

    async def emit(kind: str, content: object, _step: int) -> None:
        events.append((kind, content))

    request = ChatRequest.model_validate({"message": "Compare current and desired schemas",
                                          "preDbConfigId": 12, "testDbConfigId": 13,
                                          "confirmedIntent": "db_compare"})
    tools = RunTools(7, request)
    result = await run_graph(RunContext(request, [], "en", ModelStream(model(provider), emit, Usage()),
                                        tools, emit))
    return result, events, tools


@pytest.mark.asyncio
async def test_report_distinguishes_precision_rewrite_lock_and_rollback(
    provider: Provider, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(schema_diff, "compare_databases", lambda _user, _pre, _test: report())
    monkeypatch.setattr(database_tools, "execute_statement", lambda *_args, **_kwargs:
                        pytest.fail("Migration SQL must remain report-only"))
    final_report = (
        "Observed: ledger_archive was added, retired_ledger is absent, and ledger.balance "
        "changed from NUMERIC(9,2) to NUMERIC(11,2). Precision is total digits; integer "
        "capacity rises from 7 to 9 digits because scale remains 2. On PostgreSQL 16, "
        "this precision widening need not rewrite the table, but ALTER TABLE can acquire "
        "an ACCESS EXCLUSIVE lock. An uncommitted transactional DDL change can be rolled back; "
        "after commit, recovery is a separate task. A possible rename between the two table "
        "names is unverified.\n```sql\nALTER TABLE ledger ALTER COLUMN balance TYPE NUMERIC(11,2);\n```"
    )
    provider.replies = [call("doTerminate", {"reason": "Report ready"}),
                        answer(json.dumps({"report": final_report, "complete": True}))]
    result, events, tools = await run(provider)
    assert result["answer"] == final_report and events[-1] == ("summary", final_report)
    assert tools.statements_attempted == tools.completed_write_count == 0
    assert len(provider.requests) == 2
    messages = provider.requests[-1]["messages"]
    assert isinstance(messages, list)
    system = "\n".join(str(item["content"]) for item in messages if item["role"] == "system")
    assert COMPARE_REPORT_RULE in system and REPORT_CONTRACT in system
    assert "ledger" not in system and "balance" not in system
    assert any(item["role"] == "user" and "Server preparation observation" in str(item["content"]) and "MODIFY_COLUMN" in str(item["content"])
               for item in messages)
    assert "integer capacity rises from 7 to 9" in final_report
    assert "possible rename" in final_report and "unverified" in final_report


@pytest.mark.asyncio
async def test_incomplete_comparison_still_returns_bounded_factual_report(
    provider: Provider, monkeypatch: pytest.MonkeyPatch,
) -> None:
    incomplete = report(complete=False)
    monkeypatch.setattr(schema_diff, "compare_databases", lambda _user, _pre, _test: incomplete)
    provider.replies = [call("compareDatabases", {"pre_id": 12, "test_id": 13})]
    result, events, tools = await run(provider)
    assert "comparison is incomplete" in str(result["answer"])
    assert "No directly executable migration SQL" in str(result["answer"])
    assert len(provider.requests) == 0 and tools.statements_attempted == 0
    assert events[-1] == ("summary", result["answer"])


@pytest.mark.asyncio
async def test_mysql_report_receives_implicit_commit_boundary(
    provider: Provider, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(schema_diff, "compare_databases", lambda _user, _pre, _test: mysql_report())
    provider.replies = [call("doTerminate", {"reason": "Report ready"}),
                        answer(json.dumps({"report": "MySQL DDL can implicitly commit; a later failure cannot be "
                                          "promised to restore earlier DDL. Atomic DDL is not "
                                          "user-transaction rollback.", "complete": True}))]
    result, _, tools = await run(provider)
    assert "cannot be promised" in str(result["answer"])
    messages = provider.requests[-1]["messages"]
    assert isinstance(messages, list)
    system = "\n".join(str(item["content"]) for item in messages if item["role"] == "system")
    assert COMPARE_REPORT_RULE in system and REPORT_CONTRACT in system
    assert tools.statements_attempted == 0
