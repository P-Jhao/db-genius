"""Known model windows bound server preparation without invented AI steps."""

import json

import pytest
from compare_preflight_helpers import complete_preparation_estimates, context
from real_model_evidence import tool_results
from test_compare_graph import answer, call
from test_compare_risk_guidance import report
from test_model_protocol import Provider

from app.agent.context_runtime import _estimated_tokens
from app.agent.graph import run_graph
from app.core.config import get_settings
from app.services import database_tools, schema_diff

pytest_plugins = ["test_model_protocol"]


def configure_large_diff(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    observed = report()
    observed["preSchema"] = {"databaseName": "current", "details": "α" * 9000}
    observed["testSchema"] = {"databaseName": "desired", "details": "β" * 9000}
    monkeypatch.setattr(schema_diff, "compare_databases", lambda *_args, **_kwargs: observed)
    monkeypatch.setattr(get_settings(), "tool_output_per_tool_max_characters",
                        {"compareDatabases": 4000, "readToolOutput": 4000})
    return observed


def read_pages(events: list[tuple[str, object, int]]) -> tuple[str, dict[str, object], int]:
    parsed = tool_results([{"type": kind, "content": content} for kind, content, _ in events])
    assert parsed[0].name == "compareDatabases"
    text = ""
    last: dict[str, object] = {}
    for item in parsed[1:]:
        assert item.name == "readToolOutput" and isinstance(item.value, dict)
        page = item.value
        assert page["offset"] == len(text) and isinstance(page["content"], str)
        text += page["content"]
        assert page["nextOffset"] == len(text) and isinstance(page["totalCharacters"], int)
        assert isinstance(page["hasMore"], bool) and page["hasMore"] == (len(text) < page["totalCharacters"])
        last = page
    assert last
    return text, last, len(parsed)


@pytest.mark.asyncio
async def test_small_known_context_large_diff_stops_without_oversized_report_request(
    provider: Provider, monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_large_diff(monkeypatch)
    provider.replies = [answer("The complete comparison is ready.")]
    run, events = context(provider)
    run.model_stream.usage.contextWindow = 4096
    result = await run_graph(run)
    estimated = None
    if provider.requests:
        messages = provider.requests[0]["messages"]
        assert isinstance(messages, list)
        estimated = sum((len(str(message["content"])) + 3) // 4 + 12 for message in messages)
    print(json.dumps({"knownContextWindow": 4096, "firstRequestEstimatedTokens": estimated,
                      "providerRequests": len(provider.requests), "steps": result["step"]}))
    assert provider.requests == [], f"First report request estimated {estimated} tokens for known 4096 window"
    assert run.model_stream.usage.callCount == 0
    assert "context budget" in result["answer"] and "No directly executable migration SQL" in result["answer"]
    assert not any(kind == "summary_delta" for kind, _, _ in events)
    assert run.tools.artifacts._items == {} and run.tools.completed_write_count == 0


@pytest.mark.asyncio
async def test_unknown_window_keeps_existing_step_and_output_limits_without_guessing(
    provider: Provider, monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_large_diff(monkeypatch)
    provider.replies = [answer("The actual observed comparison is ready for manual review.")]
    run, _ = context(provider)
    assert run.model_stream.usage.contextWindow is None
    result = await run_graph(run)
    assert result["answer"].startswith("The actual observed comparison")
    assert result["step"] == 6 and len(provider.requests) == run.model_stream.usage.callCount == 1
    assert _estimated_tokens(result["messages"]) > 4096


@pytest.mark.asyncio
async def test_full_preparation_that_fits_known_budget_preserves_all_model_evidence(
    provider: Provider, monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_large_diff(monkeypatch)
    provider.replies = [answer("The full observed comparison is ready for manual review.")]
    run, events = context(provider)
    run.model_stream.usage.contextWindow = 16384
    result = await run_graph(run)
    assert result["answer"].startswith("The full observed comparison")
    assert len(provider.requests) == run.model_stream.usage.callCount == 1
    assert _estimated_tokens(result["messages"]) < 16384 * get_settings().observation_elision_threshold
    parsed = tool_results([{"type": kind, "content": content} for kind, content, _ in events])
    assert [item.name for item in parsed] == ["compareDatabases", *["readToolOutput"] * 5]
    assert result["step"] == 6


@pytest.mark.asyncio
@pytest.mark.parametrize("elide,summary,elide_threshold,summary_threshold", [
    (False, False, 0.6, 0.8),
    (False, True, 0.6, 0.8),
    (True, False, 0.6, 0.8),
    (True, True, 0.6, 0.8),
])
async def test_governance_trigger_thresholds_do_not_reject_preparation_that_fits_known_window(
    provider: Provider, monkeypatch: pytest.MonkeyPatch,
    elide: bool, summary: bool, elide_threshold: float, summary_threshold: float,
) -> None:
    configure_large_diff(monkeypatch)
    settings = get_settings()
    for name, value in {"observation_elision_enabled": elide, "step_summary_enabled": summary,
        "observation_elision_threshold": elide_threshold, "step_summary_threshold": summary_threshold}.items():
        monkeypatch.setattr(settings, name, value)
    provider.replies = [answer("Complete observed comparison.")]
    run, _ = context(provider)
    run.model_stream.usage.contextWindow = 8192
    result = await run_graph(run)
    assert len(provider.requests) == run.model_stream.usage.callCount == 1
    estimated = _estimated_tokens(result["messages"])
    assert 8192 * max(elide_threshold, summary_threshold) < estimated < 8192
    assert result["answer"] == "Complete observed comparison."


@pytest.mark.asyncio
async def test_context_limit_after_all_pages_were_read_reports_capacity_instead_of_unread_pages(
    provider: Provider, monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed = configure_large_diff(monkeypatch)
    estimates = await complete_preparation_estimates(provider)
    run, events = context(provider)
    # Admit the last page, then stop before the report decision; prompt growth does
    # not change this case into an earlier stop with unread evidence.
    window = estimates[-2] + 1
    run.model_stream.usage.contextWindow = window
    result = await run_graph(run)
    assert "context budget" in result["answer"] and "truncated" not in result["answer"]
    assert "incomplete" not in result["answer"] and provider.requests == []
    text, page, observations = read_pages(events)
    assert text == json.dumps(observed, ensure_ascii=False, allow_nan=False)
    assert page["hasMore"] is False and page["nextOffset"] == page["totalCharacters"]
    assert result["step"] == observations == len(estimates) == 6
    assert _estimated_tokens(result["messages"]) == estimates[-1] >= window
    assert run.model_stream.usage.callCount == 0 and events[-1] == ("summary", result["answer"], 6)
    assert "no report model reviewed the full evidence" in result["answer"]


@pytest.mark.asyncio
async def test_context_limit_equal_to_penultimate_input_keeps_unread_last_page_truncated(
    provider: Provider, monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed = configure_large_diff(monkeypatch)
    estimates = await complete_preparation_estimates(provider)
    run, events = context(provider)
    window = estimates[-2]
    run.model_stream.usage.contextWindow = window
    result = await run_graph(run)
    text, page, observations = read_pages(events)
    expected = json.dumps(observed, ensure_ascii=False, allow_nan=False)
    assert expected.startswith(text) and len(text) < len(expected)
    end, total = page["nextOffset"], page["totalCharacters"]
    assert page["hasMore"] is True and isinstance(end, int) and isinstance(total, int) and end < total
    assert result["step"] == observations == len(estimates) - 1 == 5
    assert _estimated_tokens(result["messages"]) == window
    assert "context budget" in result["answer"] and "truncated" in result["answer"]
    assert "no report model reviewed the full evidence" in result["answer"] and "incomplete" not in result["answer"]
    assert provider.requests == [] and run.model_stream.usage.callCount == 0
    assert events[-1] == ("summary", result["answer"], 5)


@pytest.mark.asyncio
async def test_first_summary_at_step_limit_checks_its_actual_expanded_model_input(
    provider: Provider, monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_large_diff(monkeypatch)
    monkeypatch.setattr(get_settings(), "compare_agent_max_steps", 6)
    provider.replies = [answer("The full comparison is ready.")]
    run, events = context(provider)
    run.model_stream.usage.contextWindow = 7300
    result = await run_graph(run)
    estimated = None
    if provider.requests:
        messages = provider.requests[0]["messages"]
        assert isinstance(messages, list)
        estimated = sum((len(str(message["content"])) + 3) // 4 + 12 for message in messages)
    print(json.dumps({"summaryKnownWindow": 7300, "summaryRequestEstimatedTokens": estimated,
                      "providerRequests": len(provider.requests), "steps": result["step"]}))
    assert provider.requests == [], f"Expanded first summary estimated {estimated} for known 7300 window"
    assert "context budget" in result["answer"] and "truncated" not in result["answer"]
    assert result["step"] == 6 and run.model_stream.usage.callCount == 0
    parsed = tool_results([{"type": kind, "content": content} for kind, content, _ in events])
    last = parsed[-1].value
    assert isinstance(last, dict) and last["hasMore"] is False


@pytest.mark.asyncio
async def test_later_compare_decision_checks_preparation_plus_new_observations(
    provider: Provider, monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_large_diff(monkeypatch)
    monkeypatch.setattr(database_tools, "get_schema", lambda *_args:
                        {"dbType": "postgresql", "tables": [], "notes": "z" * 3800})
    provider.replies = [call("getDatabaseSchema", {"db_id": 12}, "metadata"),
                        answer("A full reviewed report.")]
    run, events = context(provider)
    run.model_stream.usage.contextWindow = 8192
    result = await run_graph(run)
    assert "context budget" in result["answer"] and "truncated" not in result["answer"]
    assert len(provider.requests) == run.model_stream.usage.callCount == 1
    assert result["step"] == 7
    parsed = tool_results([{"type": kind, "content": content} for kind, content, _ in events])
    assert parsed[-1].name == "getDatabaseSchema" and run.tools.completed_write_count == 0


@pytest.mark.asyncio
async def test_context_limit_on_untruncated_diff_does_not_claim_metadata_or_paging_failure(
    provider: Provider, monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed = configure_large_diff(monkeypatch)
    monkeypatch.setattr(get_settings(), "tool_output_per_tool_max_characters",
                        {"compareDatabases": 20000, "readToolOutput": 4000})
    run, events = context(provider)
    run.model_stream.usage.contextWindow = 4096
    result = await run_graph(run)
    assert "context budget" in result["answer"]
    assert "truncated" not in result["answer"] and "incomplete" not in result["answer"]
    assert provider.requests == [] and result["step"] == 1
    parsed = tool_results([{"type": kind, "content": content} for kind, content, _ in events])
    assert len(parsed) == 1 and parsed[0].value == observed
    assert observed["success"] is True and observed["complete"] is True


@pytest.mark.asyncio
async def test_invalid_known_window_is_explicit_instead_of_using_a_fallback(
    provider: Provider, monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_large_diff(monkeypatch)
    run, events = context(provider)
    run.model_stream.usage.contextWindow = 0
    with pytest.raises(ValueError, match="Context window must be positive"):
        await run_graph(run)
    assert provider.requests == [] and run.tools.artifacts._items == {}
    assert not any(kind == "summary" for kind, _, _ in events)


@pytest.mark.asyncio
@pytest.mark.parametrize("locale,phrase", [
    ("en", "context budget"), ("zh-CN", "模型上下文预算"), ("zh-TW", "模型上下文預算"),
    ("es", "presupuesto de contexto"), ("fr", "budget de contexte"),
    ("ja", "コンテキスト予算"), ("ms", "bajet konteks"),
])
async def test_context_capacity_limit_is_explicit_in_each_product_language(
    provider: Provider, monkeypatch: pytest.MonkeyPatch, locale: str, phrase: str,
) -> None:
    configure_large_diff(monkeypatch)
    run, events = context(provider)
    run.locale = locale
    run.model_stream.usage.contextWindow = 4096
    result = await run_graph(run)
    assert phrase in result["answer"] and provider.requests == []
    assert events[-1][0:2] == ("summary", result["answer"])
    assert run.model_stream.usage.callCount == 0 and run.tools.artifacts._items == {}
