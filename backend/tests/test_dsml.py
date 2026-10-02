"""DSML recovery through the real HTTP model stream and restricted tool list."""

import json
import threading
from collections.abc import Iterator

import pytest
from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.tools import BaseTool
from test_model_protocol import Provider, frame, model

from app.agent.dsml import AllowedTool, StructuredCall, parse, reconcile, strip
from app.agent.graph import RunContext, run_graph
from app.agent.streaming import ModelStream
from app.agent.tools import RunTools
from app.agent.types import ChatRequest, Usage
from app.core.errors import BusinessError


@pytest.fixture
def provider() -> Iterator[Provider]:
    service = Provider([])
    thread = threading.Thread(target=service.serve_forever, daemon=True)
    thread.start()
    yield service
    service.shutdown()
    service.server_close()
    thread.join(timeout=2)


def _parameter(name: str, value: str, *, string: bool = False, bars: str = "｜｜") -> str:
    flag = str(string).lower()
    return (f'<{bars}DSML{bars}parameter name="{name}" string="{flag}">{value}'
            f'</{bars}DSML{bars}parameter>')


def _invoke(name: str, body: str, *, bars: str = "｜｜") -> str:
    return f'<{bars}DSML{bars}invoke name="{name}">{body}</{bars}DSML{bars}invoke>'


def _wrapper(body: str, *, bars: str = "｜｜") -> str:
    return f'<{bars}DSML{bars}tool_calls>{body}</{bars}DSML{bars}tool_calls>'


def _sql_text(*, bars: str = "｜｜", db_id: str = "12") -> str:
    return _wrapper(_invoke("executeSql", _parameter("dbConfigId", db_id, bars=bars)
                            + _parameter("sql", "SELECT 1", string=True, bars=bars), bars=bars), bars=bars)


def _reply(content: str, *, calls: list[dict[str, object]] | None = None,
           reasoning: str | None = None) -> list[bytes]:
    delta: dict[str, object] = {"content": content}
    if calls is not None:
        delta["tool_calls"] = calls
    if reasoning is not None:
        delta["reasoning_content"] = reasoning
    return [frame({"choices": [{"delta": delta}]}),
            frame({"usage": {"prompt_tokens": 3, "completion_tokens": 4}}), frame("[DONE]")]


def _tools() -> list[BaseTool]:
    request = ChatRequest.model_validate({"message": "query", "dbConfigIds": [12]})
    return RunTools(7, request).for_intent("sql_query")


def test_original_fullwidth_and_halfwidth_values_and_cleanup() -> None:
    for bars in ("｜｜", "||"):
        content = _wrapper(_invoke("demo", _parameter("text", " 42 ", string=True, bars=bars)
                                   + _parameter("number", "42", bars=bars)
                                   + _parameter("fraction", "1.25", bars=bars)
                                   + _parameter("flag", "true", bars=bars)
                                   + _parameter("fallback", "other", bars=bars), bars=bars), bars=bars)
        parsed = parse(content)
        assert parsed is not None
        calls, clean = parsed
        assert clean == ""
        assert calls[0].args == {"text": " 42 ", "number": 42, "fraction": 1.25,
                                 "flag": True, "fallback": "other"}
        assert strip(f"Before\n{content}\nAfter") == "Before\n\nAfter"
    assert strip("Answer <｜｜DSML｜") == "Answer "
    assert strip("Answer </｜｜DS") == "Answer "


@pytest.mark.asyncio
async def test_empty_structured_arguments_recovered_with_original_id_and_usage(provider: Provider) -> None:
    dsml = _sql_text()
    call = {"index": 0, "id": "call_original", "function": {"name": "executeSql", "arguments": ""}}
    packet = frame({"choices": [{"delta": {"content": dsml, "tool_calls": [call],
                                             "reasoning_content": "looking"}}]})
    provider.replies = [[packet[:11], packet[11:33], packet[33:],
                         frame({"usage": {"prompt_tokens": 3, "completion_tokens": 4}}), frame("[DONE]")],
                        _reply("Done")]
    events: list[tuple[str, object]] = []

    async def emit(kind: str, value: object, _step: int) -> None:
        events.append((kind, value))

    usage = Usage()
    stream = ModelStream(model(provider), emit, usage)
    result = await stream.call([HumanMessage(content="query")], event=None, tools=_tools())
    assert result.content == ""
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0]["id"] == "call_original"
    assert result.tool_calls[0]["args"] == {"db_id": 12, "statement": "SELECT 1"}
    assert result.additional_kwargs["reasoning_content"] == "looking"
    assert usage.totalTokens == 7
    assert events == []
    followup = await stream.call([HumanMessage(content="query"), result,
                                  ToolMessage(content="one row", tool_call_id="call_original")])
    assert followup.content == "Done"
    sent = provider.requests[1]["messages"]
    assert isinstance(sent, list)
    assert sent[1]["tool_calls"][0]["id"] == "call_original"
    assert sent[2]["tool_call_id"] == "call_original"


