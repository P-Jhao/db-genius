"""A comparison report must be present in the delivered final answer."""

import json
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from test_compare_graph import answer, call, request, sqlite_schemas
from test_model_protocol import Provider, model

from app.agent.final_report import REPORT_CONTRACT
from app.agent.graph import RunContext, run_graph
from app.agent.report_rules import COMPARE_REPORT_RULE
from app.agent.streaming import ModelStream
from app.agent.tools import RunTools
from app.agent.types import Usage
from app.services import database_tools


@pytest.fixture
def provider() -> Iterator[Provider]:
    service = Provider([])
    thread = threading.Thread(target=service.serve_forever, daemon=True)
    thread.start()
    yield service
    service.shutdown()
    service.server_close()
    thread.join(timeout=2)


@pytest.mark.asyncio
async def test_complete_comparison_final_answer_contains_actual_report_and_sql(
    provider: Provider, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    sqlite_schemas(monkeypatch, tmp_path)
    monkeypatch.setattr(database_tools, "execute_statement", lambda *_args, **_kwargs:
                        pytest.fail("Migration SQL reached the execution service"))
    monkeypatch.setattr(database_tools, "execute_comparison_read", lambda *_args, **_kwargs:
                        pytest.fail("No comparison SQL read was requested"))
    final_report = (
        "pre → test: orders is new, retired is absent, and users.email was added. "
        "Review the data loss risk for retired before deployment.\n\n"
        "```sql\nCREATE TABLE orders (id INTEGER PRIMARY KEY);\n```"
    )
    provider.replies = [
        call("doTerminate", {"reason": "The report and SQL were already delivered"}, "terminate"),
        answer(json.dumps({"report": final_report, "complete": True})),
    ]
    events: list[tuple[str, object]] = []

    async def emit(kind: str, content: object, _step: int) -> None:
        events.append((kind, content))

    chat_request = request()
    tools = RunTools(7, chat_request)
    result = await run_graph(RunContext(chat_request, [], "en", ModelStream(model(provider), emit, Usage()),
                                        tools, emit))
    assert result["answer"] == final_report
    assert events[-1] == ("summary", final_report)
    assert "CREATE TABLE orders" in result["answer"]
    assert all(name in result["answer"] for name in ("orders", "retired", "users.email"))
    assert tools.statements_attempted == tools.completed_write_count == 0
    assert len(provider.requests) == 2
    final_messages = provider.requests[-1]["messages"]
    assert isinstance(final_messages, list)
    final_system = [str(item["content"]) for item in final_messages if item["role"] == "system"]
    assert any(COMPARE_REPORT_RULE in content for content in final_system)
    assert final_system[-1] == REPORT_CONTRACT
    assert any(item["role"] == "user" and "Server preparation observation" in str(item["content"]) and "newTables" in str(item["content"])
               for item in final_messages)
