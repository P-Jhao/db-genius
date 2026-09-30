"""Load localized prompt resources and render their plain-text placeholders."""

import re
from collections.abc import Mapping, Sequence
from importlib.resources import files

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
    template = render_prompt_template(
        load_prompt_template("intent-classifier", locale),
        {
            "hasDbConfig": str(bool(request.db_config_ids)).lower(),
            "hasFiles": str(bool(request.file_ids)).lower(),
            "hasCompareConfig": str(
                request.pre_db_config_id is not None and request.test_db_config_id is not None
            ).lower(),
            "history": "Conversation history is supplied separately through prior messages.",
            "message": request.message,
        },
    )
    sections = split_prompt_sections(template)
    return f"{sections[0]}\n\nWrite reasoning in {language(locale)}."
