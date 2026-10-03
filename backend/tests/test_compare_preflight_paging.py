"""Scoped output paging, budgets, corrupt pages, and cancellation in preparation."""

import json
import threading

import pytest
from compare_preflight_helpers import context, observations
from real_model_evidence import tool_results
from test_compare_graph import answer
from test_compare_risk_guidance import report
from test_model_protocol import Provider

from app.agent.cancellation import RunAborted
from app.agent.graph import run_graph
from app.agent.output_guard import OutputArtifacts
from app.core import observability_runtime
from app.core.config import get_settings
from app.core.errors import BusinessError
from app.services import schema_diff

pytest_plugins = ["test_model_protocol"]


def large_report(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    observed = report()
    observed["preSchema"] = {"databaseName": "current", "details": "α" * 1700}
    observed["testSchema"] = {"databaseName": "desired", "details": "β" * 1700}
    monkeypatch.setattr(schema_diff, "compare_databases", lambda *_args, **_kwargs: observed)
    monkeypatch.setattr(get_settings(), "tool_output_per_tool_max_characters",
                        {"compareDatabases": 800, "readToolOutput": 800})
    return observed


@pytest.mark.asyncio
async def test_all_matching_pages_are_read_before_plain_answer_with_bounded_observations(
    provider: Provider, monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed = large_report(monkeypatch)
    audit: list[tuple[str, str]] = []
    monkeypatch.setattr(observability_runtime, "tool_call", lambda name, outcome: audit.append((name, outcome)))
    provider.replies = [answer("The complete observed comparison is ready for manual SQL review.")]
    run, events = context(provider)
    result = await run_graph(run)
    assert result["answer"].startswith("The complete observed comparison")
    assert len(provider.requests) == run.model_stream.usage.callCount == 1
    initial = observations(provider, "compareDatabases")
    assert len(initial) == 1 and len(initial[0]) <= 800
    assert json.loads(initial[0])["marker"] == "[TRUNCATED:TOOL_OUTPUT_TOO_LONG]"
    pages = observations(provider, "readToolOutput")
    assert len(pages) > 1 and all(len(page) <= 800 for page in pages)
    offset = 0
    content = ""
    for output in pages:
        page = json.loads(output)
        assert page["offset"] == offset
        offset = page["nextOffset"]
        content += page["content"]
    expected = json.dumps(observed, ensure_ascii=False, allow_nan=False)
    assert content == expected and offset == len(expected)
    assert json.loads(pages[-1])["hasMore"] is False
    assert result["step"] == 1 + len(pages)
    assert audit == [("compareDatabases", "done"), *[("readToolOutput", "done")] * len(pages)]
    assert [step for kind, _, step in events if kind == "step"] == list(range(1, 2 + len(pages)))
    parsed = tool_results([{"type": kind, "content": value} for kind, value, _ in events])
    assert parsed[0].name == "compareDatabases" and parsed[0].value == observed
    assert [result.name for result in parsed[1:]] == ["readToolOutput"] * len(pages)
    assert [result.value for result in parsed[1:]] == [json.loads(page) for page in pages]
    assert run.tools.artifacts._items == {} and run.tools.completed_write_count == 0


@pytest.mark.asyncio
async def test_incomplete_paging_at_step_limit_uses_safe_report_without_model(
    provider: Provider, monkeypatch: pytest.MonkeyPatch,
) -> None:
    large_report(monkeypatch)
    monkeypatch.setattr(get_settings(), "compare_agent_max_steps", 2)
    provider.replies = [answer("All changes are reliable; deploy now.")]
    run, events = context(provider)
    result = await run_graph(run)
    assert result["step"] == 2
    assert "truncated" in result["answer"] and "No directly executable migration SQL" in result["answer"]
    assert provider.requests == [] and run.model_stream.usage.callCount == 0
    assert sum(kind == "step" for kind, _, _ in events) == 2
    assert run.tools.artifacts._items == {}


@pytest.mark.asyncio
async def test_output_capacity_that_cannot_fit_page_preserves_truncated_safe_report(
    provider: Provider, monkeypatch: pytest.MonkeyPatch,
) -> None:
    large_report(monkeypatch)
    monkeypatch.setattr(get_settings(), "tool_output_per_tool_max_characters",
                        {"compareDatabases": 800, "readToolOutput": 1})
    run, _ = context(provider)
    result = await run_graph(run)
    assert "truncated" in result["answer"] and "No directly executable migration SQL" in result["answer"]
    assert result["step"] == 2 and provider.requests == []
    assert run.tools.artifacts._items == {}


@pytest.mark.asyncio
async def test_artifact_capacity_failure_is_explicit_and_does_not_call_provider(
    provider: Provider, monkeypatch: pytest.MonkeyPatch,
) -> None:
    large_report(monkeypatch)
    monkeypatch.setattr(get_settings(), "tool_artifact_max_per_task", 1)
    run, events = context(provider)
    run.tools.artifacts.add("existing task observation")
    with pytest.raises(BusinessError, match="capacity exceeded"):
        await run_graph(run)
    assert provider.requests == [] and run.tools.artifacts._items == {}
    assert not any(kind == "summary" for kind, _, _ in events)


@pytest.mark.asyncio
@pytest.mark.parametrize("corruption", ["content", "offset", "hasMore"])
async def test_invalid_or_discontinuous_page_cannot_authorize_a_report(
    provider: Provider, monkeypatch: pytest.MonkeyPatch, corruption: str,
) -> None:
    large_report(monkeypatch)
    original = OutputArtifacts.read

    def corrupted(self: OutputArtifacts, artifact_id: str, **kwargs: object) -> str:
        page = json.loads(original(self, artifact_id, **kwargs))
        if corruption == "content":
            page["content"] = "x" + page["content"][1:]
        elif corruption == "offset":
            page["offset"] += 1
        else:
            page["hasMore"] = False
        return json.dumps(page, ensure_ascii=False)

    monkeypatch.setattr(OutputArtifacts, "read", corrupted)
    run, events = context(provider)
    with pytest.raises(ValueError, match="authoritative result|requested range"):
        await run_graph(run)
    assert provider.requests == [] and run.tools.artifacts._items == {}
    assert not any(kind == "summary" for kind, _, _ in events)


@pytest.mark.asyncio
async def test_page_cancellation_stops_next_page_and_all_provider_work(
    provider: Provider, monkeypatch: pytest.MonkeyPatch,
) -> None:
    large_report(monkeypatch)
    signal = threading.Event()
    run, events = context(provider, signal=signal, cancel_on="readToolOutput:")
    with pytest.raises(RunAborted):
        await run_graph(run)
    assert provider.requests == [] and run.tools.artifacts._items == {}
    pages = [content for kind, content, _ in events if kind == "step" and str(content).startswith("readToolOutput:")]
    assert len(pages) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("wrong_identity", ["user", "task"])
async def test_scoped_artifact_read_does_not_bypass_existing_authorization(
    provider: Provider, monkeypatch: pytest.MonkeyPatch, wrong_identity: str,
) -> None:
    large_report(monkeypatch)
    original = OutputArtifacts.read

    def wrong(self: OutputArtifacts, artifact_id: str, **kwargs: object) -> str:
        kwargs["user_id" if wrong_identity == "user" else "task_id"] = -1 if wrong_identity == "user" else "other"
        return original(self, artifact_id, **kwargs)

    monkeypatch.setattr(OutputArtifacts, "read", wrong)
    run, events = context(provider)
    with pytest.raises(BusinessError, match="not part of this task"):
        await run_graph(run)
    assert provider.requests == [] and run.tools.artifacts._items == {}
    assert not any(kind == "summary" for kind, _, _ in events)
