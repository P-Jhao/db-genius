# S11 中文截断报告文案 revision

仅在独立 revision 目录修改 `compare_locale.py` 的 zh-CN/zh-TW 两条 details_limited 文案。原 22 文件冻结版与 manifest SHA `a7cf1faf346e884119878ab3739f0165612a01fd6d1989b59286bd898bad0d0f` 保持不变，接受基线仍为其实际验证的 `9703123`，不覆盖共享业务或后续 receipt 文档。

原文声称对比步骤包含“已读取的完整报告”；在大报告已截断且制品未完整读取时，该说法超出已读取证据。修订为展示“可用报告摘要”，并明确截断内容仍需读取输出制品。前 20 项、部分读取、跨方言和截断限制均保留；不改变任何状态、分页、SQL、安全策略或 LLM 行为，也不改其他五种语言。

新增确定性测试使用实际 schema_diff 生成 200 个表的 partial、跨引擎报告，通过原 4000 字裁剪得到 artifact marker，保持 read_ranges=[]。两种中文分别断言未声称完整报告、摘要只列前 20 个实际排序名称、partial/方言/truncated 文案仍存在，且 safe_report 调用后 output_truncated 仍为 true。没有访问真实数据库或外部模型。

验证：

- `ruff check app/agent/compare_locale.py tests/test_compare_locale_revision.py tests/test_compare_locale.py tests/test_compare_evidence.py`：通过。
- `mypy app/agent/compare_locale.py app/agent/compare.py`：严格 2 模块通过，未使用 ignore-missing-imports。
- `python -m pytest tests/test_compare_locale_revision.py tests/test_compare_locale.py tests/test_compare_evidence.py -q --tb=short`：**29 passed，26.52 秒**。

初次新增用例有 2 项名称排序断言错误（按数值序假设 twentieth=19，而确定性 diff 按字符串排序实际 twentieth=115）；修正测试预期后以上集合全部通过。没有修改比较排序或为测试放宽限制。按主代理授权未重跑 521 项全量集合。

`files.tsv` 仅列三份 payload：locale、新测试、本文。`guard.tsv` 为控制证据，对原冻结版 22 文件及其 441 份 accepted 保留文件逐字节核查：原 freeze 全部不变；revision 仅 locale 允许两条精确字符串替换，其余 462 份基线文件保持原 SHA。AGENTS.md 已检查，核心目录和业务边界未改变，保持原样。没有 Git 提交或容器操作。冻结后等待主代理叠加 revision 验收。
