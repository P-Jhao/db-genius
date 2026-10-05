"""Real logging and producer boundaries, with synthetic model and storage only."""

import asyncio
import importlib
import io
import json
import logging
import socket
import threading
from collections.abc import AsyncIterator, Iterator

import httpx
import pytest
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatGenerationChunk
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, SecretStr
from sqlalchemy.engine import Engine

from app.agent.model import CompatibleChatModel
from app.agent.protocol_errors import ProtocolCode, protocol_code
from app.agent.types import ChatRequest, Usage
from app.core import config
from app.core import observability_logging as safe_logging
from app.services.chat_records import ReplayRecord

PRIVATE = "SYNTHETIC_PROTOCOL_BOUNDARY_PRIVATE_20261004"
WRAPPER = ('<｜DSML｜tool_calls><invoke name="doTerminate">'
           '<parameter name="reason" string="true">done</parameter></invoke></｜DSML｜tool_calls>')
USAGE = {"usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7}}
type Capture = tuple[logging.Logger, io.StringIO, list[logging.LogRecord]]


def reject_external_access(*_args: object, **_kwargs: object) -> object:
    raise AssertionError("Offline protocol boundary attempted external access")


@pytest.fixture
def isolated_import(monkeypatch: pytest.MonkeyPatch) -> None:
    # model_construct bypasses BaseSettings' environment/.env loading entirely.
    settings = config.Settings.model_construct(database_url="sqlite+pysqlite:///:memory:",
                                               bootstrap_password="synthetic", default_model_api_key="")
    monkeypatch.setattr(config, "get_settings", lambda: settings)
    monkeypatch.setattr(Engine, "connect", reject_external_access)
    monkeypatch.setattr(Engine, "raw_connection", reject_external_access)
    monkeypatch.setattr(socket, "create_connection", reject_external_access)
    monkeypatch.setattr(httpx.AsyncClient, "send", reject_external_access)
    monkeypatch.setattr(httpx.Client, "send", reject_external_access)
    importlib.import_module("app.api.chat")


@pytest.fixture
def capture_logging(monkeypatch: pytest.MonkeyPatch) -> Iterator[Capture]:
    settings = config.Settings.model_construct(bootstrap_password="synthetic")
    local_filter = safe_logging.SafeLogFilter(settings)
    previous = logging.getLogRecordFactory()
    monkeypatch.setattr(safe_logging, "_record_filter", local_filter)
    logging.setLogRecordFactory(safe_logging.record_factory(logging.LogRecord))
    stream, records = io.StringIO(), []

    class Handler(logging.StreamHandler[io.StringIO]):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)
            super().emit(record)

    logger = logging.getLogger("synthetic.protocol.boundary")
    previous_level, previous_propagate = logger.level, logger.propagate
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    handler = Handler(stream)
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler.addFilter(local_filter)
    handler.addFilter(safe_logging.SafeLogFilter(settings))
    logger.addHandler(handler)
    try:
        yield logger, stream, records
    finally:
        logger.removeHandler(handler)
        handler.close()
        logger.setLevel(previous_level)
        logger.propagate = previous_propagate
        logging.setLogRecordFactory(previous)


def test_production_factory_filters_getmessage_formatter_and_repeated_redaction(capture_logging: Capture) -> None:
    logger, stream, records = capture_logging
    from app.agent.dsml import parse

    with pytest.raises(ValueError) as caught:
        parse(WRAPPER.replace('name="doTerminate"', 'name="doTerminate" name="' + PRIVATE + '"'))
    code = protocol_code(caught.value)
    assert code is ProtocolCode.DSML_ATTRIBUTE_DUPLICATED
    logger.error("typed code=%s stage=%s input=%s error=%s", code, code.stage, PRIVATE, caught.value,
                 exc_info=(type(caught.value), caught.value, caught.value.__traceback__), stack_info=True,
                 extra={"privateInput": PRIVATE, "headers": {"Authorization": PRIVATE},
                        "payload": {"prompt": PRIVATE}, "token": PRIVATE})
    logger.error("plain code=%s stage=%s input=%s", code.text, code.stage.value, PRIVATE)
    typed, plain = stream.getvalue().splitlines()
    assert "code=dsml_attribute_duplicated stage=dsml_parse" in typed and "ValueError" in typed
    assert "dsml_attribute_duplicated" not in plain and "dsml_parse" not in plain
    assert PRIVATE not in typed + plain
    for record in records:
        first = record.getMessage()
        assert isinstance(record, safe_logging.SafeRecord)
        assert record.getMessage() == first and PRIVATE not in logging.Formatter().format(record)
        assert record.exc_info is record.exc_text is record.stack_info is None
    assert records[0].__dict__["privateInput"] == "[redacted]"
    assert PRIVATE not in str({key: records[0].__dict__[key] for key in ("headers", "payload", "token")})


