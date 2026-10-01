"""S07 chat graph: classification, clarification, answering, and SQL tools."""

import threading
from dataclasses import dataclass
from typing import Literal, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from app.agent.cancellation import check_cancelled
from app.agent.graph_sql import SQLNodes
from app.agent.prompts import classification_prompt, system_prompt
from app.agent.streaming import ModelStream
from app.agent.tools import RunTools
from app.agent.types import ChatRequest, Classification, EventSink, Intent
from app.core.config import get_settings


class RunState(TypedDict):
    messages: list[BaseMessage]
    intent: Intent | None
    clarification: dict[str, object] | None
    step: int
    decision: AIMessage | None
    answer: str
    finished: bool


@dataclass
class RunContext:
    request: ChatRequest
    history: list[BaseMessage]
    locale: str
    model_stream: ModelStream
    tools: RunTools
    emit: EventSink
    cancel_event: threading.Event | None = None


def _clarification(intent: Intent, reason: str, locale: str) -> dict[str, object]:
    chinese = locale.lower().startswith("zh")
    question = "请确认意图并选择所需的数据源。" if chinese else "Confirm the intent and select the required database."
    labels = {
        "simple_chat": "普通问答" if chinese else "General question",
        "sql_query": "数据库查询" if chinese else "Database query",
        "workflow": "数据工作流" if chinese else "Data workflow",
        "db_compare": "结构对比" if chinese else "Schema comparison",
    }
    return {"question": question, "reasoning": reason,
            "options": [{"intent": key, "label": label} for key, label in labels.items()]}


def _missing_resources(intent: Intent, request: ChatRequest) -> str | None:
    if intent in ("sql_query", "workflow") and not request.db_config_ids:
        return "A connected database is required."
    if intent == "db_compare" and (request.pre_db_config_id is None or request.test_db_config_id is None):
        return "Both pre and test databases are required."
    return None


def _max_steps(intent: Intent) -> int:
    settings = get_settings()
    return {"sql_query": settings.sql_agent_max_steps,
            "workflow": settings.workflow_agent_max_steps,
            "db_compare": settings.compare_agent_max_steps}[intent]


def build_graph(context: RunContext):
    """Compile real conditional StateGraph nodes for one authorized request."""
    sql_nodes = SQLNodes(context, _max_steps("sql_query"))

    async def classify(state: RunState) -> dict[str, object]:
        check_cancelled(context.cancel_event)
        if context.request.confirmed_intent is not None:
            return {"intent": context.request.confirmed_intent}
        await context.emit("classifying", "Classifying intent", 0)
        response = await context.model_stream.call(
            [SystemMessage(content=classification_prompt(context.request, context.locale)),
             *context.history, HumanMessage(content=context.request.message)],
            event=None, classification=True,
        )
        check_cancelled(context.cancel_event)
        if not isinstance(response.content, str):
            raise TypeError("Intent classification must be a JSON object")
        try:
            value = Classification.model_validate_json(response.content)
        except (ValidationError, ValueError) as error:
            raise ValueError("Invalid intent classification JSON") from error
        await context.emit("classified", value.model_dump(), 0)
        if value.needsClarification or value.confidence < 0.7:
            return {"intent": value.intent,
                    "clarification": _clarification(value.intent, value.reasoning, context.locale)}
        return {"intent": value.intent}

    async def prerequisites(state: RunState) -> dict[str, object]:
        check_cancelled(context.cancel_event)
        intent = state["intent"]
        if intent is None:
            raise RuntimeError("Classification did not choose an intent")
        missing = _missing_resources(intent, context.request)
        if missing:
            return {"clarification": _clarification(intent, missing, context.locale)}
        await context.emit("routing", intent, 0)
        return {}

    async def clarify(state: RunState) -> dict[str, object]:
        check_cancelled(context.cancel_event)
        payload = state["clarification"]
        if payload is None:
            raise RuntimeError("Clarification payload is missing")
        await context.emit("clarify", payload, 0)
        return {"finished": True}

    async def simple(state: RunState) -> dict[str, object]:
        check_cancelled(context.cancel_event)
        messages = [SystemMessage(content=system_prompt("simple_chat", context.request, context.locale)),
                    *context.history, HumanMessage(content=context.request.message)]
        await context.emit("thinking", "Answering", 0)
        answer = await context.model_stream.call(messages, event="content")
        check_cancelled(context.cancel_event)
        if not isinstance(answer.content, str):
            raise TypeError("Simple answer must be text")
        return {"answer": answer.content, "finished": True}

    def after_classify(state: RunState) -> Literal["clarify", "prerequisites"]:
        return "clarify" if state["clarification"] is not None else "prerequisites"

    def after_prerequisites(state: RunState) -> Literal["clarify", "simple", "prepare_sql"]:
        if state["clarification"] is not None:
            return "clarify"
        return "simple" if state["intent"] == "simple_chat" else "prepare_sql"

    def after_decide(state: RunState) -> Literal["execute_tools", "end"]:
        return "end" if state["finished"] else "execute_tools"

    def after_tools(state: RunState) -> Literal["decide", "summarize"]:
        intent = state["intent"]
        if intent is None:
            raise RuntimeError("Tool branch lost its intent")
        return "summarize" if state["finished"] or state["step"] >= _max_steps(intent) else "decide"

    graph = StateGraph(RunState)
    for name, node in (("classify", classify), ("prerequisites", prerequisites), ("clarify", clarify),
                       ("simple", simple), ("prepare_sql", sql_nodes.prepare), ("decide", sql_nodes.decide),
                       ("execute_tools", sql_nodes.execute), ("summarize", sql_nodes.summarize)):
        graph.add_node(name, node)
    graph.add_edge(START, "classify")
    graph.add_conditional_edges("classify", after_classify)
    graph.add_conditional_edges("prerequisites", after_prerequisites)
    graph.add_edge("clarify", END)
    graph.add_edge("simple", END)
    graph.add_edge("prepare_sql", "decide")
    graph.add_conditional_edges("decide", after_decide, {"execute_tools": "execute_tools", "end": END})
    graph.add_conditional_edges("execute_tools", after_tools)
    graph.add_edge("summarize", END)
    return graph.compile()


async def run_graph(context: RunContext) -> RunState:
    initial: RunState = {"messages": [], "intent": None, "clarification": None,
                         "step": 0, "decision": None, "answer": "", "finished": False}
    try:
        recursion_limit = 2 * max(_max_steps(intent) for intent in
                                  ("sql_query", "workflow", "db_compare")) + 10
        return await build_graph(context).ainvoke(initial, {"recursion_limit": recursion_limit})
    finally:
        context.tools.close()
