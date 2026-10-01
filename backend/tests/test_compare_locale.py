"""Localized safe conclusions preserve the same authoritative facts without an LLM rewrite."""

from typing import cast

import pytest
from test_compare_graph import call
from test_model_protocol import Provider, model
from test_schema_diff import _column, _schema, _table

from app.adapters.types import SchemaMetadata
from app.agent.compare import CompareProgress
from app.agent.graph import RunContext, run_graph
from app.agent.streaming import ModelStream
from app.agent.tools import RunTools
from app.agent.types import ChatRequest, Usage
from app.services import database_tools

pytest_plugins = ["test_chat_api"]

LANGUAGES = [
    ("en", "incomplete", "up to 50 sample documents per collection", "No directly executable migration SQL"),
    ("zh-CN", "不完整", "每个集合最多 50 个样本文档", "未生成可直接执行的迁移 SQL"),
    ("zh-TW", "不完整", "各集合最多 50 個樣本文件", "未產生可直接執行的遷移 SQL"),
    ("es", "incompleta", "hasta 50 documentos de muestra por colección", "No se generó SQL de migración"),
    ("fr", "incomplète", "au plus 50 documents par collection", "Aucun SQL de migration directement exécutable"),
    ("ja", "不完全", "各コレクション最大 50 件", "直接実行できる移行 SQL は生成されていません"),
    ("ms", "tidak lengkap", "sehingga 50 dokumen sampel setiap koleksi", "SQL migrasi yang boleh dilaksanakan terus tidak dijana"),
]


@pytest.mark.parametrize("locale,incomplete,sampling,no_sql", LANGUAGES)
@pytest.mark.asyncio
async def test_safe_graph_summary_in_all_languages_has_same_facts_and_limits(
    provider: Provider, monkeypatch: pytest.MonkeyPatch,
    locale: str, incomplete: str, sampling: str, no_sql: str,
) -> None:
    pre = cast(SchemaMetadata, {**_schema("BEFORE_DB", "mongodb", _table("OLD_OBSERVED_TABLE"),
                   _table("SHARED_TABLE", _column("VALUE", "VARCHAR(20)", False)),
                   incomplete=True, error_message="RAW_METADATA_FAILED"),
                   "schemaInferred": True, "sampleSize": 50})
    test = _schema("AFTER_DB", "postgresql", _table("NEW_OBSERVED_TABLE"),
                   _table("SHARED_TABLE", _column("VALUE", "VARCHAR(40)", True),
                          _column("NEW_COLUMN", "TEXT", True)))
    monkeypatch.setattr(database_tools, "get_schema", lambda _user, db_id: pre if db_id == 12 else test)
    provider.replies = [call("compareDatabases", {"pre_id": 12, "test_id": 13}, "compare")]
    request = ChatRequest(message="compare", preDbConfigId=12, testDbConfigId=13, confirmedIntent="db_compare")
    events: list[tuple[str, object]] = []

    async def emit(kind: str, content: object, _step: int) -> None:
        events.append((kind, content))

    result = await run_graph(RunContext(request, [], locale, ModelStream(model(provider), emit, Usage()),
                                       RunTools(7, request), emit))
    report = result["answer"]
    assert incomplete in report and sampling in report and no_sql in report
    direction = report.splitlines()[0]
    assert direction.index("BEFORE_DB") < direction.index("→") < direction.index("AFTER_DB")
    assert "mongodb" in report and "postgresql" in report  # Cross-engine review remains required.
    assert "RAW_METADATA_FAILED" in report
    assert "OLD_OBSERVED_TABLE" in report and "NEW_OBSERVED_TABLE" in report
    assert '"table": "SHARED_TABLE"' in report and '"column": "NEW_COLUMN"' in report
    assert '"ADD_COLUMN"' in report and '"MODIFY_COLUMN"' in report and '"MODIFY_NULLABLE"' in report
    assert '"preType": "VARCHAR(20)"' in report and '"testType": "VARCHAR(40)"' in report
    assert '"preNullable": false' in report and '"testNullable": true' in report
    assert len(provider.requests) == 1  # No summary model may overwrite a limited comparison.
    assert not any(kind == "summary_delta" for kind, _ in events)
    assert events[-1] == ("summary", report)


@pytest.mark.parametrize("locale,missing", [
    ("en", "No database comparison completed"), ("zh-CN", "尚未完成数据库对比"),
    ("zh-TW", "尚未完成資料庫比較"), ("es", "No se completó la comparación"),
    ("fr", "Aucune comparaison"), ("ja", "比較は完了していません"),
    ("ms", "Perbandingan pangkalan data belum selesai"),
])
def test_missing_comparison_has_localized_unfinished_conclusion(locale: str, missing: str) -> None:
    progress = CompareProgress()
    assert missing in progress.safe_report(locale)
