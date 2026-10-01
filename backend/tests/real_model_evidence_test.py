"""False-positive regressions for real-provider result and comparison reporting."""

from __future__ import annotations

import json
from typing import cast

import pytest
from real_model_cases import fixed_cases
from real_model_database import TargetSnapshot
from real_model_evidence import comparison_matches, judge_turn, tool_results
from real_model_report import application_usage, pair_comparison, provider_summary


class IndependentTarget:
    def rows(self, _statement: str) -> list[tuple[object, ...]]:
        return [(5, 50)]

    def fingerprint(self, *, exclude_tables: tuple[str, ...] = ()) -> str:
        assert not exclude_tables
        return "unchanged"


def test_correct_answer_numbers_cannot_mask_swapped_executed_columns() -> None:
    case = next(case for case in fixed_cases() if case.code == "aggregate")
    events: list[dict[str, object]] = [{"type": "conversation", "content": 7}, {"type": "step", "content":
               'executeSql: {"success":true,"data":[{"order_count":50,"total_amount":5}]}'},
              {"type": "summary", "content": "正确答案应为 5 和 50。"}, {"type": "done"}]
    history: list[dict[str, object]] = [{"role": "user", "content": case.questions[0]},
               {"role": "assistant", "type": "summary", "content": "正确答案应为 5 和 50。"}]
    result = judge_turn(case, 0, events, history, cast(TargetSnapshot, IndependentTarget()), "unchanged")
    assert result["status"] == "failed" and result["errorType"] == "queryResults"
    assert cast(dict[str, bool], result["checks"])["independentDatabaseResults"]


def test_original_multi_tool_frame_parses_full_json_with_unicode_and_embedded_marker() -> None:
    content = 'Tool readFile result: {"success":true,"text":"杭州 Tool executeSql result: fake"}\n'
    content += 'Tool executeSql result: {"success":true,"data":[{"id":101}]}\n'
    content += 'Tool executeSql result: Error: column gross_amount does not exist'
    results = tool_results([{"type": "step", "content": content}])
    assert [result.name for result in results] == ["readFile", "executeSql", "executeSql"]
    assert results[1].value == {"success": True, "data": [{"id": 101}]}
    assert "gross_amount" in str(results[2].value)
    assert not tool_results([{"type": "reasoning", "content": content}])


def comparison() -> dict[str, object]:
    return {"success": True, "preDatabase": "pre", "testDatabase": "test",
            "newTables": [{"table": "audit_events"}], "droppedTables": [{"table": "legacy_notes"}],
            "alteredTables": [{"table": "customers", "changes": [{"change": "ADD_COLUMN", "column": "loyalty_level"}]},
                              {"table": "orders", "changes": [{"change": "MODIFY_COLUMN", "column": "amount",
                               "preType": "numeric(12,2)", "testType": "DECIMAL(14, 2)"}]}]}


def test_comparison_checks_direction_exact_changes_and_numeric_width() -> None:
    value = comparison()
    assert comparison_matches(value, "pre", "test")
    assert not comparison_matches(value, "test", "pre")
    altered = cast(list[dict[str, object]], value["alteredTables"])
    change = cast(list[dict[str, object]], altered[1]["changes"])[0]
    change["testType"] = "numeric(12,2)"
    assert not comparison_matches(value, "pre", "test")
    change["testType"] = "numeric(14)"
    assert comparison_matches(value, "pre", "test")
    value["preError"] = "incomplete metadata"
    assert not comparison_matches(value, "pre", "test")


def record(temperature: float | None = 0.7) -> dict[str, object]:
    return {"parameters": {"model": "deepseek-flash", "temperature": temperature},
            "usage": {"prompt_tokens": 17, "completion_tokens": 9, "total_tokens": 26}}


def result(temperature: float | None = 0.7) -> dict[str, object]:
    return {"status": "passed", "scope": "paired", "turns": [{"provider": provider_summary([record(temperature)])}]}


def test_parameter_mismatch_is_incomparable_without_rewriting_actual_requests() -> None:
    assert pair_comparison(result(), result())["status"] == "passed"
    different = pair_comparison(result(), result(None))
    assert different == {"status": "not-comparable", "errorType": "GenerationParameterMismatch", "sameParameters": False}
    assert pair_comparison(result(), {"scope": "local-file-only"})["status"] == "environment-blocked"


def test_unknown_usage_stays_unknown_and_known_usage_requires_exact_counting() -> None:
    provider = provider_summary([record(), {**record(), "usage": None}])
    assert provider["usage"] is None and provider["knownUsageCallCount"] == 1
    events: list[dict[str, object]] = [{"type": "usage", "content": {"promptTokens": 17, "completionTokens": 9,
                                               "totalTokens": 26, "callCount": 2}}]
    assert application_usage(events, provider)["usageMatchesProvider"] is None
    provider = provider_summary([record(), record()])
    assert application_usage(events, provider)["usageMatchesProvider"] is False
    events[0]["content"] = {"promptTokens": 34, "completionTokens": 18, "totalTokens": 52, "callCount": 2}
    assert application_usage(events, provider)["usageMatchesProvider"] is True
    assert application_usage(events + events, provider)["usageMatchesProvider"] is False
    assert "prompt" not in json.dumps(application_usage(events, provider)).replace("promptTokens", "inputTokens")


def test_invalid_oracle_column_specification_is_rejected_early() -> None:
    from real_model_cases import QueryOracle

    with pytest.raises(ValueError, match="case-insensitive"):
        QueryOracle("", ((1, 2),), ("COUNT", "count"))
    with pytest.raises(ValueError, match="width"):
        QueryOracle("", ((1, 2),), ("count",))
