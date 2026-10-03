"""Controlled HTTP models cannot turn doTerminate into a fictitious SQL success."""

import json

import pytest
from test_model_protocol import Provider, frame, model

from app.agent.graph import RunContext, run_graph
from app.agent.streaming import ModelStream
from app.agent.tools import RunTools
from app.agent.types import ChatRequest, Usage
from app.services import database_tools

pytest_plugins = ["test_chat_api"]


def tool_reply(name: str, arguments: dict[str, object]) -> list[bytes]:
    return [frame({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": name,
              "function": {"name": name, "arguments": json.dumps(arguments)}}]}}]}), frame("[DONE]")]


def text_reply(content: str) -> list[bytes]:
    return [frame({"choices": [{"delta": {"content": content}}]}), frame("[DONE]")]


async def run_sql(provider: Provider, message: str, locale: str = "en") -> tuple[str, RunTools]:
    async def emit(_kind: str, _content: object, _step: int) -> None:
        pass

    request = ChatRequest.model_validate({"message": message, "dbConfigIds": [12],
                                          "confirmedIntent": "sql_query"})
    tools = RunTools(1, request)
    result = await run_graph(RunContext(request, [], locale, ModelStream(model(provider), emit, Usage()),
                                        tools, emit))
    return result["answer"], tools


