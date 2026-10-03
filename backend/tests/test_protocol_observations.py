"""Offline behavior gates for actual provider, aggregation and DSML validators."""

import asyncio
import json
import re
import threading
from collections.abc import AsyncIterator
from typing import cast

import pytest
from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessageChunk, BaseMessage, HumanMessageChunk
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, SecretStr, ValidationError

from app.agent import dsml
from app.agent.cancellation import RunAborted
from app.agent.model import CompatibleChatModel
from app.agent.protocol_errors import ProtocolCode, mark, protocol_code
from app.agent.streaming import ModelStream, _collect_calls
from app.agent.types import Usage

PRIVATE = "SYNTHETIC_PROTOCOL_PRIVATE_INPUT_20261004"
USAGE = {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7}
ALLOWED = {"doTerminate": dsml.AllowedTool(frozenset({"reason"}), frozenset({"reason"}))}


def case_id(value: object) -> str:
    return value if isinstance(value, str) and re.fullmatch(r"[a-z][a-z_]+", value) else "synthetic"


def delta(value: dict[str, object], finish: object = None) -> dict[str, object]:
    return {"choices": [{"delta": value, "finish_reason": finish}]}


def call(name: str | None = "doTerminate", arguments: str = '{"reason":"done"}',
         identity: str | None = "call-safe", index: object = 0) -> dict[str, object]:
    return {"index": index, "id": identity, "function": {"name": name, "arguments": arguments}}


def wrapper(body: str = '<parameter name="reason" string="true">done</parameter>',
            name: str = "doTerminate") -> str:
    return f'<｜DSML｜tool_calls><invoke name="{name}">{body}</invoke></｜DSML｜tool_calls>'


class MemoryModel(CompatibleChatModel):
    packets: list[str]
    calls: int = 0
    yielded: int = 0
    closed: int = 0

    async def astream(self, input: LanguageModelInput, config: RunnableConfig | None = None,
                      *, stop: list[str] | None = None, **kwargs: object) -> AsyncIterator[AIMessageChunk]:
        self.calls += 1
        try:
            for packet in self.packets:
                for chunk in self._parse_packet(packet):
                    self.yielded += 1
                    assert isinstance(chunk.message, AIMessageChunk)
                    yield chunk.message
        finally:
            self.closed += 1


def memory(*packets: object) -> MemoryModel:
    return MemoryModel(base_url="https://offline.invalid", api_key=SecretStr("synthetic"),
                       model_name="synthetic", packets=[json.dumps(packet) for packet in packets])


async def forbidden_tool(reason: str) -> str:
    raise AssertionError("Protocol tests must never execute tools")


class Input(BaseModel):
    reason: str


def tools() -> list[BaseTool]:
    return [StructuredTool(name="doTerminate", description="Synthetic", args_schema=Input,
                           coroutine=forbidden_tool)]


async def discard(_kind: str, _content: object, _step: int) -> None:
    pass


def assert_observation(error: BaseException, code: str, stage: str) -> None:
    observed = protocol_code(error)
    assert type(observed) is ProtocolCode
    assert str(observed) == code
    assert observed.stage.value == stage


