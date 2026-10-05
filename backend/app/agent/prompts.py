"""Load localized prompt resources and render their plain-text placeholders."""

import re
from collections.abc import Mapping, Sequence
from importlib.resources import files

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from app.agent.task_goal import GOAL_RULE
from app.agent.types import ChatRequest, Intent

_RESOURCE_NAME = re.compile(r"[a-z0-9_-]+\Z")
_PLACEHOLDER = re.compile(r"(?<!\{)\{([A-Za-z][A-Za-z0-9]*)\}(?!\})")
_USER_SECTION = re.compile(r"(?m)^===USER===\r?$")
_PROMPT_BY_INTENT: dict[Intent, str] = {
    "simple_chat": "simple-chat-agent-system",
    "sql_query": "db-sql-agent-system",
    "workflow": "db-workflow-agent-system",
    "db_compare": "db-compare-agent-system",
}
_LANGUAGE_NAMES = {
    "en": "English",
    "zh-cn": "Simplified Chinese",
    "zh-tw": "Traditional Chinese",
    "zh": "Chinese",
    "ja": "Japanese",
    "es": "Spanish",
    "fr": "French",
    "ms": "Malay",
}


def _locale_code(locale: str) -> str:
    value = locale.split(",", maxsplit=1)[0].split(";", maxsplit=1)[0]
    return value.strip().lower().replace("_", "-")


def language(locale: str) -> str:
    """Return the explicit response-language name for the request locale."""
    code = _locale_code(locale)
    base_language = code.split("-", maxsplit=1)[0]
    return _LANGUAGE_NAMES.get(code, _LANGUAGE_NAMES.get(base_language, "English"))


def _prompt_variant(locale: str) -> str:
    """Use the source's zh_CN prompt; other locales use English prompt text."""
    return "zh_CN" if _locale_code(locale) == "zh-cn" else "en"


def load_prompt_template(name: str, locale: str) -> str:
    """Load a prompt from app/resources/prompts, falling back to English."""
    if _RESOURCE_NAME.fullmatch(name) is None:
        raise ValueError(f"Invalid prompt resource name: {name!r}")

    variant = _prompt_variant(locale)
    resource = files("app").joinpath("resources", "prompts", f"{name}_{variant}.md")
    if not resource.is_file() and variant != "en":
        resource = files("app").joinpath("resources", "prompts", f"{name}_en.md")
    if not resource.is_file():
        raise FileNotFoundError(f"Prompt resource not found: {name} ({locale})")
    return resource.read_text(encoding="utf-8")


def render_prompt_template(template: str, values: Mapping[str, str]) -> str:
    """Replace named placeholders once while leaving JSON braces untouched."""

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        return values.get(key, match.group(0))

    return _PLACEHOLDER.sub(replace, template)


def split_prompt_sections(template: str) -> tuple[str, ...]:
    """Split a source prompt's system and user sections at ===USER===."""
    sections = _USER_SECTION.split(template)
    if len(sections) > 2:
        raise ValueError("Prompt template may contain at most one ===USER=== delimiter")
    return tuple(section.strip() for section in sections)


def _format_ids(values: Sequence[int] | None) -> str:
    if values is None or len(values) == 0:
        return "(none)"
    return ", ".join(str(value) for value in values)


def _format_optional_id(value: int | None) -> str:
    if value is None:
        return "(none)"
    return str(value)


def _selected_database_ids(request: ChatRequest) -> list[int]:
    selected = [] if request.db_config_ids is None else list(request.db_config_ids)
    for database_id in (request.pre_db_config_id, request.test_db_config_id):
        if database_id is not None and database_id not in selected:
            selected.append(database_id)
    return selected


def _system_prompt_values(request: ChatRequest, locale: str) -> dict[str, str]:
    return {
        "outputLanguage": language(locale),
        "databaseIds": _format_ids(_selected_database_ids(request)),
        "fileIds": _format_ids(request.file_ids),
    }


def system_prompt(intent: Intent, request: ChatRequest, locale: str) -> str:
    """Build the system prompt for a graph intent using the source templates."""
    template_name = _PROMPT_BY_INTENT.get(intent)
    if template_name is None:
        raise ValueError(f"Unsupported prompt intent: {intent}")

    values = _system_prompt_values(request, locale)
    if intent == "sql_query":
        values.update({
            "dialect": (
                "Use the dialect identified by the selected database schema. "
                "If it is unclear, ask before generating SQL."
            ),
            "schema": "Schema details are supplied in a separate system message after this prompt.",
        })
    elif intent == "workflow":
        file_template = load_prompt_template("db-workflow-agent-files", locale)
        values.update({
            "fileSection": render_prompt_template(file_template, values),
            "schema": (
                "Read the selected database schema with getDatabaseSchema(db_id=...) "
                "before planning SQL."
            ),
        })
    elif intent == "db_compare":
        values.update({
            "preDatabaseId": _format_optional_id(request.pre_db_config_id),
            "testDatabaseId": _format_optional_id(request.test_db_config_id),
            "preSchema": "Available only from a successful compareDatabases result for the selected pre_id.",
            "testSchema": (
                "Available only from a successful compareDatabases result for the selected test_id."
            ),
        })

    prompt = render_prompt_template(load_prompt_template(template_name, locale), values)
    if intent != "simple_chat":
        policy = load_prompt_template("_context-policy", locale)
        prompt = f"{prompt.rstrip()}\n\n{render_prompt_template(policy, values).strip()}"
    return f"{prompt.rstrip()}\n\nYou MUST respond in {language(locale)}."


