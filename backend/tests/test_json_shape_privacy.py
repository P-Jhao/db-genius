"""Private shape identity, bounds, validation parity and observation-failure priority."""
import asyncio
import json
import logging

import pytest
from pydantic import SecretStr
from test_protocol_observation_boundary import MemoryModel

from app.agent import json_shape_diagnostics as shape
from app.agent.cancellation import RunAborted
from app.agent.final_report import ReportDecoder
from app.agent.graph import RunContext, run_graph
from app.agent.protocol_errors import ProtocolCode, protocol_code
from app.agent.streaming import ModelStream
from app.agent.tools import RunTools
from app.agent.types import ChatRequest, Classification, Usage
from app.core.config import Settings
from app.core.observability_logging import SafeLogFilter

PRIVATE = "SYNTHETIC_PRIVATE_SHAPE_DATA"


def test_number_boolean_and_text_values_are_not_diagnostics() -> None:
    first = {"intent": "sql_query", "confidence": 0.172931, "reasoning": PRIVATE, "needsClarification": False}
    second = {"intent": "workflow", "confidence": 0.982735, "reasoning": "different", "needsClarification": True}
    result = shape.safe_observe_json_shape(json.dumps(first), "classification")
    assert result == shape.safe_observe_json_shape(json.dumps(second), "classification")
    assert PRIVATE not in json.dumps(result) and "0.172931" not in json.dumps(result)
    assert shape.safe_observe_json_shape('{"report":"","complete":false}', "final_report") == shape.safe_observe_json_shape(
        '{"report":"nonempty","complete":true}', "final_report")


@pytest.mark.parametrize("wire", [" " * 65537, "[" * 65 + "0" + "]" * 65, '{"x":"' + PRIVATE + '\\q"}'],
                         ids=["size", "depth", "invalid"])
def test_adversarial_wire_is_bounded_and_private(wire: str) -> None:
    observed = shape.safe_observe_json_shape(wire, "classification")
    assert observed["syntax"] != "valid_json" and PRIVATE not in json.dumps(observed)


def test_classifier_unknown_and_duplicate_behavior_is_unchanged() -> None:
    wire = '{"intent":"workflow","intent":"simple_chat","confidence":0.9,"reasoning":"x","needsClarification":false,"extra":1}'
    value = Classification.model_validate_json(wire)
    assert value.intent == "simple_chat"
    observed = shape.safe_observe_json_shape(wire, "classification")
    assert observed["unexpectedFieldCount"] == 1 and observed["topLevelDuplicateCount"] == 1


def test_private_shape_record_preserves_fixed_structure_through_logging_filters() -> None:
    observed = shape.safe_observe_json_shape(
        json.dumps({"intent": "wrong", "confidence": 0.172931, "reasoning": PRIVATE,
                    "needsClarification": True, PRIVATE: PRIVATE}), "classification")
    row = {"code": ProtocolCode.INTENT_CLASSIFICATION_VALIDATION_FAILED.text,
           "stage": "schema_validation", "taskId": "1" * 32, "jsonShape": observed}
    prefix = "Intent classification validation "
    record = logging.makeLogRecord({"msg": prefix + json.dumps(row), "args": ()})
    boundary = SafeLogFilter(Settings.model_construct(bootstrap_password="synthetic"))
    assert boundary.filter(record) and boundary.filter(record)
    assert json.loads(record.getMessage().removeprefix(prefix)) == row
    assert PRIVATE not in record.getMessage() and "0.172931" not in record.getMessage()


@pytest.mark.parametrize("observer_result", [
    {"contract": "final_report", "syntax": "valid_json", PRIVATE: PRIVATE},
    {"contract": [PRIVATE], "syntax": "invalid_json"},
    {"contract": "final_report", "syntax": PRIVATE},
], ids=["extra-field", "bad-contract", "bad-syntax"])
@pytest.mark.parametrize("valid", [False, True])
def test_malformed_private_observer_result_cannot_change_report_validation(
    monkeypatch: pytest.MonkeyPatch, observer_result: dict[str, object], valid: bool,
) -> None:
    monkeypatch.setattr(shape, "observe_json_shape", lambda *_: observer_result)
    decoder = ReportDecoder()
    decoder.push(json.dumps({"report": "verified", "complete": valid}))
    result = decoder.finish("stop", 0)
    assert result.error == (None if valid else "invalid_report_envelope")
    assert result.observation["jsonShape"]["syntax"] == "unobserved_diagnostic_failure"
    assert PRIVATE not in json.dumps(result.observation)


