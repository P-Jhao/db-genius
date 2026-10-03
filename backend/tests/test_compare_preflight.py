"""Mandatory real graph preparation with a controlled local HTTP provider."""

import json
import threading
from typing import cast

import pytest
from compare_preflight_helpers import context, observations
from real_model_cases import fixed_cases
from real_model_database import TargetSnapshot
from real_model_evidence import comparison_matches, judge_turn, tool_results
from real_model_evidence_test import IndependentTarget, comparison
from test_compare_graph import answer, call
from test_compare_risk_guidance import report
from test_model_protocol import Provider
from test_schema_diff import _schema

from app.agent.cancellation import RunAborted
from app.agent.graph import run_graph
from app.core import observability_runtime
from app.core.config import get_settings
from app.core.errors import BusinessError
from app.services import database_tools, schema_diff

pytest_plugins = ["test_model_protocol"]


@pytest.mark.asyncio
async def test_original_acceptance_parser_recognizes_server_diff_as_successful_actual_evidence(
    provider: Provider, monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed = comparison()
    observed.update({"complete": True, "preDbType": "postgresql", "testDbType": "postgresql"})
    monkeypatch.setattr(schema_diff, "compare_databases", lambda *_args: observed)
    case = next(case for case in fixed_cases() if case.uses_compare)
    provider.replies = [answer("pre→test: add audit_events, remove legacy_notes, add customers.loyalty_level, "
                               "and widen orders.amount from NUMERIC(12,2) to NUMERIC(14,2).")]
    run, emitted = context(provider)
    run.request.message = case.questions[0]
    result = await run_graph(run)
    events: list[dict[str, object]] = [{"type": "conversation", "content": 7}]
    events.extend({"type": kind, "content": content} for kind, content, _ in emitted)
    events.append({"type": "done"})
    parsed = tool_results(events)
    assert len(parsed) == 1 and parsed[0].name == "compareDatabases"
    assert comparison_matches(parsed[0].value, "pre", "test")
    assert not comparison_matches(parsed[0].value, "test", "pre")

    class NamedTarget(IndependentTarget):
        def __init__(self, name: str) -> None:
            self.name = name

    history: list[dict[str, object]] = [{"role": "user", "content": case.questions[0]},
        {"role": "assistant", "type": "summary", "content": result["answer"]}]
    judged = judge_turn(case, 0, events, history, cast(TargetSnapshot, NamedTarget("pre")),
                       "unchanged", cast(TargetSnapshot, NamedTarget("test")))
    checks = judged["checks"]
    assert isinstance(checks, dict)
    assert checks["requiredTools"] is True and checks["comparisonDirectionAndChanges"] is True
    assert len(provider.requests) == run.model_stream.usage.callCount == 1


@pytest.mark.asyncio
async def test_server_diff_precedes_first_plain_answer_without_fabricated_model_call(
    provider: Provider, monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[int, int, int]] = []
    audit: list[tuple[str, str]] = []

    def compare(user: int, pre: int, test: int) -> dict[str, object]:
        assert provider.requests == []
        calls.append((user, pre, test))
        return report()

    monkeypatch.setattr(schema_diff, "compare_databases", compare)
    monkeypatch.setattr(observability_runtime, "tool_call", lambda name, outcome: audit.append((name, outcome)))
    provider.replies = [answer("Observed pre→test: ledger.balance precision is widened.")]
    run, events = context(provider)
    result = await run_graph(run)
    assert result["answer"].startswith("Observed pre→test")
    assert calls == [(7, 12, 13)] and audit == [("compareDatabases", "done")]
    assert len(provider.requests) == run.model_stream.usage.callCount == 1
    assert run.model_stream.usage.totalTokens == 0
    assert run.tools.statements_attempted == run.tools.completed_write_count == 0
    messages = provider.requests[0]["messages"]
    assert isinstance(messages, list)
    assert all(message["role"] != "tool" and "tool_calls" not in message for message in messages)
    actual = observations(provider, "compareDatabases")
    assert len(actual) == 1 and json.loads(actual[0]) == report()
    assert any(kind == "step" and step == 1 and str(content).startswith("compareDatabases:")
               for kind, content, step in events)
    assert run.tools.artifacts._items == {}


@pytest.mark.asyncio
async def test_completed_empty_diff_is_valid_evidence(provider: Provider, monkeypatch: pytest.MonkeyPatch) -> None:
    observed = report()
    observed.update({"newTables": [], "droppedTables": [], "alteredTables": []})
    monkeypatch.setattr(schema_diff, "compare_databases", lambda *_args: observed)
    provider.replies = [answer("The completed comparison found no observed differences.")]
    run, _ = context(provider)
    result = await run_graph(run)
    assert result["answer"] == "The completed comparison found no observed differences."
    assert len(provider.requests) == 1
    assert json.loads(observations(provider, "compareDatabases")[0])["alteredTables"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,phrase", [("incomplete", "comparison is incomplete"),
    ("cross", "Cross-engine comparison"), ("inferred", "unobserved fields may still exist")])
