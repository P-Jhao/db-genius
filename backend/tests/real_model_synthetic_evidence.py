"""Retain only synthetic tool observations, with all known credentials removed."""

from __future__ import annotations

import json
import math
import re

from real_model_answers import answer_review, redact_answer
from real_model_cases import EffectCase
from real_model_evidence import _answer, tool_results
from real_model_relay import object_value

SENSITIVE_FIELD = re.compile(r"password|api.?key|authorization|oss.?key|base.?url", re.IGNORECASE)


def scrub(value: object, secrets: tuple[str, ...]) -> object:
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[omitted]")
        return value
    if isinstance(value, dict):
        return {str(key): "[omitted]" if SENSITIVE_FIELD.search(str(key)) else scrub(item, secrets)
                for key, item in value.items()}
    if isinstance(value, list):
        return [scrub(item, secrets) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return {"invalidNumber": True}
    return value


def executed_tools(request: dict[str, object], secrets: tuple[str, ...]) -> list[dict[str, object]]:
    """Pair previous assistant tool arguments with actual tool observations by call ID.

    Full messages, reasoning, connection objects and headers are never retained. A
    dedicated runner explicitly enables this only for its random synthetic fixtures.
    """
    messages = request.get("messages")
    if not isinstance(messages, list):
        raise TypeError("Synthetic provider evidence requires messages")
    arguments: dict[str, dict[str, object]] = {}
    result: list[dict[str, object]] = []
    for raw in messages:
        message = object_value(raw)
        if message.get("role") == "assistant":
            calls = message.get("tool_calls", [])
            if not isinstance(calls, list):
                raise TypeError("Synthetic tool calls must be a list")
            for raw_call in calls:
                call = object_value(raw_call)
                function = object_value(call.get("function"))
                name = function.get("name")
                if name not in {"executeSql", "compareDatabases"}:
                    continue
                call_id, encoded = call.get("id"), function.get("arguments")
                if not isinstance(call_id, str) or not isinstance(encoded, str):
                    raise TypeError("Synthetic tool identity or arguments are invalid")
                args = object_value(json.loads(encoded))
                allowed = {"db_id", "statement"} if name == "executeSql" else {"pre_id", "test_id"}
                arguments[call_id] = {"toolCallId": call_id, "name": name,
                                      "arguments": {key: args[key] for key in allowed if key in args}}
        elif message.get("role") == "tool":
            call_id = message.get("tool_call_id")
            if not isinstance(call_id, str) or call_id not in arguments:
                continue
            content = message.get("content")
            if not isinstance(content, str):
                raise TypeError("Synthetic tool observation must be text")
            observation = object_value(scrub({**arguments[call_id], "result": json.loads(content)}, secrets))
            result.append(observation)
    return result


def turn_evidence(case: EffectCase, index: int, events: list[dict[str, object]],
                  secrets: tuple[str, ...]) -> dict[str, object]:
    types = [event.get("type") for event in events]
    classified = [event.get("content") for event in events if event.get("type") == "classified"]
    clarification = [event.get("content") for event in events if event.get("type") == "clarify"]
    tools = [{"name": result.name, "result": result.value} for result in tool_results(events)]
    review = answer_review(case, index, _answer(events))
    redact_answer(review, secrets, ())
    if case.expects_clarification:
        review = {"status": "validated", "finalAnswer": "", "answerTruncated": False,
                  "expectedResults": [], "parsedResults": None}
    return {
        "sse": {"eventTypes": types, "doneCount": types.count("done"), "usageCount": types.count("usage"),
                "abortedCount": types.count("aborted"), "errorCount": types.count("error"),
                "ended": bool(types) and types.count("done") == 1 and types[-1] == "done",
                "conversationIds": [event.get("content") for event in events if event.get("type") == "conversation"],
                "taskIds": sorted({str(event["taskId"]) for event in events if "taskId" in event})},
        "classification": scrub(classified, secrets), "clarification": scrub(clarification, secrets),
        "syntheticToolResults": scrub(tools, secrets), "answerReview": review,
    }


def executed_sql(provider: dict[str, object], secrets: tuple[str, ...]) -> list[dict[str, object]]:
    """Keep the first observed arguments/result pair for each executed SQL call."""
    calls = provider["calls"]
    if not isinstance(calls, list):
        raise TypeError("Expected provider calls for concrete SQL evidence")
    unique: dict[str, dict[str, object]] = {}
    for raw in calls:
        observations = object_value(raw).get("syntheticExecutedTools", [])
        if not isinstance(observations, list):
            raise TypeError("Synthetic observations must be a list")
        for raw_observation in observations:
            observation = object_value(raw_observation)
            if observation.get("name") == "executeSql":
                call_id = observation.get("toolCallId")
                if not isinstance(call_id, str):
                    raise TypeError("Concrete SQL evidence lacks tool call identity")
                unique.setdefault(call_id, object_value(scrub(observation, secrets)))
    return list(unique.values())