@pytest.mark.asyncio
async def test_unstructured_full_wrapper_recovers_only_in_tool_branch(provider: Provider) -> None:
    provider.replies = [_reply(_sql_text(bars="||")), _reply("done"), _reply(_sql_text(bars="||"))]

    async def emit(_kind: str, _value: object, _step: int) -> None:
        pass

    stream = ModelStream(model(provider), emit, Usage())
    call = await stream.call([HumanMessage(content="query")], event=None, tools=_tools())
    assert len(call.tool_calls) == 1
    recovered_id = call.tool_calls[0]["id"]
    assert isinstance(recovered_id, str)
    assert recovered_id.startswith("dsml-")
    assert call.tool_calls[0]["args"]["db_id"] == 12
    followup = await stream.call([HumanMessage(content="query"), call,
                                  ToolMessage(content="one row", tool_call_id=recovered_id)])
    assert followup.content == "done"
    sent = provider.requests[1]["messages"]
    assert isinstance(sent, list)
    assert sent[1]["tool_calls"][0]["id"] == recovered_id
    assert sent[2]["tool_call_id"] == recovered_id
    plain = await stream.call([HumanMessage(content="explain DSML")], event="content")
    assert plain.tool_calls == []
    assert "DSML" in plain.content


@pytest.mark.asyncio
async def test_code_example_and_malformed_or_unknown_do_not_execute(provider: Provider) -> None:
    example = f"Here is an example:\n```xml\n{_sql_text()}\n```\nDo not run it."
    simple_example = '<invoke name="executeSql"><parameter name="dbConfigId">12</parameter></invoke>'
    malformed = "<｜｜DSML｜｜tool_calls><｜｜DSML｜｜invoke name=\"executeSql\">broken"
    unknown = _wrapper(_invoke("deleteEverything", _parameter("db_id", "12")))
    provider.replies = [_reply(example), _reply(simple_example), _reply(malformed), _reply(unknown)]

    async def emit(_kind: str, _value: object, _step: int) -> None:
        pass

    stream = ModelStream(model(provider), emit, Usage())
    ordinary = await stream.call([HumanMessage(content="example")], event=None, tools=_tools())
    assert ordinary.tool_calls == []
    assert "executeSql" not in ordinary.content
    simple = await stream.call([HumanMessage(content="simple example")], event=None, tools=_tools())
    assert simple.tool_calls == [] and simple.content == simple_example
    with pytest.raises(ValueError, match="Incomplete DSML"):
        await stream.call([HumanMessage(content="broken")], event=None, tools=_tools())
    with pytest.raises(ValueError, match="Unknown DSML tool"):
        await stream.call([HumanMessage(content="unknown")], event=None, tools=_tools())


def test_mismatched_multiple_calls_and_duplicate_structured_call() -> None:
    first = _sql_text()
    repeated = _wrapper(_invoke("executeSql", _parameter("db_id", "12")
                                + _parameter("statement", "SELECT 1", string=True))
                        + _invoke("executeSql", _parameter("db_id", "12")
                                  + _parameter("statement", "SELECT 2", string=True)))
    structured = [StructuredCall("executeSql", json.dumps({"db_id": 12, "statement": "SELECT 1"}), "call_1")]
    allowed = {"executeSql": AllowedTool(frozenset({"db_id", "statement"}),
                                         frozenset({"db_id", "statement"}))}
    clean, calls = reconcile(first, structured, allowed)
    assert clean == "" and calls is not None and len(calls) == 1
    assert calls[0]["id"] == "call_1"
    with pytest.raises(ValueError, match="counts differ"):
        reconcile(repeated, structured, allowed)
    with pytest.raises(ValueError, match="missing required"):
        reconcile(first, [StructuredCall("executeSql", '{"db_id": 13}', "call_1")], allowed)


@pytest.mark.parametrize(("name", "legacy", "canonical", "fields"), [
    ("getDatabaseSchema", {"dbConfigId": 9}, {"db_id": 9}, {"db_id"}),
    ("readFile", {"fileId": 9}, {"file_id": 9}, {"file_id"}),
    ("readImage", {"fileId": 9}, {"file_id": 9}, {"file_id"}),
    ("compareDatabases", {"preDbConfigId": 1, "testDbConfigId": 2},
     {"pre_id": 1, "test_id": 2}, {"pre_id", "test_id"}),
    ("readToolOutput", {"artifactId": "a", "offset": 0, "limit": 100},
     {"artifact_id": "a", "offset": 0, "length": 100}, {"artifact_id", "offset", "length"}),
    ("doTerminate", {"summary": "done"}, {"reason": "done"}, {"reason"}),
])
def test_known_legacy_argument_names_are_mapped_only_for_allowed_tools(
    name: str, legacy: dict[str, object], canonical: dict[str, object], fields: set[str],
) -> None:
    body = "".join(_parameter(key, str(value), string=isinstance(value, str))
                   for key, value in legacy.items())
    content = _wrapper(_invoke(name, body))
    clean, calls = reconcile(content, [], {name: AllowedTool(frozenset(fields), frozenset(fields))})
    assert clean == "" and calls is not None
    assert calls[0]["args"] == canonical