async def test_limited_evidence_stops_before_any_report_model(
    provider: Provider, monkeypatch: pytest.MonkeyPatch, kind: str, phrase: str,
) -> None:
    observed = report()
    if kind == "incomplete":
        observed.update({"success": False, "complete": False, "preError": "metadata failed"})
    elif kind == "cross":
        observed["testDbType"] = "mysql"
    else:
        observed.update({"preSchemaInferred": True, "preSampleSize": 50})
    monkeypatch.setattr(schema_diff, "compare_databases", lambda *_args: observed)
    provider.replies = [answer("Migration succeeded.")]
    run, events = context(provider)
    result = await run_graph(run)
    assert phrase in result["answer"] and "No directly executable migration SQL" in result["answer"]
    assert "Migration succeeded" not in result["answer"]
    assert provider.requests == [] and run.model_stream.usage.callCount == 0
    assert not any(kind == "summary_delta" for kind, _, _ in events)


@pytest.mark.asyncio
async def test_metadata_ownership_failure_prevents_model_and_test_read(
    provider: Provider, monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolved: list[tuple[int, int]] = []

    def owned(user: int, db: int) -> object:
        resolved.append((user, db))
        raise BusinessError(404, "Database configuration not found", 404)

    monkeypatch.setattr(database_tools, "_ready_config", owned)
    run, _ = context(provider)
    with pytest.raises(BusinessError) as denied:
        await run_graph(run)
    assert denied.value.code == 404 and resolved == [(7, 12)] and provider.requests == []


@pytest.mark.asyncio
async def test_selected_target_guard_applies_to_server_preparation(
    provider: Provider, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(schema_diff, "compare_databases", lambda *_args: pytest.fail("Unselected service call"))
    run, _ = context(provider)
    run.tools.database_ids.remove(13)
    with pytest.raises(BusinessError, match="not selected"):
        await run_graph(run)
    assert provider.requests == []


@pytest.mark.asyncio
async def test_provider_reverse_request_still_cannot_change_direction(
    provider: Provider, monkeypatch: pytest.MonkeyPatch,
) -> None:
    pairs: list[tuple[int, int]] = []

    def compare(_user: int, pre: int, test: int) -> dict[str, object]:
        pairs.append((pre, test))
        return report()

    monkeypatch.setattr(schema_diff, "compare_databases", compare)
    provider.replies = [call("compareDatabases", {"pre_id": 13, "test_id": 12}, "reverse")]
    run, events = context(provider)
    with pytest.raises(BusinessError, match="direction differs"):
        await run_graph(run)
    assert pairs == [(12, 13)] and len(provider.requests) == 1
    assert not any(kind == "summary" for kind, _, _ in events)


@pytest.mark.asyncio
@pytest.mark.parametrize("when", ["before", "metadata", "observation"])
async def test_cancellation_stops_later_metadata_and_report_calls(
    provider: Provider, monkeypatch: pytest.MonkeyPatch, when: str,
) -> None:
    signal = threading.Event()
    reads: list[int] = []

    def schema(_user: int, db: int) -> dict[str, object]:
        reads.append(db)
        if when == "metadata":
            signal.set()
        return _schema("pre" if db == 12 else "test", "postgresql")

    monkeypatch.setattr(database_tools, "get_schema", schema)
    if when == "before":
        signal.set()
    run, events = context(provider, signal=signal,
                          cancel_on="compareDatabases:" if when == "observation" else None)
    with pytest.raises(RunAborted):
        await run_graph(run)
    assert reads == ([] if when == "before" else [12] if when == "metadata" else [12, 13])
    assert provider.requests == [] and run.model_stream.usage.callCount == 0
    assert not any(kind == "summary" for kind, _, _ in events)


@pytest.mark.asyncio
async def test_provider_failure_after_diff_does_not_invent_a_success_summary(
    provider: Provider, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(schema_diff, "compare_databases", lambda *_args: report())
    provider.replies = [503]
    run, events = context(provider)
    with pytest.raises(RuntimeError, match="HTTP 503"):
        await run_graph(run)
    assert len(provider.requests) == run.model_stream.usage.callCount == 1
    assert len(observations(provider, "compareDatabases")) == 1
    assert not any(kind == "summary" for kind, _, _ in events)
    assert run.tools.artifacts._items == {} and run.tools.completed_write_count == 0


@pytest.mark.asyncio
async def test_confirmed_trial_comparison_is_denied_before_preparation(
    provider: Provider, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "trial_enabled", True)
    monkeypatch.setattr(schema_diff, "compare_databases", lambda *_args: pytest.fail("Trial called diff"))
    run, _ = context(provider)
    with pytest.raises(BusinessError) as denied:
        await run_graph(run)
    assert denied.value.code == 403 and provider.requests == []
