"""Regression checks for restored source prompts and their runtime rendering."""

import pytest
from langchain_core.tools import BaseTool

from app.agent.prompts import (
    classification_prompt,
    language,
    load_prompt_template,
    render_prompt_template,
    split_prompt_sections,
    system_prompt,
)
from app.agent.tools import RunTools
from app.agent.types import ChatRequest


def request_with_resources() -> ChatRequest:
    return ChatRequest.model_validate({
        "message": "Compare the selected databases and import this file",
        "dbConfigIds": [12],
        "preDbConfigId": 31,
        "testDbConfigId": 32,
        "fileIds": [20],
    })


def tool_argument_names(tools: list[BaseTool]) -> dict[str, set[str]]:
    names: dict[str, set[str]] = {}
    for tool in tools:
        names[tool.name] = set(tool.args)
    return names


def test_source_sql_safety_rules_exist_in_both_languages() -> None:
    request = request_with_resources()
    english = system_prompt("sql_query", request, "en")
    chinese = system_prompt("sql_query", request, "zh-CN")

    assert "NEVER execute destructive commands" in english
    assert "DROP DATABASE, DROP TABLE, or TRUNCATE" in english
    assert "严禁执行 DROP DATABASE、DROP TABLE、TRUNCATE" in chinese
    assert "未经用户明确确认，绝不修改生产数据" in chinese
    assert "You MUST respond in English." in english
    assert "You MUST respond in Simplified Chinese." in chinese
    assert "Database IDs\n12, 31, 32" in english


def test_classification_uses_localized_resource_and_request_context() -> None:
    request = request_with_resources()
    english = classification_prompt(request, "en-US")
    chinese = classification_prompt(request, "zh_CN")

    assert "Intent Type Definitions" in english
    assert "Has the user selected a database: true" in english
    assert "Has the user uploaded files: true" in english
    assert "Has the user provided comparison databases: true" in english
    assert "意图类型定义" in chinese
    assert "用户是否已选择数据库: true" in chinese
    assert "Write reasoning in English." in english
    assert "Write reasoning in Simplified Chinese." in chinese


def test_workflow_prompts_match_run_tool_names_and_arguments() -> None:
    request = request_with_resources()
    tools = RunTools(7, request)
    definitions = tool_argument_names(tools.for_intent("workflow"))
    prompt = system_prompt("workflow", request, "en")

    expected = {"getDatabaseSchema", "executeSql", "readFile", "readImage", "readToolOutput", "doTerminate"}
    assert expected <= set(definitions)
    assert set(definitions["getDatabaseSchema"]) == {"db_id"}
    assert set(definitions["executeSql"]) == {"db_id", "statement"}
    assert set(definitions["readFile"]) == {"file_id"}
    assert set(definitions["readImage"]) == {"file_id"}
    assert set(definitions["readToolOutput"]) == {"artifact_id", "offset", "length"}
    assert set(definitions["doTerminate"]) == {"reason"}
    assert "getDatabaseSchema(db_id=...)" in prompt
    assert "executeSql(db_id=..., statement=...)" in prompt
    assert "readFile(file_id=N)" in prompt
    assert "readImage(file_id=N)" in prompt
    assert "readToolOutput(artifact_id, offset, length)" in prompt
    assert "Selected file IDs: 20" in prompt


def test_compare_prompt_keeps_source_rules_and_reports_runtime_boundary() -> None:
    request = request_with_resources()
    tools = RunTools(7, request)
    definitions = tool_argument_names(tools.for_intent("db_compare"))
    english = system_prompt("db_compare", request, "en")
    chinese = system_prompt("db_compare", request, "zh-CN")

    assert "compareDatabases" in definitions
    assert set(definitions["compareDatabases"]) == {"pre_id", "test_id"}
    assert "compareDatabases(pre_id=..., test_id=...)" in english
    assert "人工确认" in chinese
    assert "尚未实现或不可用" in chinese
    assert "DROP TABLE" in english and "NEVER execute" in english
    assert "Pre: 31" in english and "Test: 32" in english
    assert "doTerminate(reason=...)" in english


def test_locale_fallback_keeps_explicit_output_language() -> None:
    assert load_prompt_template("db-sql-agent-system", "zh-TW") == load_prompt_template(
        "db-sql-agent-system", "en"
    )
    assert language("zh-TW,zh;q=0.9") == "Traditional Chinese"
    assert "You MUST respond in Traditional Chinese." in system_prompt(
        "simple_chat", ChatRequest.model_validate({"message": "hi"}), "zh-TW"
    )
    assert "你是 DB-Genius" not in system_prompt(
        "simple_chat", ChatRequest.model_validate({"message": "hi"}), "zh-TW"
    )


def test_template_renderer_preserves_json_and_does_not_reprocess_values() -> None:
    template = '{"intent": "sql_query"}\nCurrent message: {message}\n{unknown}'
    rendered = render_prompt_template(template, {"message": "literal {unknown}"})

    assert rendered == '{"intent": "sql_query"}\nCurrent message: literal {unknown}\n{unknown}'


def test_prompt_sections_reject_repeated_delimiter() -> None:
    assert split_prompt_sections("system\n===USER===\nuser") == ("system", "user")
    with pytest.raises(ValueError, match="at most one"):
        split_prompt_sections("system\n===USER===\nuser\n===USER===\nagain")
