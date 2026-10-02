"""Small, fixed-label Prometheus surface for chat and its dependencies."""

from pathlib import Path

from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Histogram, generate_latest

from app.core.config import get_settings
from app.core.observability_multiprocess import ServiceMetricsCollector

REGISTRY = CollectorRegistry(auto_describe=True)

RUNS = Counter("sqlchat_chat_runs_total", "Terminal chat runs", ("outcome",), registry=REGISTRY)
RUN_DURATION = Histogram("sqlchat_chat_duration_seconds", "Chat run duration", ("outcome",),
                         registry=REGISTRY)
FIRST_CHUNK = Histogram("sqlchat_chat_first_chunk_seconds", "First visible model chunk latency",
                        registry=REGISTRY)
MODEL_CALLS = Counter("sqlchat_model_calls_total", "Model calls", ("outcome",), registry=REGISTRY)
MODEL_TOKENS = Counter("sqlchat_model_tokens_total", "Provider-reported model tokens", ("kind",),
                       registry=REGISTRY)
TOOLS = Counter("sqlchat_tool_calls_total", "Agent tool calls", ("tool", "outcome"), registry=REGISTRY)
DATABASE = Counter("sqlchat_database_calls_total", "Target database calls", ("operation", "outcome"),
                   registry=REGISTRY)
PERSISTENCE = Counter("sqlchat_persistence_total", "Chat persistence calls", ("operation", "outcome"),
                      registry=REGISTRY)
INTERRUPTIONS = Counter("sqlchat_chat_interruptions_total", "Chat interruption reasons", ("reason",),
                        registry=REGISTRY)
LOOP_STOPS = Counter("sqlchat_chat_loop_stops_total", "Agent loop stop reasons", ("reason",),
                     registry=REGISTRY)

QUEUE = Counter("sqlchat_queue_publications_total", "Verification publications", ("outcome",), registry=REGISTRY)
VERIFICATION = Counter("sqlchat_verifications_total", "Verification callbacks", ("outcome",), registry=REGISTRY)

_OUTCOMES = frozenset({"done", "error", "aborted", "timeout", "cancelled", "partial", "stale", "write_outcome_unknown"})
_TOOLS = frozenset({"getDatabaseSchema", "executeSql", "readFile", "readImage", "readToolOutput",
                    "doTerminate", "compareDatabases"})
_DATABASE_OPS = frozenset({"schema", "execute"})
_PERSISTENCE_OPS = frozenset({"prepare", "save", "set_intent", "finalize"})


def _fixed(value: str, allowed: frozenset[str]) -> str:
    return value if value in allowed else "other"


def metrics_text() -> tuple[bytes, str]:
    root = get_settings().metrics_multiprocess_root
    if root:
        registry = CollectorRegistry(auto_describe=False)
        registry.register(ServiceMetricsCollector(Path(root)))
    else:
        registry = REGISTRY
    return generate_latest(registry), CONTENT_TYPE_LATEST


def run_finished(outcome: str, duration_seconds: float) -> None:
    label = _fixed(outcome, _OUTCOMES)
    RUNS.labels(label).inc()
    RUN_DURATION.labels(label).observe(max(0.0, duration_seconds))


def first_chunk(seconds: float) -> None:
    FIRST_CHUNK.observe(max(0.0, seconds))


def model_call(outcome: str, prompt: int, completion: int) -> None:
    MODEL_CALLS.labels(_fixed(outcome, _OUTCOMES)).inc()
    if prompt > 0:
        MODEL_TOKENS.labels("prompt").inc(prompt)
    if completion > 0:
        MODEL_TOKENS.labels("completion").inc(completion)


def tool_call(name: str, outcome: str) -> None:
    TOOLS.labels(_fixed(name, _TOOLS), _fixed(outcome, _OUTCOMES)).inc()


def database_call(operation: str, outcome: str) -> None:
    DATABASE.labels(_fixed(operation, _DATABASE_OPS), _fixed(outcome, _OUTCOMES)).inc()


def persistence_call(operation: str, outcome: str) -> None:
    PERSISTENCE.labels(_fixed(operation, _PERSISTENCE_OPS), _fixed(outcome, _OUTCOMES)).inc()


def interrupted(reason: str) -> None:
    INTERRUPTIONS.labels(_fixed(reason, frozenset({"cancelled", "timeout", "write_outcome_unknown"}))).inc()


def loop_stopped(reason: str | None) -> None:
    if reason is None:
        return
    label = ("repeated" if "Repeated" in reason else
             "step_limit" if "Step limit" in reason else
             "tool_failure" if "succeed" in reason else "other")
    LOOP_STOPS.labels(label).inc()


def queue_call(outcome: str) -> None:
    QUEUE.labels(_fixed(outcome, _OUTCOMES)).inc()


def verification_finished(outcome: str) -> None:
    VERIFICATION.labels(_fixed(outcome, _OUTCOMES)).inc()


def result_outcome(value: object) -> str:
    if isinstance(value, dict):
        if value.get("success") is False:
            return "error"
        if value.get("incomplete") is True:
            return "partial"
    return "done"