@pytest.mark.parametrize(("packet", "error_type", "code", "stage"), [
    ("[]", TypeError, "provider_packet_not_object", "provider_packet"),
    ('{"error":"private"}', RuntimeError, "provider_stream_error", "provider_packet"),
    ('{"usage":[]}', TypeError, "provider_usage_packet_type", "provider_usage"),
    ('{"usage":{"prompt_tokens":true,"completion_tokens":1}}', TypeError,
     "provider_usage_counts_type", "provider_usage"),
    ('{"usage":{"prompt_tokens":-1,"completion_tokens":1}}', ValueError,
     "provider_usage_values_invalid", "provider_usage"),
    (json.dumps({"choices": {}}), TypeError, "provider_choices_type", "provider_delta"),
    (json.dumps({"choices": [None]}), TypeError, "provider_choice_type", "provider_delta"),
    (json.dumps(delta({}, 1)), TypeError, "provider_finish_reason_type", "provider_delta"),
    (json.dumps(delta({"content": []})), ValueError, "provider_content_type", "provider_delta"),
    (json.dumps({**delta({"content": []}), "usage": []}), ValueError, "provider_content_type", "provider_delta"),
    (json.dumps(delta({"reasoning_content": []})), ValueError, "provider_reasoning_type", "provider_delta"),
    (json.dumps(delta({"tool_calls": {}})), ValueError, "provider_tool_calls_type", "provider_delta"),
    (json.dumps(delta({"tool_calls": [call(index=True)]})), TypeError, "provider_tool_index_type", "provider_delta"),
    (json.dumps(delta({"tool_calls": [call(index=-1)]})), ValueError, "provider_tool_index_negative", "provider_delta"),
    (json.dumps(delta({"tool_calls": [{"index": 0, "id": 1}]})), TypeError,
     "provider_tool_id_type", "provider_delta"),
    (json.dumps(delta({"tool_calls": [{"index": 0, "function": []}]})), ValueError,
     "provider_tool_function_type", "provider_delta"),
    (json.dumps(delta({"tool_calls": [{"index": 0, "function": {"name": 1}}]})), ValueError,
     "provider_tool_name_type", "provider_delta"),
    (json.dumps(delta({"tool_calls": [{"index": 0, "function": {"arguments": {}}}]})), ValueError,
     "provider_tool_arguments_type", "provider_delta"),
], ids=case_id)
def test_provider_validator_fixed_codes(packet: str, error_type: type[Exception], code: str, stage: str) -> None:
    with pytest.raises(error_type) as caught:
        CompatibleChatModel._parse_packet(packet)
    assert type(caught.value) is error_type
    assert_observation(caught.value, code, stage)


def test_json_error_and_mark_preserve_identity_type_message_and_cause() -> None:
    source = '{"' + PRIVATE + '":'
    with pytest.raises(json.JSONDecodeError) as caught:
        CompatibleChatModel._parse_packet(source)
    assert caught.value.doc == source and caught.value.__cause__ is None
    assert_observation(caught.value, "provider_packet_json_invalid", "provider_packet")
    error = ValueError(PRIVATE)
    error.__dict__["_sqlchat_protocol_code"] = "dsml_incomplete"
    assert protocol_code(error) is None
    assert mark(error, ProtocolCode.DSML_INCOMPLETE) is error and str(error) == PRIVATE
    with pytest.raises(TypeError):
        mark(error, cast(ProtocolCode, "dsml_incomplete"))


@pytest.mark.parametrize(("content", "code"), [
    (wrapper().replace('name="doTerminate"', 'name="doTerminate" name="again"'), "dsml_attribute_duplicated"),
    (wrapper().replace('string="true"', 'string="invalid"'), "dsml_string_attribute_invalid"),
    (wrapper('<parameter name="reason">NaN</parameter>'), "dsml_number_not_finite"),
    (wrapper().replace('<invoke', 'unexpected<invoke'), "dsml_invoke_sequence_invalid"),
    (wrapper(name=""), "dsml_tool_name_missing"),
    (wrapper('unexpected<parameter name="reason">done</parameter>'), "dsml_parameter_sequence_invalid"),
    (wrapper('<parameter name="">done</parameter>'), "dsml_parameter_name_invalid"),
    (wrapper('unparsed'), "dsml_parameters_invalid"),
    ('<｜DSML｜tool_calls></｜DSML｜tool_calls>', "dsml_block_invalid"),
    (wrapper() + wrapper(), "dsml_wrappers_ambiguous"),
    (wrapper() + '<｜DSML｜invoke>', "dsml_outside_wrapper"),
    ('<｜DSML｜tool_calls>', "dsml_incomplete"),
], ids=case_id)
def test_dsml_parse_fixed_codes(content: str, code: str) -> None:
    with pytest.raises(ValueError) as caught:
        dsml.parse(content)
    assert type(caught.value) is ValueError
    assert_observation(caught.value, code, "dsml_parse")


