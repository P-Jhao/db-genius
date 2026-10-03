"""Both comparison report paths retain actual tool evidence and review-only SQL."""

import json

import pytest
from test_compare_risk_guidance import answer, call, run
from test_model_protocol import Provider

from app.agent.final_report import REPORT_CONTRACT
from app.agent.report_rules import COMPARE_REPORT_RULE
from app.services import database_tools, schema_diff

pytest_plugins = ["test_model_protocol"]


@pytest.mark.parametrize("framed", [False, True])
@pytest.mark.asyncio
async def test_changed_shared_table_and_checked_unchanged_subset_reach_both_paths(
    provider: Provider, monkeypatch: pytest.MonkeyPatch, framed: bool,
) -> None:
    observed: dict[str, object] = {
        "success": True, "complete": True,
        "preDatabase": "current", "testDatabase": "desired",
        "preDbType": "postgresql", "testDbType": "postgresql",
        "summary": {"newTables": 1, "droppedTables": 1, "alteredTables": 1},
        "newTables": [{"table": "events_new", "columns": [{"name": "id", "type": "INTEGER"}]}],
        "droppedTables": [{"table": "notes_old"}],
        "alteredTables": [{"table": "sales", "changes": [{
            "change": "MODIFY_COLUMN", "column": "amount",
            "preType": "NUMERIC(12,2)", "testType": "NUMERIC(14,2)",
        }]}],
        "checkedUnchangedTables": [{"table": "contacts", "attributes": ["columns", "types"]}],
        "verifiedIndexes": [{"table": "sales", "name": "ix_sales_region", "columns": ["region"]}],
        "unreadMetadata": ["columnDefaults", "foreignKeys"],
    }
    calls: list[tuple[int, int, int]] = []

    def compare(user: int, pre: int, target: int) -> dict[str, object]:
        calls.append((user, pre, target))
        return observed

    monkeypatch.setattr(schema_diff, "compare_databases", compare)
    monkeypatch.setattr(database_tools, "execute_statement", lambda *_args, **_kwargs:
                        pytest.fail("Migration SQL must never be executed"))
    monkeypatch.setattr(database_tools, "execute_comparison_read", lambda *_args, **_kwargs:
                        pytest.fail("No row-value read was requested"))
    report = (
        "1 added table, 1 dropped table, 1 changed table. sales and contacts exist on both sides; "
        "sales.amount changed from NUMERIC(12,2) to NUMERIC(14,2). contacts has no observed "
        "column or type changes. ix_sales_region was read; column defaults and foreign keys "
        "were not read. Target row values are unknown. If executed, this script would widen "
        "sales.amount; no migration SQL has been executed.\n"
        "```sql\nALTER TABLE sales ALTER COLUMN amount TYPE NUMERIC(14,2);\n```"
    )
    provider.replies = ([call("doTerminate", {"reason": "Report ready"}),
                         answer(json.dumps({"report": report, "complete": True}))]
                        if framed else [answer(report)])
    result, events, tools = await run(provider)
    assert result["answer"] == report and events[-1] == ("summary", report)
    assert calls == [(7, 12, 13)]
    assert len(provider.requests) == (2 if framed else 1)
    assert tools.statements_attempted == tools.completed_write_count == 0
    for payload in provider.requests:
        messages = payload["messages"]
        assert isinstance(messages, list)
        system = [str(item["content"]) for item in messages if item["role"] == "system"]
        assert any(COMPARE_REPORT_RULE in content for content in system)
        observations = [str(item["content"]) for item in messages
                        if item["role"] == "user" and "Server preparation observation" in str(item["content"])]
        assert len(observations) == 1
        saved_evidence = json.loads(observations[0].split("\n", 1)[1])
        assert saved_evidence == observed
        assert payload["temperature"] == 0.7 and "response_format" not in payload
    last_messages = provider.requests[-1]["messages"]
    assert isinstance(last_messages, list)
    assert (last_messages[-1]["content"] == REPORT_CONTRACT) is framed
    assert all(name not in COMPARE_REPORT_RULE for name in ("sales", "contacts", "ix_sales_region"))
