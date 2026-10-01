"""Limited Chinese reports cannot promise full evidence without reading the artifact."""

import json

import pytest
from test_compare_evidence import _report

from app.agent.compare import CompareProgress
from app.agent.tools import RunTools
from app.agent.types import ChatRequest
from app.services import database_tools, schema_diff


@pytest.mark.parametrize("locale,truncated,partial,cross,summary,page", [
    ("zh-CN", "对比工具输出已截断", "数据库结构对比不完整", "跨引擎对比", "可用报告摘要", "输出制品"),
    ("zh-TW", "比較工具輸出已截斷", "資料庫結構比較不完整", "跨引擎比較", "可用報告摘要", "輸出製品"),
])
def test_large_partial_cross_engine_report_keeps_unread_artifact_limits(
    monkeypatch: pytest.MonkeyPatch, locale: str, truncated: str, partial: str,
    cross: str, summary: str, page: str,
) -> None:
    source = _report()
    pre_schema, test_schema = source["preSchema"], source["testSchema"]
    assert isinstance(pre_schema, dict) and isinstance(test_schema, dict)
    pre_schema.update({"incomplete": True, "errorMessage": "PARTIAL_METADATA_READ"})
    test_schema["dbType"] = "mysql"
    monkeypatch.setattr(database_tools, "get_schema", lambda _user, db_id:
                        pre_schema if db_id == 12 else test_schema)
    report = schema_diff.compare_databases(7, 12, 13)
    tools = RunTools(7, ChatRequest(message="compare", preDbConfigId=12, testDbConfigId=13))
    try:
        output = tools.bound(report, "compareDatabases")
        bounded = json.loads(output)
        assert len(output) <= 4000 and bounded["marker"] == "[TRUNCATED:TOOL_OUTPUT_TOO_LONG]"
        progress = CompareProgress()
        result = tools.last_result
        assert isinstance(result, dict)
        progress.observe(output, result)
        assert progress.output_truncated is True and progress.read_ranges == []
        safe = progress.safe_report(locale)
        assert safe is not None
        assert truncated in safe and partial in safe and cross in safe
        assert "PARTIAL_METADATA_READ" in safe
        assert "前 20" in safe and summary in safe and page in safe
        # The deterministic diff orders names lexically: its twentieth name is new_table_115.
        names_line = next(line for line in safe.splitlines() if "new_table_0," in line)
        names = names_line.rsplit("(", 1)[1].removesuffix(")").split(", ")
        assert len(names) == 20 and names[0] == "new_table_0" and names[-1] == "new_table_115"
        assert "new_table_116" not in safe
        assert "完整报告" not in safe and "完整報告" not in safe
        assert "已读取的完整" not in safe and "已讀取的完整" not in safe
        assert progress.output_truncated is True and progress.read_ranges == []
    finally:
        tools.close()