def test_legacy_alias_conflicts_and_unknown_arguments_fail() -> None:
    allowed = {"executeSql": AllowedTool(frozenset({"db_id", "statement"}),
                                         frozenset({"db_id", "statement"}))}
    conflict = _wrapper(_invoke("executeSql", _parameter("dbConfigId", "12")
                                + _parameter("db_id", "12")
                                + _parameter("sql", "SELECT 1", string=True)))
    with pytest.raises(ValueError, match="Conflicting DSML argument"):
        reconcile(conflict, [], allowed)
    unknown = _wrapper(_invoke("executeSql", _parameter("dbConfigId", "12")
                               + _parameter("sql", "SELECT 1", string=True)
                               + _parameter("userId", "7")))
    with pytest.raises(ValueError, match="Unknown DSML argument"):
        reconcile(unknown, [], allowed)


def test_simple_invoke_requires_corresponding_structured_call() -> None:
    simple = ('<invoke name="executeSql"><parameter name="dbConfigId">12</parameter>'
              '<parameter name="sql" string="true">SELECT 1</parameter></invoke>')
    schema = {"executeSql": AllowedTool(frozenset({"db_id", "statement"}),
                                        frozenset({"db_id", "statement"}))}
    assert reconcile(simple, [], schema) == (simple, None)
    clean, calls = reconcile(simple, [StructuredCall("executeSql", "", "call_simple")], schema)
    assert clean == "" and calls is not None
    assert calls[0]["id"] == "call_simple"
    assert calls[0]["args"] == {"db_id": 12, "statement": "SELECT 1"}


@pytest.mark.asyncio
async def test_graph_executes_recovered_legacy_call_once_and_checks_selection(
    provider: Provider, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import database_tools

    executions: list[tuple[int, int, str]] = []
    monkeypatch.setattr(database_tools, "get_schema", lambda _user, _db: {"tables": [], "incomplete": False})

    def execute(user: int, db_id: int, statement: str) -> dict[str, object]:
        executions.append((user, db_id, statement))
        return {"success": True, "rowCount": 1, "data": [{"value": 1}]}

    monkeypatch.setattr(database_tools, "execute_statement", execute)

    async def emit(_kind: str, _value: object, _step: int) -> None:
        pass

    provider.replies = [_reply(_sql_text()), _reply("one row")]
    request = ChatRequest.model_validate({"message": "query", "confirmedIntent": "sql_query", "dbConfigIds": [12]})
    context = RunContext(request, [], "en", ModelStream(model(provider), emit, Usage()),
                         RunTools(7, request), emit)
    result = await run_graph(context)
    assert result["answer"] == "one row"
    assert executions == [(7, 12, "SELECT 1")]

    structured = {"index": 0, "id": "call_structured", "function": {
        "name": "executeSql", "arguments": '{"db_id":12,"statement":"SELECT 1"}',
    }}
    provider.replies = [_reply(_sql_text(), calls=[structured]), _reply("one row")]
    duplicate = RunContext(request, [], "en", ModelStream(model(provider), emit, Usage()),
                           RunTools(7, request), emit)
    assert (await run_graph(duplicate))["answer"] == "one row"
    assert executions == [(7, 12, "SELECT 1"), (7, 12, "SELECT 1")]

    provider.replies = [_reply(_sql_text(db_id="13"))]
    unauthorized = RunContext(request, [], "en", ModelStream(model(provider), emit, Usage()),
                              RunTools(7, request), emit)
    with pytest.raises(BusinessError, match="not selected"):
        await run_graph(unauthorized)
    assert executions == [(7, 12, "SELECT 1"), (7, 12, "SELECT 1")]


@pytest.mark.asyncio
async def test_summary_delta_and_final_text_hide_split_protocol(provider: Provider) -> None:
    dsml = _sql_text()
    provider.replies = [[frame({"choices": [{"delta": {"content": "Answer <"}}]}),
                         frame({"choices": [{"delta": {"content": dsml[1:25]}}]}),
                         frame({"choices": [{"delta": {"content": dsml[25:] + " after"}}]}),
                         frame("[DONE]")]]
    emitted: list[str] = []

    async def emit(kind: str, value: object, _step: int) -> None:
        if kind == "summary_delta":
            assert isinstance(value, str)
            emitted.append(value)

    result = await ModelStream(model(provider), emit, Usage()).call(
        [HumanMessage(content="summarize")], event="summary_delta",
    )
    assert result.content == "Answer  after"
    assert "".join(emitted) == "Answer  after"
    assert all("DSML" not in value and "invoke" not in value for value in emitted)