@pytest.mark.parametrize(("content", "structured", "error_type", "code"), [
    (wrapper('<parameter name="unknown">x</parameter>'), [], ValueError, "dsml_argument_unknown"),
    (wrapper('<parameter name="reason">x</parameter><parameter name="summary">y</parameter>'), [],
     ValueError, "dsml_argument_alias_conflict"),
    (wrapper(), [dsml.StructuredCall(None, None, "a"), dsml.StructuredCall(None, None, "b")],
     ValueError, "dsml_call_count_mismatch"),
    (wrapper(name=PRIVATE), [], ValueError, "dsml_tool_unknown"),
    (wrapper(), [dsml.StructuredCall("other", "{}", "a")], ValueError, "dsml_tool_name_mismatch"),
    (wrapper(), [dsml.StructuredCall("doTerminate", "{}", None)], ValueError, "dsml_structured_id_missing"),
    (wrapper(), [dsml.StructuredCall("doTerminate", "[]", "a")], TypeError,
     "dsml_structured_arguments_not_object"),
    (wrapper(), [dsml.StructuredCall("doTerminate", "{}", "a")], ValueError, "dsml_arguments_missing"),
    (wrapper(), [dsml.StructuredCall("doTerminate", '{"reason":"x","extra":"y"}', "a")], ValueError,
     "dsml_structured_argument_unknown"),
    (wrapper().replace('</｜DSML｜tool_calls>', wrapper().split('tool_calls>', 1)[1]),
     [dsml.StructuredCall(None, None, "a"), dsml.StructuredCall(None, None, "a")],
     ValueError, "dsml_ids_duplicated"),
], ids=case_id)
def test_dsml_reconcile_fixed_codes(content: str, structured: list[dsml.StructuredCall],
                                    error_type: type[Exception], code: str) -> None:
    with pytest.raises(error_type) as caught:
        dsml.reconcile(content, structured, ALLOWED)
    assert type(caught.value) is error_type
    assert_observation(caught.value, code, "dsml_reconcile")


@pytest.mark.parametrize(("packets", "error_type", "code"), [
    ([], RuntimeError, "model_stream_empty"),
    ([delta({}, "stop")], RuntimeError, "model_response_empty"),
    ([delta({"tool_calls": [call(identity=None)]})], ValueError, "tool_identity_missing"),
    ([delta({"tool_calls": [call(arguments="{")]})], ValueError, "tool_arguments_json_invalid"),
    ([delta({"tool_calls": [call(arguments="[]")]})], TypeError, "tool_arguments_not_object"),
    ([delta({"tool_calls": [call(), call(index=1)]})], ValueError, "tool_ids_duplicated"),
], ids=case_id)
@pytest.mark.asyncio
async def test_aggregation_fixed_codes_and_one_call(packets: list[object], error_type: type[Exception],
                                                   code: str) -> None:
    model, usage = memory(*packets), Usage()
    with pytest.raises(error_type) as caught:
        await ModelStream(model, discard, usage).call([])
    stage = "stream_aggregate" if code.startswith("model_") else "tool_aggregate"
    assert_observation(caught.value, code, stage)
    if code == "tool_arguments_json_invalid":
        assert type(caught.value.__cause__) is json.JSONDecodeError
    assert model.calls == model.closed == usage.callCount == 1


@pytest.mark.asyncio
async def test_valid_dsml_alias_and_malformed_structured_json_recovery() -> None:
    text = wrapper('<parameter name="summary" string="true">done</parameter>')
    for fragments in ([], [call(arguments="{")]):
        model = memory(delta({"content": text, "tool_calls": fragments}, "tool_calls"))
        result = await ModelStream(model, discard, Usage()).call([], event=None, tools=tools())
        assert len(result.tool_calls) == 1 and result.content == ""
        assert result.tool_calls[0]["args"] == {"reason": "done"}
        identity = result.tool_calls[0]["id"]
        assert isinstance(identity, str)
        assert identity == "call-safe" if fragments else identity.startswith("dsml-")
        assert model.calls == model.closed == 1


@pytest.mark.asyncio
async def test_actual_schema_validation_and_original_structured_arguments_priority() -> None:
    valid = memory(delta({"content": wrapper(), "tool_calls": [call(arguments='{"reason":"original"}')]},
                         "tool_calls"))
    result = await ModelStream(valid, discard, Usage()).call([], event=None, tools=tools())
    assert result.tool_calls == [{"name": "doTerminate", "args": {"reason": "original"},
                                  "id": "call-safe", "type": "tool_call"}]
    malformed = memory(delta({"content": wrapper(), "tool_calls": [call(arguments=json.dumps({"reason": [PRIVATE]}))]}))
    with pytest.raises(ValidationError) as caught:
        await ModelStream(malformed, discard, Usage()).call([], event=None, tools=tools())
    assert type(caught.value) is ValidationError
    assert_observation(caught.value, "tool_arguments_schema_invalid", "schema_validation")


