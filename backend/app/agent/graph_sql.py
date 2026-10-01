"""SQL graph nodes with bounded observations and explicit loop termination."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage

from app.agent.cancellation import check_cancelled
from app.agent.context_runtime import RepeatedCalls, govern_messages, summary_request
from app.agent.prompts import system_prompt
from app.agent.workflow import WorkflowProgress
from app.agent.workflow_rows import schema_mutation
from app.core.errors import BusinessError

if TYPE_CHECKING:
    from app.agent.graph import RunContext, RunState


class SQLNodes:
    def __init__(self, context: RunContext, max_steps: int) -> None:
        self.context = context
        self.max_steps = max_steps
        self.repeated_calls = RepeatedCalls()
        self.workflow = WorkflowProgress(set(context.request.file_ids or []))

    async def prepare(self, state: RunState) -> dict[str, object]:
        context = self.context
        check_cancelled(context.cancel_event)
        intent = state["intent"]
        if intent not in ("sql_query", "workflow"):
            raise BusinessError(501, f"{intent} workflow is scheduled for a later phase")
        schemas: list[str] = []
        for db_id in context.request.db_config_ids or []:
            check_cancelled(context.cancel_event)
            schema = await context.tools.schema(db_id)
            if intent == "workflow":
                self.workflow.schema.register(db_id, context.tools.last_result)
            schemas.append(f"Database {db_id} schema:\n{schema}")
            await context.emit("step", f"Read schema for database {db_id}", 0)
        messages: list[BaseMessage] = [
            SystemMessage(content=system_prompt(intent, context.request, context.locale)),
            *context.history, SystemMessage(content="\n\n".join(schemas)),
            HumanMessage(content=context.request.message),
        ]
        if intent == "workflow":
            messages.append(SystemMessage(content=(
                "Structured table rows require literal batch writes and matching query evidence. "
                "Unstructured document/OCR text does not prove a complete row import. "
                "Describe the actual verified operations; do not claim every text row was imported."
            )))
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
            if intent == "sql_query" and context.tools.statements_executed == 0:
                raise RuntimeError("SQL agent answered without executing a statement")
            if not isinstance(decision.content, str):
                raise TypeError("Database answer must be text")
            status = self.workflow.status() if intent == "workflow" else None
            content = decision.content if status is None else status
            await context.emit("summary", content, state["step"])
            return {"messages": messages, "decision": decision,
                    "answer": content, "finished": True}
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
            if (context.tools.terminated or context.tools.loop_stop_reason is not None or
                    (intent == "workflow" and self.workflow.failure is not None)):
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
            context.tools.last_result = None
            if intent == "workflow":
                self.workflow.before_call(call["name"], args)
            result = await tool.ainvoke(args)
            check_cancelled(context.cancel_event)
            if intent == "workflow":
                self.workflow.after_call(call["name"], args, context.tools.last_result)
            output = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str)
            additions.append(ToolMessage(content=output, tool_call_id=call["id"]))
            display = output if context.tools.last_output is None else context.tools.last_output
            await context.emit("step", f"{call['name']}: {display}", state["step"] + 1)
            if intent == "workflow" and call["name"] == "executeSql":
                db_id, statement = args.get("db_id"), args.get("statement")
                if not isinstance(db_id, int) or not isinstance(statement, str):
                    raise TypeError("SQL tool arguments are invalid")
                service_result = context.tools.last_result
                if (isinstance(service_result, dict) and service_result.get("success") is True and
                        schema_mutation(statement, self.workflow.schema.dialects.get(db_id))):
                    latest_schema = await context.tools.schema(db_id)
                    self.workflow.schema.register(db_id, context.tools.last_result)
                    additions.append(SystemMessage(content=f"Database {db_id} updated schema:\n{latest_schema}"))
            repeated_warning = repeated_warning or warning
        if repeated_warning:
            additions.append(SystemMessage(content=(
                "This exact tool call has reached the warning threshold. Change strategy; "
                "do not repeat it unchanged."
            )))
        return {"messages": [*state["messages"], *additions], "step": state["step"] + 1,
                "finished": (context.tools.terminated or context.tools.loop_stop_reason is not None or
                             (intent == "workflow" and self.workflow.failure is not None))}

    async def summarize(self, state: RunState) -> dict[str, object]:
        context = self.context
        check_cancelled(context.cancel_event)
        workflow_status = self.workflow.status() if state["intent"] == "workflow" else None
        if state["intent"] == "sql_query" and context.tools.statements_executed == 0:
            content = ("No database statement was successfully executed. "
                       "Unfinished work: the requested database operation was not completed.")
            if context.tools.statement_errors:
                content += "\n\nStatement errors:\n" + "\n".join(context.tools.statement_errors)
            await context.emit("summary", content, state["step"])
            return {"answer": content, "finished": True}
        unfinished = context.tools.loop_stop_reason
        limit = self.max_steps
        if state["intent"] == "workflow":
            from app.core.config import get_settings

            limit = get_settings().workflow_agent_max_steps
        if unfinished is None and not context.tools.terminated and state["step"] >= limit:
            unfinished = "Step limit reached"
        warning = (f"{workflow_status}; report only verified facts." if workflow_status else
                   f"{unfinished}; report unfinished work." if unfinished else "Summarize completed work.")
        answer = await context.model_stream.call(
            [*state["messages"], SystemMessage(content=warning)], step=state["step"],
            event=None if workflow_status else "summary_delta",
        )
        check_cancelled(context.cancel_event)
        if not isinstance(answer.content, str):
            raise TypeError("Summary must be text")
        content = (f"{unfinished}. Unfinished work: remaining requested steps were not verified complete.\n\n"
                   f"{answer.content}" if unfinished else answer.content)
        if workflow_status is not None:
            content = workflow_status if unfinished is None else f"{unfinished}. {workflow_status}"
        await context.emit("summary", content, state["step"])
        return {"answer": content, "finished": True}
