"""Database observation cannot change adapter calls, data, or cancellation truth."""

from unittest.mock import Mock

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from test_observability_lifecycle import one

from app.adapters.cancellation import DatabaseExecutionInterrupted, DatabaseWriteOutcomeUnknown
from app.core.observability_metrics import REGISTRY
from app.core.observability_runtime import observe_database

pytest_plugins = ["test_observability_lifecycle"]


@pytest.mark.parametrize("result,outcome", [({"success": True}, "done"),
    ({"success": False, "error": "SYNTHETIC_PRIVATE_BODY"}, "error"),
    ({"incomplete": True, "errorMessage": "SYNTHETIC_PRIVATE_BODY"}, "partial")])
def test_full_result_is_returned_and_observed_once(result: dict[str, object], outcome: str,
    spans: InMemorySpanExporter,
) -> None:
    body = Mock(return_value=result)
    before = REGISTRY.get_sample_value("sqlchat_database_calls_total", {"operation": "schema", "outcome": outcome})
    assert observe_database("schema")(body)("synthetic-argument") is result
    body.assert_called_once_with("synthetic-argument")
    record = one(spans, "database.schema")
    assert record.attributes == {"outcome": outcome} and not record.events
    assert REGISTRY.get_sample_value("sqlchat_database_calls_total", {"operation": "schema", "outcome": outcome}) == \
        (0 if before is None else before) + 1


@pytest.mark.parametrize("reason,unknown,outcome", [("timeout", False, "timeout"),
    ("cancelled", False, "cancelled"), ("cancelled", True, "write_outcome_unknown")])
def test_interrupts_preserve_exact_exception(reason: str, unknown: bool, outcome: str,
    spans: InMemorySpanExporter,
) -> None:
    assert reason in {"cancelled", "timeout"}
    error = DatabaseExecutionInterrupted("timeout" if reason == "timeout" else "cancelled",
        cancel_request_sent=False, server_termination_confirmed=False, write_outcome_unknown=unknown)
    body = Mock(side_effect=error)
    with pytest.raises(DatabaseExecutionInterrupted) as caught:
        observe_database("execute")(body)()
    assert caught.value is error and body.call_count == 1
    record = one(spans, "database.execute")
    assert record.attributes == {"outcome": outcome, "error.type": "DatabaseExecutionInterrupted"}
    assert not record.events


@pytest.mark.parametrize("error,outcome", [(TimeoutError("SYNTHETIC_PRIVATE_BODY"), "timeout"),
    (DatabaseWriteOutcomeUnknown("SYNTHETIC_PRIVATE_BODY"), "write_outcome_unknown")])
def test_timeout_and_unknown_commit_are_not_generic_success(error: Exception, outcome: str,
    spans: InMemorySpanExporter,
) -> None:
    body = Mock(side_effect=error)
    with pytest.raises(type(error)) as caught:
        observe_database("execute")(body)()
    assert caught.value is error and body.call_count == 1
    record = one(spans, "database.execute")
    assert record.attributes == {"outcome": outcome, "error.type": type(error).__name__}
    assert not record.events