@pytest.mark.asyncio
async def test_fragmented_identity_name_arguments_reasoning_and_duplicate_usage() -> None:
    model = memory(delta({"reasoning_content": "reasoning-", "tool_calls": [call("doTerm", '{"reason":"', "call_")]}),
                   delta({"reasoning_content": "safe", "tool_calls": [call("inate", 'finish"}', "fragment")]}),
                   delta({}, "tool_calls"), {"usage": USAGE}, {"usage": USAGE})
    usage, events = Usage(), []

    async def emit(kind: str, content: object, step: int) -> None:
        events.append((kind, content, step))
    result = await ModelStream(model, emit, usage).call([], step=2, tools=tools())
    assert result.tool_calls == [{"name": "doTerminate", "args": {"reason": "finish"},
                                  "id": "call_fragment", "type": "tool_call"}]
    assert result.additional_kwargs["reasoning_content"] == "reasoning-safe"
    assert events == [("reasoning", "reasoning-", 2), ("reasoning", "safe", 2)]
    assert (usage.promptTokens, usage.completionTokens, usage.totalTokens, usage.callCount) == (3, 4, 7, 1)
    assert model.calls == model.closed == 1


@pytest.mark.asyncio
async def test_invalid_chunk_fragment_and_summary_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(TypeError) as caught:
        _collect_calls({}, AIMessageChunk(content="", tool_call_chunks=[{"name": "x", "args": "{}",
                       "id": "a", "index": None, "type": "tool_call_chunk"}]))
    assert_observation(caught.value, "tool_fragment_index_invalid", "tool_aggregate")
    for chunk, code, final_report in [(HumanMessageChunk(content="safe"), "assistant_chunk_type", False),
        (AIMessageChunk(content='{"report":"safe","complete":true}', response_metadata={"finish_reason": 1}),
         "summary_finish_reason_type", True)]:
        async def stream(_self: MemoryModel, _messages: list[BaseMessage], _chunk: object = chunk,
                         **_kwargs: object) -> AsyncIterator[AIMessageChunk]:
            yield cast(AIMessageChunk, _chunk)

        monkeypatch.setattr(MemoryModel, "astream", stream)
        with pytest.raises(TypeError) as caught:
            await ModelStream(memory(), discard, Usage()).call([], final_report=final_report)
        assert_observation(caught.value, code, "stream_aggregate")


@pytest.mark.asyncio
async def test_cancel_closes_pending_generator_and_accounts_usage_once(monkeypatch: pytest.MonkeyPatch) -> None:
    cancel, ready, model, usage = threading.Event(), asyncio.Event(), memory(), Usage()

    async def stream(_self: MemoryModel, _messages: list[BaseMessage], **_kwargs: object) -> AsyncIterator[AIMessageChunk]:
        model.calls += 1
        try:
            chunk = CompatibleChatModel._parse_packet(json.dumps({"usage": USAGE}))[0].message
            assert isinstance(chunk, AIMessageChunk)
            yield chunk
            model.yielded += 1
            ready.set()
            await asyncio.Event().wait()
            raise AssertionError("Cancellation advanced the model stream")
        finally:
            model.closed += 1

    monkeypatch.setattr(MemoryModel, "astream", stream)
    task = asyncio.create_task(ModelStream(model, discard, usage, cancel).call([], tools=tools()))
    await asyncio.wait_for(ready.wait(), timeout=2)
    cancel.set()
    with pytest.raises(RunAborted) as caught:
        await asyncio.wait_for(task, timeout=2)
    assert caught.value.reason == "cancelled" and protocol_code(caught.value) is None
    assert model.calls == model.closed == model.yielded == usage.callCount == 1
    assert (usage.promptTokens, usage.completionTokens, usage.totalTokens) == (3, 4, 7)