@pytest.mark.parametrize("reason,calls,expected", [("stop", 0, "invalid_report_envelope"),
    ("length", 0, "provider_length"), ("length", 1, "unexpected_summary_tool_call")])
def test_observer_fault_cannot_override_report_error_priority(
    monkeypatch: pytest.MonkeyPatch, reason: str, calls: int, expected: str,
) -> None:
    def fail(*_args: object) -> dict[str, object]:
        raise RuntimeError(PRIVATE)

    monkeypatch.setattr(shape, "observe_json_shape", fail)
    decoder = ReportDecoder()
    decoder.push('{"report":"verified","complete":false}')
    result = decoder.finish(reason, calls)
    assert result.error == expected and result.observation["envelopeIssue"] == "completion_not_true"
    assert result.observation["jsonShape"] == {"contract": "final_report", "syntax": "unobserved_diagnostic_failure", "diagnosticError": "other"}
    assert PRIVATE not in json.dumps(result.observation)


@pytest.mark.parametrize("error", [RunAborted("cancelled"), asyncio.CancelledError()])
def test_diagnostic_wrapper_preserves_cancellation(monkeypatch: pytest.MonkeyPatch, error: BaseException) -> None:
    def abort(*_args: object) -> dict[str, object]:
        raise error

    monkeypatch.setattr(shape, "observe_json_shape", abort)
    with pytest.raises(type(error)):
        shape.safe_observe_json_shape("{}", "classification")


async def invalid_classifier(wire: str, task_id: str | None) -> tuple[BaseException, list[str], Usage, MemoryModel]:
    model = MemoryModel(base_url="http://unused.invalid", api_key=SecretStr("synthetic"), model_name="memory",
        packets=[json.dumps({"choices": [{"delta": {"content": wire}}]}),
                 json.dumps({"usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}})])
    events: list[str] = []

    async def emit(kind: str, _content: object, _step: int) -> None:
        events.append(kind)

    request, usage = ChatRequest(message="question"), Usage()
    context = RunContext(request, [], "en", ModelStream(model, emit, usage), RunTools(7, request), emit,
                         task_id=task_id)
    with pytest.raises(ValueError, match="Invalid intent classification JSON") as caught:
        await run_graph(context)
    assert str(caught.value) == "Invalid intent classification JSON"
    assert protocol_code(caught.value) is ProtocolCode.INTENT_CLASSIFICATION_VALIDATION_FAILED
    assert usage.callCount == 1 and model.calls == 1 and events == ["classifying"]
    return caught.value, events, usage, model


@pytest.mark.asyncio
async def test_concurrent_classification_diagnostics_keep_task_identity(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="app.agent.graph")
    await asyncio.gather(invalid_classifier("not JSON " + PRIVATE, "1" * 32),
                         invalid_classifier('{"intent":"wrong"}', "2" * 32))
    prefix = "Intent classification validation "
    rows = [json.loads(record.getMessage().removeprefix(prefix)) for record in caplog.records
            if record.name == "app.agent.graph" and record.getMessage().startswith(prefix)]
    assert {row["taskId"]: row["jsonShape"]["syntax"] for row in rows} == {"1" * 32: "invalid_json", "2" * 32: "valid_json"}
    assert PRIVATE not in caplog.text and all(row["code"] == "intent_classification_validation_failed" for row in rows)


@pytest.mark.asyncio
async def test_diagnostic_fault_keeps_original_classification_failure_and_unknown_task(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    def fail(*_args: object) -> dict[str, object]:
        raise ValueError(PRIVATE)

    monkeypatch.setattr(shape, "observe_json_shape", fail)
    caplog.set_level(logging.INFO, logger="app.agent.graph")
    error, _, _, _ = await invalid_classifier("invalid", None)
    assert error.__cause__ is not None and PRIVATE not in str(error)
    prefix = "Intent classification validation "
    row = next(json.loads(record.getMessage().removeprefix(prefix)) for record in caplog.records
               if record.name == "app.agent.graph" and record.getMessage().startswith(prefix))
    assert row["taskId"] is None and row["jsonShape"]["diagnosticError"] == "ValueError"