def classification_prompt(request: ChatRequest, locale: str) -> str:
    """Render the original classifier's system section for the current request."""
    sections = split_prompt_sections(load_prompt_template("intent-classifier", locale))
    if len(sections) != 2:
        raise ValueError("Intent classifier prompt requires a user section")
    system = render_prompt_template(sections[0], {
        "hasDbConfig": str(bool(request.db_config_ids)).lower(),
        "hasFiles": str(bool(request.file_ids)).lower(),
        "hasCompareConfig": str(
            request.pre_db_config_id is not None and request.test_db_config_id is not None
        ).lower(),
    })
    if _prompt_variant(locale) == "zh_CN":
        actionability = (
            "对于 sql_query/workflow，能判断意图类别不等于任务已可执行。只有当前消息或有效历史"
            "明确给出具体操作及其目标、数据来源或范围时，才设 needsClarification=false。已选择的"
            "数据库或附件仅表示资源可用，不能替用户补出缺失的操作或目标。历史中的明确任务可以支持"
            "续问；无附件但明确的多步骤数据库操作仍可归为 workflow。"
        )
    else:
        actionability = (
            "For sql_query/workflow, identifying the intent category does not make the task "
            "actionable. Set needsClarification=false only when the current message or effective "
            "history identifies both a concrete operation and its target, data source, or scope. "
            "Selected database and file flags indicate available resources; they do not supply "
            "a missing operation or target. A concrete prior goal may ground a follow-up, and an "
            "explicit multi-step database task may be workflow without an attachment."
        )
    contract = (
        "Return the four classification fields plus required taskGoal. For sql_query, taskGoal "
        "is the strict goal object below, derived in this same call. For all other intents taskGoal "
        "must be null. The goal is internal and does not add a public intent.\n" + GOAL_RULE
    )
    return f"{system}\n\n{actionability}\n\n{contract}\n\nWrite reasoning in {language(locale)}."


def classification_user_prompt(request: ChatRequest, history: Sequence[BaseMessage], locale: str) -> str:
    """Render the source classifier's user section with one labeled history snapshot."""
    sections = split_prompt_sections(load_prompt_template("intent-classifier", locale))
    if len(sections) != 2:
        raise ValueError("Intent classifier prompt requires a user section")
    zh = _prompt_variant(locale) == "zh_CN"
    if not history:
        history_text = "（无历史对话）" if zh else "(no conversation history)"
    else:
        lines = ["## 最近对话历史\n" if zh else "## Recent conversation history\n"]
        for message in history:
            if not isinstance(message.content, str):
                raise TypeError("Classification history content must be text")
            if isinstance(message, HumanMessage):
                role = "用户" if zh else "user"
            elif isinstance(message, AIMessage):
                role = "助手" if zh else "assistant"
            elif isinstance(message, SystemMessage):
                role = "摘要" if zh else "summary"
            else:
                raise TypeError("Unsupported classification history message")
            lines.append(f"{role}: {message.content}")
        history_text = "\n".join(lines)
    result = render_prompt_template(sections[1], {"history": history_text, "message": request.message})
    return result + "\n\nSelected database IDs: " + _format_ids(request.db_config_ids)


def task_goal_prompt(locale: str) -> str:
    return GOAL_RULE + f"\nWrite reasoning in {language(locale)}."


def summary_prompt_messages(history: Sequence[BaseMessage], request: ChatRequest,
                            locale: str, intent: Intent | None = None) -> list[BaseMessage]:
    """Assemble source summary system/user sections around the execution history."""
    sections = split_prompt_sections(load_prompt_template("tool-call-summary", locale))
    if len(sections) != 2:
        raise ValueError("Tool summary prompt requires a user section")
    execution_history = list(history)
    if (intent is not None and execution_history and isinstance(execution_history[0], SystemMessage)
            and execution_history[0].content == system_prompt(intent, request, locale)):
        execution_history = execution_history[1:]
    return [SystemMessage(content=sections[0] + f"\nRespond in {language(locale)}."),
            *execution_history,
            HumanMessage(content=render_prompt_template(sections[1], {"message": request.message}))]
