"""SQL graph nodes with bounded observations and explicit loop termination."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage

from app.agent.cancellation import check_cancelled
from app.agent.context_runtime import RepeatedCalls, govern_messages, summary_request
from app.agent.prompts import system_prompt
from app.core.errors import BusinessError

if TYPE_CHECKING:
    from app.agent.graph import RunContext, RunState


class SQLNodes:
    def __init__(self, context: RunContext, max_steps: int) -> None:
        self.context = context
        self.max_steps = max_steps
        self.repeated_calls = RepeatedCalls()

    async def prepare(self, state: RunState) -> dict[str, object]:
        context = self.context
        check_cancelled(context.cancel_event)
        intent = state["intent"]
        if intent != "sql_query":
            raise BusinessError(501, f"{intent} workflow is scheduled for a later phase")
        schemas: list[str] = []
        for db_id in context.request.db_config_ids or []:
            check_cancelled(context.cancel_event)
            schema = await context.tools.schema(db_id)
            schemas.append(f"Database {db_id} schema:\n{schema}")
            await context.emit("step", f"Read schema for database {db_id}", 0)
        messages: list[BaseMessage] = [
            SystemMessage(content=system_prompt(intent, context.request, context.locale)),
            *context.history, SystemMessage(content="\n\n".join(schemas)),
            HumanMessage(content=context.request.message),
        ]
        return {"messages": messages}

    async def decide(self, state: RunState) -> dict[str, object]:
        context = self.context
        check_cancelled(context.cancel_event)
        intent = state["intent"]
        if intent is None or intent == "simple_chat":
            raise RuntimeError("Tool branch requires a database intent")

        async def summarize_steps(old: list[BaseMessage]) -> str:
            answer = await context.model_stream.call(summary_request(old, context.locale),
                                                     step=state["step"], event=None)
            if answer.tool_calls:
                raise ValueError("Step summary model returned a tool call")
            if not isinstance(answer.content, str):
                raise TypeError("Step summary must be text")
            return answer.content

        messages = await govern_messages(
            state["messages"], context_window=context.model_stream.usage.contextWindow,
            summarize=summarize_steps, emit=context.emit, step=state["step"], locale=context.locale,
            artifacts=context.tools.artifacts,
        )
        check_cancelled(context.cancel_event)
        await context.emit("thinking", "Planning database step", state["step"])
        decision = await context.model_stream.call(
            messages, step=state["step"], event=None, tools=context.tools.for_intent(intent),
        )
        check_cancelled(context.cancel_event)
        if not decision.tool_calls:
            if context.tools.statements_executed == 0:
                raise RuntimeError("SQL agent answered without executing a statement")
            if not isinstance(decision.content, str):
                raise TypeError("Database answer must be text")
            await context.emit("summary", decision.content, state["step"])
            return {"messages": messages, "decision": decision,
                    "answer": decision.content, "finished": True}
        return {"messages": messages, "decision": decision}

    async def execute(self, state: RunState) -> dict[str, object]:
        context = self.context
        check_cancelled(context.cancel_event)
        intent, decision = state["intent"], state["decision"]
        if intent is None or decision is None:
            raise RuntimeError("Tool decision is missing")
        available = {tool.name: tool for tool in context.tools.for_intent(intent)}
        additions: list[BaseMessage] = [decision]
        repeated_warning = False
        for call in decision.tool_calls:
            check_cancelled(context.cancel_event)
            if context.tools.terminated or context.tools.loop_stop_reason is not None:
                additions.append(ToolMessage(content="Skipped after execution stopped", tool_call_id=call["id"]))
                continue
            tool = available.get(call["name"])
            if tool is None:
                raise BusinessError(400, f"Unknown model tool: {call['name']}")
            args = call["args"]
            if not isinstance(args, dict):
                raise TypeError("Tool arguments must be an object")
            warning, stop = self.repeated_calls.record(call["name"], args)
            if stop:
                context.tools.loop_stop_reason = "Repeated tool call limit reached"
                additions.append(ToolMessage(content="Repeated call stopped without execution.",
                                             tool_call_id=call["id"]))
                continue
            context.tools.last_output = None
            result = await tool.ainvoke(args)
            check_cancelled(context.cancel_event)
            output = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str)
            additions.append(ToolMessage(content=output, tool_call_id=call["id"]))
            display = output if context.tools.last_output is None else context.tools.last_output
            await context.emit("step", f"{call['name']}: {display}", state["step"] + 1)
            repeated_warning = repeated_warning or warning
        if repeated_warning:
            additions.append(SystemMessage(content=(
                "This exact tool call has reached the warning threshold. Change strategy; "
                "do not repeat it unchanged."
            )))
        return {"messages": [*state["messages"], *additions], "step": state["step"] + 1,
                "finished": context.tools.terminated or context.tools.loop_stop_reason is not None}

    async def summarize(self, state: RunState) -> dict[str, object]:
        context = self.context
        check_cancelled(context.cancel_event)
        if context.tools.statements_executed == 0:
            content = ("No database statement was successfully executed. "
                       "Unfinished work: the requested database operation was not completed.")
            if context.tools.statement_errors:
                content += "\n\nStatement errors:\n" + "\n".join(context.tools.statement_errors)
            await context.emit("summary", content, state["step"])
            return {"answer": content, "finished": True}
        unfinished = context.tools.loop_stop_reason
        if unfinished is None and not context.tools.terminated and state["step"] >= self.max_steps:
            unfinished = "Step limit reached"
        warning = f"{unfinished}; report unfinished work." if unfinished else "Summarize completed work."
        answer = await context.model_stream.call(
            [*state["messages"], SystemMessage(content=warning)], step=state["step"], event="summary_delta",
        )
        check_cancelled(context.cancel_event)
        if not isinstance(answer.content, str):
            raise TypeError("Summary must be text")
        content = (f"{unfinished}. Unfinished work: remaining requested steps were not verified complete.\n\n"
                   f"{answer.content}" if unfinished else answer.content)
        await context.emit("summary", content, state["step"])
        return {"answer": content, "finished": True}