class MemoryModel(CompatibleChatModel):
    packets: list[str]
    calls: int = 0
    yielded: int = 0
    closed: int = 0

    async def _astream(self, messages: list[BaseMessage], stop: list[str] | None = None,
                       run_manager: object = None, **kwargs: object) -> AsyncIterator[ChatGenerationChunk]:
        self.calls += 1
        try:
            for packet in self.packets:
                for chunk in self._parse_packet(packet):
                    self.yielded += 1
                    yield chunk
        finally:
            self.closed += 1


class Input(BaseModel):
    reason: str


async def forbidden_tool(reason: str) -> str:
    raise AssertionError("The protocol producer test must never execute a tool")


class PreparedTools:
    completed_write_count = 0
    loop_stop_reason = None
    interruption = None
    closed = 0

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        pass

    def close(self) -> None:
        self.closed += 1


@pytest.mark.parametrize(("mode", "expected_code", "stage"), [
    ("success", None, None),
    ("json_failure", "tool_arguments_json_invalid", "tool_aggregate"),
    ("post_write_failure", "tool_arguments_json_invalid", "tool_aggregate"),
    ("dsml_failure", "dsml_tool_unknown", "dsml_reconcile"),
    ("schema_failure", "tool_arguments_schema_invalid", "schema_validation"),
    ("unclassified_value_error", None, None),
    ("system_failure", None, None),
    ("config_failure", None, None),
    ("cancelled", None, None),
])
@pytest.mark.asyncio
async def test_actual_producer_public_terminal_persistence_and_accounting(
    isolated_import: None, capture_logging: Capture, monkeypatch: pytest.MonkeyPatch,
    mode: str, expected_code: str | None, stage: str | None,
) -> None:
    from app.agent.graph import RunContext
    from app.api import chat
    from app.core import observability_runtime as runtime

    cancel, queue = threading.Event(), asyncio.Queue[bytes | None]()
    logger, log_stream, _records = capture_logging
    operations: list[str] = []
    saved: list[tuple[object, ...]] = []
    finalized: list[tuple[str, str, str, dict[str, object], Usage]] = []
    model_metrics: list[tuple[str, int, int]] = []
    run_metrics: list[str] = []
    persistence_metrics: list[tuple[str, str]] = []
    instances: list[PreparedTools] = []

    class Tools(PreparedTools):
        completed_write_count = 2 if mode == "post_write_failure" else 0

        def __init__(self, *_args: object, **_kwargs: object) -> None:
            instances.append(self)

    def prepare(*_args: object) -> int:
        operations.append("prepare")
        return 123

    def save(*args: object) -> None:
        operations.append("save")
        saved.append(args)

    def finalize(_user: int, _conversation: int, _task: str, usage: Usage,
                 status: str, content: str, kind: str, details: dict[str, object],
                 records: list[ReplayRecord] | None = None) -> bool:
        operations.append("finalize")
        finalized.append((status, content, kind, details, usage.model_copy(deep=True)))
        return True

    arguments = '{"reason":"done"}'
    content = WRAPPER if mode == "schema_failure" else "safe"
    if mode in {"json_failure", "post_write_failure"}:
        arguments = '{"' + PRIVATE + '":'
    elif mode == "schema_failure":
        arguments = json.dumps({"reason": [PRIVATE]})
    elif mode == "dsml_failure":
        content = WRAPPER.replace("doTerminate", PRIVATE)
    packets: list[object] = [USAGE, {"choices": [{"delta": {"content": content, "tool_calls": [
        {"index": 0, "id": "call-safe", "function": {"name": "doTerminate", "arguments": arguments}}]},
        "finish_reason": "tool_calls"}]}]
    if mode == "cancelled":
        packets = [USAGE, {"choices": [{"delta": {"content": "safe partial"}}]},
                   {"choices": [{"delta": {"content": "must not advance"}}]}]
    model = MemoryModel(base_url="https://offline.invalid", api_key=SecretStr("synthetic"),
                        model_name="synthetic", packets=[json.dumps(packet) for packet in packets])
    tool = StructuredTool(name="doTerminate", description="Synthetic", args_schema=Input, coroutine=forbidden_tool)

    async def graph(context: RunContext) -> dict[str, object]:
        assert isinstance(context.model_stream, runtime.ObservedModelStream)
        if mode == "system_failure":
            raise RuntimeError(PRIVATE)
        if mode == "unclassified_value_error":
            raise ValueError(PRIVATE)
        if mode == "config_failure":
            from app.agent.model import completion_url
            completion_url(PRIVATE)
        await context.model_stream.call([], event="content" if mode == "cancelled" else None, tools=[tool])
        await context.emit("summary", "safe complete", 1)
        return {"intent": None, "clarification": None, "answer": "safe complete"}

    original_frame = chat._frame

    def frame(task: str, kind: str, value: object, step: int) -> bytes:
        result = original_frame(task, kind, value, step)
        if mode == "cancelled" and kind == "content":
            cancel.set()
        return result

    monkeypatch.setattr(chat, "logger", logger)
    monkeypatch.setattr(chat, "RunTools", Tools)
    monkeypatch.setattr(chat, "run_graph", graph)
    monkeypatch.setattr(chat, "_frame", frame)
    monkeypatch.setattr(chat.chat_store, "prepare", prepare)
    monkeypatch.setattr(chat.chat_store, "save", save)
    monkeypatch.setattr(chat.chat_store, "finalize_run", finalize)
    monkeypatch.setattr(chat.chat_store, "set_intent", reject_external_access)
    monkeypatch.setattr(runtime, "model_call", lambda outcome, prompt, completion:
                        model_metrics.append((outcome, prompt, completion)))
    monkeypatch.setattr(runtime, "run_finished", lambda outcome, _duration: run_metrics.append(outcome))
    monkeypatch.setattr(runtime, "persistence_call", lambda operation, outcome:
                        persistence_metrics.append((operation, outcome)))
    body = ChatRequest(message="safe request", confirmedIntent="db_compare", preDbConfigId=1, testDbConfigId=2,
                       conversationId=None, dbConfigIds=None, fileIds=None)
    await chat._produce(queue, 1, body, [], "zh-CN", model, None, cancel)
    events: list[dict[str, object]] = []
    while (wire := await queue.get()) is not None:
        events.append(json.loads(wire.decode().removeprefix("data: ")))
    kinds = [event["type"] for event in events]
    assert queue.empty() and kinds[0] == "conversation"
    assert operations == ["prepare", "save", "finalize"]
    assert persistence_metrics == [(operation, "done") for operation in operations]
    assert len(finalized) == len(instances) == instances[0].closed == 1
    status = "done" if mode == "success" else "aborted" if mode == "cancelled" else "error"
    assert finalized[0][0] == status and run_metrics == [status]
    assert finalized[0][3] == ({"reason": "cancelled", "completedWriteCount": 0} if mode == "cancelled"
                              else {"completedWriteCount": 2 if mode == "post_write_failure" else 0})
    called = mode not in {"system_failure", "unclassified_value_error", "config_failure"}
    assert model.calls == model.closed == finalized[0][4].callCount == int(called)
    expected_usage = Usage(promptTokens=3 * int(called), completionTokens=4 * int(called),
                           totalTokens=7 * int(called), contextTokens=3 * int(called), callCount=int(called))
    assert finalized[0][4].model_dump() == expected_usage.model_dump()
    assert next(event["content"] for event in events if event["type"] == "usage") == expected_usage.model_dump()
    assert model_metrics == ([("done" if mode == "success" else "cancelled" if mode == "cancelled" else "error", 3, 4)]
                             if called else [])
    assert kinds.count("usage") == 1
    terminal = (["usage", "aborted"] if mode == "cancelled" else ["usage", "done"] if mode == "success"
                else ["usage", "error", "done"])
    assert kinds[-len(terminal):] == terminal
    assert kinds.count("done") == int(mode != "cancelled") and kinds.count("error") == int(status == "error")
    if mode == "cancelled":
        assert model.yielded == 2 and finalized[0][1:3] == ("safe partial", "aborted")
    elif mode == "success":
        assert [event["content"] for event in events if event["type"] == "summary"] == ["safe complete"]
        assert finalized[0][1:3] == ("safe complete", "summary")
    elif status == "error":
        public = next(event["content"] for event in events if event["type"] == "error")
        assert finalized[0][1:3] == (public, "error")
        if mode != "system_failure":
            assert public == "模型返回了无效响应。"
    output = json.dumps(events) + repr(saved) + repr(finalized) + log_stream.getvalue()
    assert PRIVATE not in output
    assert ("protocolCode=" in log_stream.getvalue()) is (expected_code is not None)
    if expected_code is not None:
        assert f"protocolCode={expected_code} protocolStage={stage}" in log_stream.getvalue()
    with pytest.raises(RuntimeError, match="active producer"):
        runtime.accounting()
