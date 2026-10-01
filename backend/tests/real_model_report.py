"""Numeric provider aggregation and strict comparison gates for S15 reports."""

from __future__ import annotations

import json
from collections import Counter
from statistics import median

from real_model_relay import object_value


def _count(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise TypeError("Evidence counts must be nonnegative integers")
    return value


def _duration(value: object) -> float | None:
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
        raise TypeError("Evidence durations must be nonnegative numbers")
    return float(value)


def _turns(row: dict[str, object]) -> list[dict[str, object]]:
    raw = row.get("turns", [])
    if not isinstance(raw, list):
        raise TypeError("Expected a list of turn reports")
    return [object_value(turn) for turn in raw]


def provider_summary(records: list[dict[str, object]]) -> dict[str, object]:
    usages = [object_value(row["usage"]) for row in records if row.get("usage") is not None]
    totals = {key: sum(_count(usage[key]) for usage in usages)
              for key in ("prompt_tokens", "completion_tokens", "total_tokens")}
    return {"modelCallCount": len(records), "knownUsageCallCount": len(usages),
            "usage": totals if len(usages) == len(records) and records else None,
            "calls": records}


def application_usage(events: list[dict[str, object]], provider: dict[str, object]) -> dict[str, object]:
    usage_events = [object_value(event["content"]) for event in events if event.get("type") == "usage"]
    if len(usage_events) != 1:
        return {"usage": None, "usageMatchesProvider": False}
    raw = usage_events[0]
    safe: dict[str, object] = {}
    for key in ("promptTokens", "completionTokens", "totalTokens", "callCount"):
        value = raw.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise TypeError("Application usage must contain nonnegative integer counts")
        safe[key] = value
    expected = provider["usage"]
    agrees = None if expected is None else all(
        safe[app_key] == object_value(expected)[provider_key] for app_key, provider_key in (
            ("promptTokens", "prompt_tokens"), ("completionTokens", "completion_tokens"),
            ("totalTokens", "total_tokens"),
        )) and safe["callCount"] == provider["modelCallCount"]
    return {"usage": safe, "usageMatchesProvider": agrees}


def parameter_profiles(turn: dict[str, object]) -> set[str]:
    provider = object_value(turn["provider"])
    calls = provider["calls"]
    if not isinstance(calls, list):
        raise TypeError("Expected actual provider calls")
    return {json.dumps(object_value(call)["parameters"], sort_keys=True) for call in calls}


def pair_comparison(left: dict[str, object], right: dict[str, object]) -> dict[str, object]:
    if left.get("scope") != "paired" or right.get("scope") != "paired":
        return {"status": "environment-blocked", "errorType": "OriginalOssUnavailable", "sameParameters": None}
    left_turns, right_turns = left.get("turns"), right.get("turns")
    if not isinstance(left_turns, list) or not isinstance(right_turns, list):
        raise TypeError("Expected turn evidence from both variants")
    if len(left_turns) != len(right_turns) or not left_turns:
        return {"status": "failed", "errorType": "IncompletePair", "sameParameters": False}
    aligned = all(parameter_profiles(object_value(a)) == parameter_profiles(object_value(b))
                  and bool(parameter_profiles(object_value(a)))
                  for a, b in zip(left_turns, right_turns, strict=True))
    if not aligned:
        return {"status": "not-comparable", "errorType": "GenerationParameterMismatch", "sameParameters": False}
    passed = left.get("status") == right.get("status") == "passed"
    if (all(row.get("status") in {"passed", "review-required"} for row in (left, right))
            and any(row.get("status") == "review-required" for row in (left, right))):
        return {"status": "review-required", "errorType": "GroundedAnswerReviewRequired", "sameParameters": True}
    return {"status": "passed" if passed else "failed", "errorType": None if passed else "VariantFailed",
            "sameParameters": True}


def aggregate(rows: list[dict[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for variant in ("java", "python"):
        selected = [row for row in rows if row.get("variant") == variant]
        turns = [turn for row in selected for turn in _turns(row)]
        elapsed = [duration for turn in turns if (duration := _duration(turn.get("elapsedSeconds"))) is not None]
        first = [duration for turn in turns if (duration := _duration(turn.get("firstVisibleSeconds"))) is not None]
        providers = [object_value(turn["provider"]) for turn in turns if "provider" in turn]
        calls = [object_value(call) for provider in providers for call in _calls(provider)]
        usages = [object_value(call["usage"]) for call in calls if call.get("usage") is not None]
        result[variant] = {
            "caseCount": len(selected), "statuses": dict(Counter(str(row["status"]) for row in selected)),
            "turnCount": len(turns), "totalSecondsMedian": median(elapsed) if elapsed else None,
            "totalSecondsMax": max(elapsed) if elapsed else None,
            "firstVisibleSecondsMedian": median(first) if first else None,
            "modelCallCount": sum(_count(provider["modelCallCount"]) for provider in providers),
            "knownUsageCallCount": sum(_count(provider["knownUsageCallCount"]) for provider in providers),
            "unknownUsageCallCount": len(calls) - len(usages),
            "knownTokenTotals": {key: sum(_count(usage[key]) for usage in usages)
                                 for key in ("prompt_tokens", "completion_tokens", "total_tokens")},
            "toolCallCount": sum(_count(turn.get("toolCallCount", 0)) for turn in turns),
            "toolSuccessCount": sum(_count(turn.get("toolSuccessCount", 0)) for turn in turns),
            "oracleCount": sum(_count(turn.get("oracleCount", 0)) for turn in turns),
            "passedOracleCount": sum(_count(turn.get("passedOracleCount", 0)) for turn in turns),
            "validatedAnswerCount": sum(object_value(turn["answerReview"])["status"] == "validated"
                                        for turn in turns if "answerReview" in turn),
        }
    return result


def _calls(provider: dict[str, object]) -> list[object]:
    raw = provider["calls"]
    if not isinstance(raw, list):
        raise TypeError("Expected provider call records")
    return raw