@pytest.mark.parametrize("failed_statement", [False, True])
@pytest.mark.asyncio
async def test_termination_without_success_has_authoritative_unfinished_report(
    failed_statement: bool, provider: Provider, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(database_tools, "get_schema", lambda _user, _db: {"tables": []})
    executions: list[str] = []

    def execute(_user: int, _db: int, statement: str) -> dict[str, object]:
        executions.append(statement)
        return {"success": False, "error": "Unknown table missing_orders"}

    monkeypatch.setattr(database_tools, "execute_statement", execute)
    provider.replies = ([tool_reply("executeSql", {"db_id": 12, "statement": "SELECT * FROM missing_orders"})]
                        if failed_statement else [])
    provider.replies.append(tool_reply("doTerminate", {"reason": "All requested work completed"}))
    events: list[tuple[str, object]] = []

    async def emit(kind: str, content: object, _step: int) -> None:
        events.append((kind, content))

    request = ChatRequest(message="Query orders", dbConfigIds=[12], confirmedIntent="sql_query")
    usage = Usage()
    tools = RunTools(1, request)
    result = await run_graph(RunContext(request, [], "en", ModelStream(model(provider), emit, usage), tools, emit))
    assert "No database statement was successfully executed" in result["answer"]
    assert "was not completed" in result["answer"]
    assert "All requested work completed" not in result["answer"]
    assert len(provider.requests) == (2 if failed_statement else 1)
    assert len(executions) == (1 if failed_statement else 0)
    assert tools.statements_executed == 0
    assert events[-1] == ("summary", result["answer"])
    if failed_statement:
        assert "Unknown table missing_orders" in result["answer"]


@pytest.mark.parametrize(("locale", "fragment"), [
    ("en", "forbidden by the database safety rules"),
    ("zh-CN", "数据库安全规则禁止"),
    ("zh-TW", "資料庫安全規則禁止"),
    ("fr", "règles de sécurité"),
    ("ms", "peraturan keselamatan"),
    ("ja", "安全規則で禁止"),
    ("es", "reglas de seguridad"),
])
@pytest.mark.parametrize("statement", ["DROP TABLE orders", "TRUNCATE TABLE customers"])
@pytest.mark.asyncio
async def test_explicit_forbidden_request_is_refused_without_execution(
    locale: str, fragment: str, statement: str, provider: Provider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(database_tools, "get_schema", lambda _user, _db: {"tables": []})
    executions: list[str] = []
    monkeypatch.setattr(database_tools, "execute_statement", lambda _user, _db, sql:
                        executions.append(sql))
    provider.replies = [tool_reply("doTerminate", {"reason": "All requested work completed"})]
    answer, tools = await run_sql(provider, f"请执行 {statement}。若安全规则不允许，说明拒绝原因。", locale)
    assert fragment in answer
    assert "DROP" in answer and "TRUNCATE" in answer
    assert "All requested work completed" not in answer
    assert tools.statements_executed == 0 and tools.completed_write_count == 0
    assert executions == [] and len(provider.requests) == 1


@pytest.mark.asyncio
async def test_direct_model_refusal_is_authoritative_only_for_forbidden_request(
    provider: Provider, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(database_tools, "get_schema", lambda _user, _db: {"tables": []})
    provider.replies = [text_reply("I completed the request.")]
    answer, tools = await run_sql(provider, "Please execute DROP TABLE orders")
    assert "forbidden by the database safety rules" in answer
    assert "completed" not in answer
    assert tools.statements_attempted == tools.statements_executed == 0


@pytest.mark.parametrize("message", [
    "请执行 ALTER TABLE customers DROP COLUMN name。若安全规则不允许请拒绝。",
    "DROP TABLE orders",
    "TRUNCATE TABLE customers;",
    "ALTER TABLE customers DROP COLUMN name;",
])
@pytest.mark.asyncio
async def test_explicit_alter_or_complete_sql_command_is_refused(
    message: str, provider: Provider, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(database_tools, "get_schema", lambda _user, _db: {"tables": []})
    provider.replies = [tool_reply("doTerminate", {"reason": "Done"})]
    answer, tools = await run_sql(provider, message)
    assert "forbidden by the database safety rules" in answer
    assert tools.statements_attempted == tools.statements_executed == 0
    assert len(provider.requests) == 1


@pytest.mark.parametrize("message", [
    "SELECT 'DROP TABLE orders' AS note",
    "-- DROP TABLE orders\nSELECT 1",
    "Explain why executing DROP TABLE orders is forbidden",
    "请解释为什么执行 DROP TABLE orders 不安全",
    "DROP TABLE orders 是什么意思？",
    "TRUNCATE TABLE customers 的风险有哪些？",
    "ALTER TABLE customers DROP COLUMN name 与结构对比报告有什么关系？",
])
@pytest.mark.asyncio
async def test_drop_mention_is_not_a_safe_refusal(
    message: str, provider: Provider, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(database_tools, "get_schema", lambda _user, _db: {"tables": []})
    provider.replies = [tool_reply("doTerminate", {"reason": "I refuse DROP"})]
    answer, tools = await run_sql(provider, message)
    assert "No database statement was successfully executed" in answer
    assert "I refuse DROP" not in answer
    assert tools.statements_executed == 0


@pytest.mark.parametrize(("locale", "unfinished", "errors_label"), [
    ("en", "Unfinished work", "Statement errors:"),
    ("zh-CN", "未完成", "语句错误："),
    ("zh-TW", "未完成", "語句錯誤："),
    ("fr", "Travail inachevé", "Erreurs des instructions :"),
    ("ms", "Kerja belum selesai", "Ralat pernyataan:"),
    ("ja", "未完了", "文のエラー："),
    ("es", "Trabajo pendiente", "Errores de las sentencias:"),
])
@pytest.mark.parametrize("failed_statement", [False, True])
@pytest.mark.asyncio
async def test_zero_success_termination_is_localized_and_retains_statement_error(
    locale: str, unfinished: str, errors_label: str, failed_statement: bool,
    provider: Provider, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(database_tools, "get_schema", lambda _user, _db: {"tables": []})
    monkeypatch.setattr(database_tools, "execute_statement", lambda _user, _db, _sql:
                        {"success": False, "error": "Unknown table missing_orders"})
    provider.replies = ([tool_reply("executeSql", {"db_id": 12,
                                                    "statement": "SELECT * FROM missing_orders"})]
                        if failed_statement else [])
    provider.replies.append(tool_reply("doTerminate", {"reason": "All requested work completed"}))
    answer, tools = await run_sql(provider, "Query orders", locale)
    assert unfinished in answer and "All requested work completed" not in answer
    assert tools.statements_executed == 0
    assert tools.statements_attempted == int(failed_statement)
    if failed_statement:
        assert errors_label in answer and "Unknown table missing_orders" in answer
        assert tools.statement_errors == ["Unknown table missing_orders"]
    else:
        assert errors_label not in answer and tools.statement_errors == []


@pytest.mark.asyncio
async def test_read_only_drop_literal_executes_normally(
    provider: Provider, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(database_tools, "get_schema", lambda _user, _db: {"tables": []})
    statements: list[str] = []

    def execute(_user: int, _db: int, statement: str) -> dict[str, object]:
        statements.append(statement)
        return {"success": True, "rowCount": 1, "data": [{"note": "DROP TABLE orders"}]}

    monkeypatch.setattr(database_tools, "execute_statement", execute)
    statement = "SELECT 'DROP TABLE orders' AS note"
    provider.replies = [tool_reply("executeSql", {"db_id": 12, "statement": statement}),
                        text_reply("DROP TABLE orders")]
    answer, tools = await run_sql(provider, statement)
    assert answer == "DROP TABLE orders"
    assert statements == [statement] and tools.statements_executed == 1


@pytest.mark.asyncio
async def test_join_projection_instruction_reaches_http_model_and_exact_result(
    provider: Provider, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(database_tools, "get_schema", lambda _user, _db: {
        "tables": [{"name": "customers", "columns": ["id", "name"]},
                   {"name": "orders", "columns": ["customer_id", "amount"]}],
    })
    statement = ("SELECT c.name AS customer_name, SUM(o.amount) AS total_amount "
                 "FROM customers c LEFT JOIN orders o ON o.customer_id=c.id "
                 "GROUP BY c.id,c.name ORDER BY c.id")
    statements: list[str] = []

    def execute(_user: int, _db: int, sql: str) -> dict[str, object]:
        statements.append(sql)
        return {"success": True, "rowCount": 1,
                "data": [{"customer_name": "Ada", "total_amount": 15}]}

    monkeypatch.setattr(database_tools, "execute_statement", execute)
    provider.replies = [tool_reply("executeSql", {"db_id": 12, "statement": statement}),
                        text_reply("Ada: 15")]
    answer, tools = await run_sql(provider, "Return customer_name and total_amount only; order by customers.id")
    messages = provider.requests[0]["messages"]
    assert isinstance(messages, list)
    system = "\n".join(str(item["content"]) for item in messages if item["role"] == "system")
    assert "exactly those columns" in system
    assert "ORDER BY without selecting them" in system
    assert "auxiliary verification query does not replace" in system
    assert "customers" in system and "orders" in system
    assert statements == [statement] and tools.statements_executed == 1
    assert answer == "Ada: 15"
