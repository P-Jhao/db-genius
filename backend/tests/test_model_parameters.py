"""Capture actual HTTP payloads for each caller's original model parameters."""

import json
import threading

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from test_chat_graph import response
from test_model_protocol import Provider, frame, model

from app.agent import context_runtime
from app.agent.cancellation import RunAborted
from app.agent.graph import RunContext, RunState, run_graph
from app.agent.graph_sql import SQLNodes
from app.agent.streaming import ModelStream
from app.agent.tools import RunTools
from app.agent.types import ChatRequest, Usage
from app.core.config import Settings
from app.models import Message
from app.services import context_compress, database_tools

pytest_plugins = ["test_chat_api"]


async def emit(_kind: str, _content: object, _step: int) -> None:
    pass


def assert_parameters(payload: dict[str, object], *, classification: bool = False) -> None:
    assert "top_p" not in payload
    assert "max_tokens" not in payload
    assert "response_format" not in payload
    if classification:
        assert payload["thinking"] == {"type": "disabled"}
        assert "temperature" not in payload
    else:
        assert payload["temperature"] == 0.7
        assert "thinking" not in payload
    assert payload["stream"] is True
    assert payload["stream_options"] == {"include_usage": True}


def tool_reply(name: str, arguments: dict[str, object]) -> list[bytes]:
    return [frame({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": name,
        "function": {"name": name, "arguments": json.dumps(arguments)}}]}}]}),
        frame({"usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6}}),
        frame("[DONE]")]


@pytest.mark.asyncio
async def test_classification_then_simple_answer_have_separate_parameters(provider: Provider) -> None:
    provider.replies = [response(json.dumps({"intent": "simple_chat", "confidence": 0.96,
        "reasoning": "general", "needsClarification": False})), response("The answer is 42.")]
    request = ChatRequest(message="What is 42?")
    usage = Usage()
    result = await run_graph(RunContext(request, [], "en", ModelStream(model(provider), emit, usage),
                                       RunTools(7, request), emit))
    assert result["answer"] == "The answer is 42."
    assert len(provider.requests) == 2
    assert_parameters(provider.requests[0], classification=True)
    assert_parameters(provider.requests[1])
    assert (usage.callCount, usage.promptTokens, usage.completionTokens, usage.totalTokens) == (2, 8, 4, 12)
    assert "needsClarification" in json.dumps(provider.requests[0]["messages"])


@pytest.mark.parametrize("invalid_json", [
    "not json", '{"intent":"execute_everything"}',
    '{"intent":"simple_chat","confidence":2,"reasoning":"general","needsClarification":false}',
])
@pytest.mark.asyncio
async def test_classifier_still_validates_provider_text(provider: Provider, invalid_json: str) -> None:
    provider.replies = [response(invalid_json)]
    request = ChatRequest(message="question")
    usage = Usage()
    with pytest.raises(ValueError, match="Invalid intent classification JSON"):
        await run_graph(RunContext(request, [], "en", ModelStream(model(provider), emit, usage),
                                   RunTools(7, request), emit))
    assert len(provider.requests) == 1
    assert_parameters(provider.requests[0], classification=True)
    assert (usage.callCount, usage.totalTokens) == (1, 6)


@pytest.mark.asyncio
async def test_sql_tool_followup_and_final_summary_use_ordinary_parameters(
    provider: Provider, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(database_tools, "get_schema", lambda _user, _db: {"tables": []})
    statements: list[str] = []

    def execute(_user: int, _db: int, statement: str) -> dict[str, object]:
        statements.append(statement)
        return {"success": True, "rowCount": 1, "data": [{"value": 1}]}

    monkeypatch.setattr(database_tools, "execute_statement", execute)
    provider.replies = [tool_reply("executeSql", {"db_id": 12, "statement": "SELECT 1"}),
                        tool_reply("doTerminate", {"reason": "Done"}),
                        response(json.dumps({"report": "The value is 1.", "complete": True}))]
    request = ChatRequest(message="Select one", dbConfigIds=[12], confirmedIntent="sql_query")
    usage = Usage()
    result = await run_graph(RunContext(request, [], "en", ModelStream(model(provider), emit, usage),
                                       RunTools(7, request), emit))
    assert result["answer"] == "The value is 1."
    assert statements == ["SELECT 1"]
    assert len(provider.requests) == 3
    for payload in provider.requests:
        assert_parameters(payload)
    assert "tools" in provider.requests[0] and "tools" in provider.requests[1]
    assert "tools" not in provider.requests[2]
    followup = provider.requests[1]["messages"]
    assert isinstance(followup, list)
    assert any(item["role"] == "tool" and item["tool_call_id"] == "executeSql"
               and json.loads(item["content"])["data"] == [{"value": 1}] for item in followup)
    assert (usage.callCount, usage.totalTokens) == (3, 18)


@pytest.mark.asyncio
async def test_execution_step_summary_uses_ordinary_parameters(
    provider: Provider, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(context_runtime, "get_settings", lambda: Settings(
        observation_elision_enabled=False, step_summary_threshold=0.01, step_summary_keep_last_steps=1,
    ))
    provider.replies = [response("Earlier query returned 1."), tool_reply("doTerminate", {"reason": "Done"})]
    request = ChatRequest(message="Query", dbConfigIds=[12], confirmedIntent="sql_query")
    usage = Usage(contextWindow=1000)
    tools = RunTools(7, request)
    messages: list[BaseMessage] = [HumanMessage(content="Query")]
    for index in range(2):
        messages.extend([AIMessage(content="", tool_calls=[{"name": "executeSql", "args": {},
            "id": str(index)}]), ToolMessage(content='{"success":true,"data":[{"value":1}]}',
                                            tool_call_id=str(index))])
    state: RunState = {"messages": messages, "intent": "sql_query", "clarification": None, "step": 2,
                       "decision": None, "answer": "", "finished": False}
    try:
        result = await SQLNodes(RunContext(request, [], "en", ModelStream(model(provider), emit, usage),
                                           tools, emit), 10).decide(state)
    finally:
        tools.close()
    assert "Earlier query returned 1." in str(result["messages"])
    assert len(provider.requests) == 2
    assert_parameters(provider.requests[0])
    assert_parameters(provider.requests[1])
    assert "tools" not in provider.requests[0] and "tools" in provider.requests[1]
    assert (usage.callCount, usage.totalTokens) == (2, 12)


@pytest.mark.parametrize("automatic", [False, True])
@pytest.mark.asyncio
async def test_manual_and_automatic_context_summary_parameters(provider: Provider, automatic: bool) -> None:
    provider.replies = [response("Earlier conversation summarized.")]
    configured = model(provider)
    usage = Usage()
    stream = ModelStream(configured, emit, usage) if automatic else None
    rows = [Message(conversation_id=1, role="user", content="Earlier question", type="user", step=0)]
    summary = await context_compress._summarize(configured, rows, None, "en", stream)
    assert summary == "Earlier conversation summarized."
    assert len(provider.requests) == 1
    assert_parameters(provider.requests[0])
    if automatic:
        assert (usage.callCount, usage.totalTokens) == (1, 6)


@pytest.mark.asyncio
async def test_model_transport_has_no_global_parameter_defaults(provider: Provider) -> None:
    provider.replies = [response("Direct transport.")]
    chunks = [chunk async for chunk in model(provider).astream([HumanMessage(content="Transport")])]
    assert "Direct transport." in "".join(str(chunk.content) for chunk in chunks)
    assert set(provider.requests[0]) == {"model", "messages", "stream", "stream_options"}


@pytest.mark.asyncio
async def test_classification_http_error_preserves_unknown_usage(provider: Provider) -> None:
    provider.replies = [503]
    request = ChatRequest(message="question")
    usage = Usage()
    with pytest.raises(RuntimeError, match="503"):
        await run_graph(RunContext(request, [], "en", ModelStream(model(provider), emit, usage),
                                   RunTools(7, request), emit))
    assert_parameters(provider.requests[0], classification=True)
    assert (usage.callCount, usage.totalTokens) == (1, 0)


@pytest.mark.parametrize("reported_usage", [False, True])
@pytest.mark.asyncio
async def test_answer_cancellation_preserves_partial_text_and_usage(
    provider: Provider, reported_usage: bool,
) -> None:
    provider.replies = [[
        *([frame({"usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6}})]
          if reported_usage else []),
        frame({"choices": [{"delta": {"content": "partial"}}]}), frame("[DONE]"),
    ]]
    cancellation = threading.Event()

    async def cancel(kind: str, _content: object, _step: int) -> None:
        if kind == "content":
            cancellation.set()

    usage = Usage()
    stream = ModelStream(model(provider), cancel, usage, cancellation)
    with pytest.raises(RunAborted):
        await stream.call([HumanMessage(content="question")])
    assert_parameters(provider.requests[0])
    assert stream.partial == "partial"
    assert (usage.callCount, usage.totalTokens) == (1, 6 if reported_usage else 0)
