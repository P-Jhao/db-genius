"""Read-only comparison statements and metadata failures against real targets."""

import json

import pytest
from sqlalchemy.exc import DBAPIError
from test_model_protocol import Provider, model
from test_schema_diff_integration import (
    PRE_ID,
    TEST_ID,
    USER_ID,
    _adapter,
    _answer,
    _call,
    install_configs,
    temporary_pair,
)
from test_schema_diff_integration import provider as provider_fixture

from app.agent.compare import CompareProgress
from app.agent.graph import RunContext, run_graph
from app.agent.streaming import ModelStream
from app.agent.tools import RunTools
from app.agent.types import ChatRequest, Usage
from app.core.errors import BusinessError
from app.services import database_tools, schema_diff

provider = provider_fixture


@pytest.mark.parametrize("db_type", ["postgresql", "mysql"])
def test_real_dialect_reads_and_nested_write_rejection(monkeypatch: pytest.MonkeyPatch, db_type: str) -> None:
    with temporary_pair(db_type) as targets:
        install_configs(monkeypatch, targets)
        engine = _adapter(db_type)._engine(targets.pre, 30)
        q = '"' if db_type == "postgresql" else "`"
        try:
            with engine.begin() as connection:
                connection.exec_driver_sql(f"CREATE TABLE {q}order items{q} ({q}label value{q} TEXT)")
                connection.exec_driver_sql(f"INSERT INTO {q}order items{q} VALUES ('keep')")
            reads = [f"SELECT {q}label value{q} FROM {q}order items{q}",
                     f"EXPLAIN SELECT * FROM {q}order items{q}"]
            reads.extend(["SHOW ALL"] if db_type == "postgresql" else
                         ["SHOW TABLES", f"DESC {q}order items{q}", f"SHOW CREATE TABLE {q}order items{q}"])
            for statement in reads:
                result = database_tools.execute_comparison_read(USER_ID, PRE_ID, statement)
                assert result["success"] is True and result["rowCount"] > 0
            denied = ["SELECT 1; DELETE FROM orders", "CREATE TABLE unwanted (id INTEGER)"]
            if db_type == "postgresql":
                denied += ["SELECT 1 INTO unwanted",
                    "WITH changed AS (DELETE FROM orders RETURNING *) SELECT * FROM changed",
                    "EXPLAIN ANALYZE DELETE FROM orders"]
            for statement in denied:
                with pytest.raises(BusinessError):
                    database_tools.execute_comparison_read(USER_ID, PRE_ID, statement)
            with engine.connect() as connection:
                assert connection.exec_driver_sql(f"SELECT * FROM {q}order items{q}").all() == [("keep",)]
                names = (connection.exec_driver_sql("SELECT tablename FROM pg_tables WHERE schemaname='public'")
                         if db_type == "postgresql" else connection.exec_driver_sql("SHOW TABLES"))
                assert "unwanted" not in {str(row[0]) for row in names}
        finally:
            engine.dispose()


def test_pg_read_only_transaction_stops_function_side_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    with temporary_pair("postgresql") as targets:
        install_configs(monkeypatch, targets)
        engine = _adapter("postgresql")._engine(targets.pre, 30)
        try:
            with engine.begin() as connection:
                connection.exec_driver_sql("CREATE SEQUENCE comparison_sequence")
            with pytest.raises(DBAPIError):
                database_tools.execute_comparison_read(USER_ID, PRE_ID, "SELECT nextval('comparison_sequence')")
            with engine.connect() as connection:
                assert connection.exec_driver_sql("SELECT last_value,is_called FROM comparison_sequence").one() == (1, False)
        finally:
            engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("db_type", ["postgresql", "mysql"])
async def test_real_metadata_read_failure_has_partial_report_and_no_model_success(
    monkeypatch: pytest.MonkeyPatch, provider: Provider, db_type: str,
) -> None:
    with temporary_pair(db_type) as targets:
        install_configs(monkeypatch, targets)
        adapter_class = type(_adapter(db_type))
        original = adapter_class._read_table

        def fail_one_table(self, connection, inspector, table_name):
            if table_name == "orders" and connection.engine.url.database == targets.pre.db_name:
                connection.exec_driver_sql("SELECT missing_metadata_column FROM orders")
                pytest.fail("Expected an actual driver metadata-read error")
            return original(self, connection, inspector, table_name)

        monkeypatch.setattr(adapter_class, "_read_table", fail_one_table)
        report = schema_diff.compare_databases(USER_ID, PRE_ID, TEST_ID)
        assert report["success"] is False and report["complete"] is False
        assert report["preComplete"] is False and report["testComplete"] is True
        assert "missing_metadata_column" in report["preError"]
        progress = CompareProgress()
        progress.observe(json.dumps(report), report)
        assert "comparison is incomplete" in progress.safe_report()
        provider.replies = [_call("compareDatabases", {"pre_id": PRE_ID, "test_id": TEST_ID}, "compare"),
                            _answer("No differences, all migrations are safe.")]
        request = ChatRequest(message="compare", preDbConfigId=PRE_ID, testDbConfigId=TEST_ID,
                              confirmedIntent="db_compare")
        events: list[str] = []

        async def emit(kind: str, _content: object, _step: int) -> None:
            events.append(kind)

        result = await run_graph(RunContext(request, [], "en", ModelStream(model(provider), emit, Usage()),
                                           RunTools(USER_ID, request), emit))
        assert "comparison is incomplete" in result["answer"]
        assert "all migrations are safe" not in result["answer"]
        assert "summary_delta" not in events
        assert len(provider.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("db_type", ["postgresql", "mysql"])
async def test_comparison_read_error_can_be_repaired_before_actual_comparison(
    monkeypatch: pytest.MonkeyPatch, provider: Provider, db_type: str,
) -> None:
    with temporary_pair(db_type) as targets:
        install_configs(monkeypatch, targets)
        provider.replies = [
            _call("executeSql", {"db_id": PRE_ID,
                                "statement": "SELECT missing_comparison_column FROM orders"}, "bad_read"),
            _call("executeSql", {"db_id": PRE_ID, "statement": "SELECT id FROM orders"}, "fixed_read"),
            _call("compareDatabases", {"pre_id": PRE_ID, "test_id": TEST_ID}, "compare"),
            _call("doTerminate", {"reason": "report ready"}, "done"),
            _answer("The actual pre→test comparison completed after correcting the read."),
        ]
        request = ChatRequest(message="compare", preDbConfigId=PRE_ID, testDbConfigId=TEST_ID,
                              confirmedIntent="db_compare")
        events: list[tuple[str, object]] = []

        async def emit(kind: str, content: object, _step: int) -> None:
            events.append((kind, content))

        tools = RunTools(USER_ID, request)
        usage = Usage()
        result = await run_graph(RunContext(request, [], "en", ModelStream(model(provider), emit, usage),
                                           tools, emit))
        assert "comparison completed" in result["answer"]
        assert any(kind == "step" and '"success": false' in str(content)
                   and "missing_comparison_column" in str(content) for kind, content in events)
        assert any(kind == "step" and '"ADD_COLUMN"' in str(content) for kind, content in events)
        assert tools.statements_executed == 1 and tools.completed_write_count == 0
        assert tools.successful_writes == set()
        assert len(provider.requests) == usage.callCount == 5
        assert usage.totalTokens == 0  # Provider omitted usage; do not invent token accounting.
