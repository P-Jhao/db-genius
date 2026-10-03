"""Comparison reports emitted directly after a tool must receive the same rules."""

import threading
from collections.abc import Iterator

import pytest
from test_compare_risk_guidance import answer, call, report, run
from test_model_protocol import Provider

from app.agent.report_rules import COMPARE_REPORT_RULE
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


@pytest.mark.parametrize("database_type", ["postgresql", "mysql"])
@pytest.mark.asyncio
async def test_direct_comparison_answer_receives_all_report_rules(
    provider: Provider, monkeypatch: pytest.MonkeyPatch, database_type: str,
) -> None:
    observed = report()
    observed.update({"preDbType": database_type, "testDbType": database_type})
    monkeypatch.setattr(schema_diff, "compare_databases", lambda *_args: observed)
    monkeypatch.setattr(database_tools, "execute_statement", lambda *_args, **_kwargs:
                        pytest.fail("Migration SQL must remain report-only"))
    final_answer = (
        "Observed additions and removals are separate facts; a rename is unverified. "
        "NUMERIC(9,2) to NUMERIC(11,2) raises integer capacity from 7 to 9 digits. "
        "For PostgreSQL precision widening, distinguish a table rewrite from locks and "
        "uncommitted rollback from recovery after commit. MySQL implicit commits and "
        "atomic DDL do not promise rollback of previously completed DDL.\n"
        "```sql\nALTER TABLE ledger ALTER COLUMN balance TYPE NUMERIC(11,2);\n```"
        if database_type == "postgresql" else
        "Observed: ledger_archive is added, retired_ledger is absent, and ledger.balance "
        "changes from NUMERIC(9,2) to NUMERIC(11,2). Integer capacity grows from 7 to 9 "
        "digits. A rename is unverified. MySQL DDL generally implicitly commits; atomic "
        "DDL is statement crash safety and does not guarantee user transaction rollback.\n"
        "```sql\nALTER TABLE ledger MODIFY balance NUMERIC(11,2);\n```"
    )
    provider.replies = [call("compareDatabases", {"pre_id": 12, "test_id": 13}), answer(final_answer)]
    result, events, tools = await run(provider)
    assert result["answer"] == final_answer and events[-1] == ("summary", final_answer)
    assert len(provider.requests) == 2 and not tools.terminated
    assert tools.statements_attempted == tools.completed_write_count == 0
    for request in provider.requests:
        messages = request["messages"]
        assert isinstance(messages, list)
        assert any(item["role"] == "system" and item["content"] == COMPARE_REPORT_RULE
                   for item in messages)
    final_messages = provider.requests[-1]["messages"]
    assert isinstance(final_messages, list)
    assert any(item["role"] == "tool" and "MODIFY_COLUMN" in str(item["content"])
               for item in final_messages)
    assert "ledger" not in COMPARE_REPORT_RULE and "balance" not in COMPARE_REPORT_RULE
