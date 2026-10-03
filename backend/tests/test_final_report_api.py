"""Real LangGraph/ObservedModelStream/API terminals with mocked storage and SQL."""

import asyncio
import json
import logging
import threading

import pytest
from test_model_parameters import tool_reply
from test_model_protocol import Provider, frame, model

from app.agent.final_report import REPORT_CONTRACT
from app.agent.types import ChatRequest, Usage
from app.api import chat
from app.core.config import get_settings
from app.services import chat_store, database_tools

pytest_plugins = ["test_model_protocol"]


def final_reply(wire: str, reason: str = "stop") -> list[bytes]:
    return [frame({"usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6}}),
            frame({"choices": [{"delta": {"content": wire}}]}),
            frame({"choices": [{"delta": {}, "finish_reason": reason}]}), frame("[DONE]")]


@pytest.mark.parametrize(("wire", "reason", "expected"), [
    (json.dumps({"report": "Verified test-secret-value insert. 中文 😀", "complete": True}), "stop", "done"),
    ("## 已完成的工", "stop", "error"),
    (json.dumps({"report": "Verified insert.", "complete": True}), "length", "error"),
    (json.dumps({"report": "Before <｜DSML｜invoke>unclosed", "complete": True}), "stop", "error"),
    (json.dumps({"report": '## Done <｜DSML｜invoke name="doTerminate">'
                '<｜DSML｜parameter name="reason" string="true">done</｜DSML｜parameter>'
                '</｜DSML｜invoke>', "complete": True}), "stop", "error"),
])
@pytest.mark.asyncio
async def test_api_terminal_preserves_one_write_and_original_public_events(
    provider: Provider, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    wire: str, reason: str, expected: str,
) -> None:
    statements: list[str] = []
    finalized: list[tuple[str, str, str, dict[str, object], Usage]] = []

    def execute(_user: int, _db: int, statement: str, **_kwargs: object) -> dict[str, object]:
        statements.append(statement)
        return {"success": True, "affectedRows": 1}

    def finalize(_user: int, _conversation: int, _task: str, usage: Usage,
                 status: str, content: str, kind: str, details: dict[str, object]) -> bool:
        finalized.append((status, content, kind, details, usage))
        return True

    monkeypatch.setattr(database_tools, "get_schema", lambda *_args: {"tables": []})
    monkeypatch.setattr(database_tools, "execute_statement", execute)
    monkeypatch.setattr(chat_store, "prepare", lambda *_args: 1)
    monkeypatch.setattr(chat_store, "save", lambda *_args: None)
    monkeypatch.setattr(chat_store, "set_intent", lambda *_args: None)
    monkeypatch.setattr(chat_store, "finalize_run", finalize)
    provider.replies = [tool_reply("executeSql", {"db_id": 12, "statement": "INSERT INTO t VALUES (1)"}),
                        tool_reply("doTerminate", {"reason": "done"}), final_reply(wire, reason)]
    queue: asyncio.Queue[bytes | None] = asyncio.Queue()
    with caplog.at_level(logging.INFO, logger="app.agent.streaming"):
        await chat._produce(queue, 7, ChatRequest(message="insert", dbConfigIds=[12],
                                                confirmedIntent="sql_query"), [], "en",
                            model(provider), None, threading.Event())
    events: list[dict[str, object]] = []
    while (packet := await queue.get()) is not None:
        events.append(json.loads(packet.decode().removeprefix("data: ")))
    kinds = [event["type"] for event in events]
    assert statements == ["INSERT INTO t VALUES (1)"] and len(provider.requests) == 3
    assert len(finalized) == 1 and finalized[0][0] == expected
    assert finalized[0][3] == {"completedWriteCount": 1}
    assert finalized[0][4].callCount == 3 and finalized[0][4].totalTokens == 18
    assert kinds.count("usage") == kinds.count("done") == 1 and kinds[-1] == "done"
    assert "summary_observation" not in kinds
    usage_event = next(event["content"] for event in events if event["type"] == "usage")
    assert isinstance(usage_event, dict) and set(usage_event) == set(Usage().model_dump())
    assert "test-secret-value" not in caplog.text
    assert provider.requests[-1]["messages"][-1]["content"] == REPORT_CONTRACT
    assert all(payload["temperature"] == 0.7 and "response_format" not in payload
               for payload in provider.requests)
    if expected == "done":
        text = json.loads(wire)["report"]
        assert [event["content"] for event in events if event["type"] == "summary"] == [text]
        assert "".join(str(event["content"]) for event in events if event["type"] == "summary_delta") == text
        assert finalized[0][1:3] == (text, "summary") and "error" not in kinds
    else:
        assert "summary" not in kinds and kinds.count("error") == 1
        assert finalized[0][2] == "error"
        errors = [event["content"] for event in events if event["type"] == "error"]
        assert errors == [finalized[0][1]]
        assert str(errors[0]).startswith("The final report could not be completed.")
        assert "does not roll back completed writes" in str(errors[0])
        assert "Review the execution steps" in str(errors[0])


@pytest.mark.asyncio
async def test_api_cancellation_keeps_decoded_partial_without_replaying_write(
    provider: Provider, monkeypatch: pytest.MonkeyPatch,
) -> None:
    cancel = threading.Event()
    statements: list[str] = []
    finalized: list[tuple[str, str, str, dict[str, object], Usage]] = []
    original_frame = chat._frame

    def frame_and_cancel(task_id: str, kind: str, content: object, step: int) -> bytes:
        packet = original_frame(task_id, kind, content, step)
        if kind == "summary_delta":
            cancel.set()
        return packet

    def execute(_user: int, _db: int, statement: str, **_kwargs: object) -> dict[str, object]:
        statements.append(statement)
        return {"success": True, "affectedRows": 1}

    def finalize(_user: int, _conversation: int, _task: str, usage: Usage,
                 status: str, content: str, kind: str, details: dict[str, object]) -> bool:
        finalized.append((status, content, kind, details, usage))
        return True

    monkeypatch.setattr(database_tools, "get_schema", lambda *_args: {"tables": []})
    monkeypatch.setattr(database_tools, "execute_statement", execute)
    monkeypatch.setattr(chat_store, "prepare", lambda *_args: 1)
    monkeypatch.setattr(chat_store, "save", lambda *_args: None)
    monkeypatch.setattr(chat_store, "finalize_run", finalize)
    monkeypatch.setattr(chat, "_frame", frame_and_cancel)
    wire = '{"report":"Verified insert. '
    provider.replies = [tool_reply("executeSql", {"db_id": 12, "statement": "INSERT INTO t VALUES (1)"}),
                        tool_reply("doTerminate", {"reason": "done"}), final_reply(wire)]
    queue: asyncio.Queue[bytes | None] = asyncio.Queue()
    await chat._produce(queue, 7, ChatRequest(message="insert", dbConfigIds=[12],
                                            confirmedIntent="sql_query"), [], "en", model(provider), None, cancel)
    events: list[dict[str, object]] = []
    while (packet := await queue.get()) is not None:
        events.append(json.loads(packet.decode().removeprefix("data: ")))
    kinds = [event["type"] for event in events]
    assert statements == ["INSERT INTO t VALUES (1)"] and len(provider.requests) == 3
    assert len(finalized) == 1 and finalized[0][:3] == ("aborted", "Verified insert. ", "aborted")
    assert finalized[0][3] == {"reason": "cancelled", "completedWriteCount": 1}
    assert finalized[0][4].callCount == 3 and finalized[0][4].totalTokens == 18
    assert kinds[-1] == "aborted" and kinds.count("usage") == 1
    assert "summary" not in kinds and "done" not in kinds and "summary_observation" not in kinds


@pytest.mark.parametrize("cancel_on_prefix", [False, True])
@pytest.mark.asyncio
async def test_step_limit_prefix_matches_final_or_is_retained_on_api_cancel(
    provider: Provider, monkeypatch: pytest.MonkeyPatch, cancel_on_prefix: bool,
) -> None:
    cancel = threading.Event()
    statements: list[str] = []
    finalized: list[tuple[str, str, dict[str, object], Usage]] = []
    original_frame = chat._frame
    prefix = "Step limit reached. Unfinished work: remaining requested steps were not verified complete.\n\n"

    def frame_and_cancel(task_id: str, kind: str, content: object, step: int) -> bytes:
        packet = original_frame(task_id, kind, content, step)
        if cancel_on_prefix and kind == "summary_delta":
            cancel.set()
        return packet

    def execute(_user: int, _db: int, statement: str, **_kwargs: object) -> dict[str, object]:
        statements.append(statement)
        return {"success": True, "affectedRows": 1}

    def finalize(_user: int, _conversation: int, _task: str, usage: Usage,
                 status: str, content: str, _kind: str, details: dict[str, object]) -> bool:
        finalized.append((status, content, details, usage))
        return True

    monkeypatch.setattr(get_settings(), "sql_agent_max_steps", 1)
    monkeypatch.setattr(database_tools, "get_schema", lambda *_args: {"tables": []})
    monkeypatch.setattr(database_tools, "execute_statement", execute)
    monkeypatch.setattr(chat_store, "prepare", lambda *_args: 1)
    monkeypatch.setattr(chat_store, "save", lambda *_args: None)
    monkeypatch.setattr(chat_store, "set_intent", lambda *_args: None)
    monkeypatch.setattr(chat_store, "finalize_run", finalize)
    monkeypatch.setattr(chat, "_frame", frame_and_cancel)
    provider.replies = [tool_reply("executeSql", {"db_id": 12, "statement": "INSERT INTO t VALUES (1)"}),
                        final_reply(json.dumps({"report": "Verified insert.", "complete": True}))]
    queue: asyncio.Queue[bytes | None] = asyncio.Queue()
    await chat._produce(queue, 7, ChatRequest(message="insert", dbConfigIds=[12],
                                            confirmedIntent="sql_query"), [], "en", model(provider), None, cancel)
    events: list[dict[str, object]] = []
    while (packet := await queue.get()) is not None:
        events.append(json.loads(packet.decode().removeprefix("data: ")))
    deltas = "".join(str(event["content"]) for event in events if event["type"] == "summary_delta")
    assert statements == ["INSERT INTO t VALUES (1)"] and len(finalized) == 1
    status, content, details, usage = finalized[0]
    assert details["completedWriteCount"] == 1
    if cancel_on_prefix:
        assert len(provider.requests) == usage.callCount == 1 and usage.totalTokens == 6
        assert status == "aborted" and deltas == content == prefix
        assert events[-1]["type"] == "aborted" and not any(event["type"] == "summary" for event in events)
    else:
        assert len(provider.requests) == usage.callCount == 2 and usage.totalTokens == 12
        assert status == "done" and deltas == content == prefix + "Verified insert."
        assert [event["content"] for event in events if event["type"] == "summary"] == [content]
