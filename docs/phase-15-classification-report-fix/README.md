# S15 分类与报告证据修复

## 范围与来源

第二轮固定矩阵已完成 120 行、138 轮，原始结果保留。初始隔离补丁来自 `.git/acceptance/s15-clarification-fix-20261003/candidate.patch`，涉及分类提示、图路由与 SQL 图。当前正式候选范围为 `backend/app/agent/{graph,prompts,graph_sql,report_rules}.py`，并新增三项受控测试：`test_classification_actionability.py`、`test_compare_risk_guidance.py` 和 `test_compare_direct_report_rules.py`。原 120 组用例、oracle、模型参数、prompt 资源和 Java 参考项目未改。真实模型效果专项尚未运行，不能宣称线上误路由或报告失真已被效果验证修复。

分类调用现在渲染原模板的 `===USER===` 段，按角色只提供一次有效历史和当前用户消息。运行时分类规则要求 SQL/工作流同时有明确操作与目标；数据库选择或附件存在只证明资源可用，短续问可以从有效历史取得目标，无附件的明确多步数据库任务仍可路由。四字段 JSON 与置信度阈值保持不变。

对比最终报告的通用规则要求把工具观察到的 add/drop 与重命名推测分开，准确解释 `NUMERIC(p,s)` 的总位数和整数位容量，并分别论述表重写、锁与已提交/未提交 PostgreSQL DDL。MySQL 8.0 的 CREATE/ALTER/DROP DDL 一般触发隐式提交，atomic DDL 不代表可以由用户事务回滚；不得承诺后续失败会恢复先前 DDL。SQL 与对比总结均须区分 SQL 语义和实测数据事实，不得仅由 COUNT/SUM 推断某列有无 NULL、原始类型或行数。参考：[MySQL 隐式提交语句](https://docs.oracle.com/cd/E17952_01/mysql-8.0-en/implicit-commit.html)、[MySQL Atomic DDL](https://docs.oracle.com/cd/E17952_01/mysql-8.0-en/atomic-ddl.html)、[PostgreSQL 9.2 发布说明](https://www.postgresql.org/docs/9.2/release-9-2.html)、[PostgreSQL 16 ALTER TABLE](https://www.postgresql.org/docs/16/sql-altertable.html)。

6.1 共用报告规则会送入比较工具后的直接回答路径和最终总结路径；不完整比较仍保留 `safe_report` 的有限事实报告。未完整读取的默认值、外键、触发器和其他依赖标为未知，缺项不代表不存在；迁移 SQL 只覆盖已观察到的属性，并说明属性范围不足以证明完整等价。规则也要求区分 SQL 语义与查询观察值，并遵守 PostgreSQL/MySQL DDL 的提交、回滚、表重写和锁范围；迁移 SQL 仅供人工审查，不会被执行。

## 验证与后续效果验收

`backend/tests/test_classification_actionability.py` 与 `test_compare_risk_guidance.py` 用受控 HTTP 模型通过实际 LangGraph 检查提示交付、历史去重、路由与零工具澄清、报告证据边界。这只证明图的集成，不证明真实模型遵守提示。

落地后从 `backend` 执行了以下检查：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_prompts.py tests/test_chat_graph.py tests/test_chat_api.py tests/test_compare_graph.py tests/test_compare_report_delivery.py tests/test_classification_actionability.py tests/test_compare_risk_guidance.py -q
.\.venv\Scripts\python.exe -m ruff check app/agent/prompts.py app/agent/graph.py app/agent/graph_sql.py tests/test_classification_actionability.py tests/test_compare_risk_guidance.py tests/real_model_classification_regression.py ../scripts/acceptance/classification_regression.py
.\.venv\Scripts\python.exe -m mypy --strict app/agent/prompts.py app/agent/graph.py app/agent/graph_sql.py tests/real_model_classification_regression.py
```

结果：36 passed，Ruff 通过，strict mypy 通过，runner 只做了 Python 编译检查。首次回归发现 SQL 直接回答路径不经过总结节点，因此把共用证据规则也加入 SQL/工作流准备消息后重跑通过。

## 主代理旧候选回归历史

主代理曾对前一候选复跑 47 个受影响测试模块，结果为 542 passed、0 failed、0 skipped；Ruff 对 `backend/app` 和 `backend/tests` 全量通过，strict mypy 对 `backend/app` 的 104 个源文件通过。该次门禁记录了 151 个源码路径哈希，过程中没有源码变化；回归没有调用真实模型，也没有执行容器生命周期操作。该结果保留为历史记录，不并入当前正式候选门禁计数。

## 当前正式候选主代理回归

主代理对当前正式候选完成 23 个受影响测试模块，199 passed、0 failed、0 skipped，耗时 265.09 秒；Ruff 对 `backend/app` 与 `backend/tests` 全量通过，strict mypy 对 `backend/app` 的 105 个源文件通过。门禁记录的 128 个源码路径哈希保持稳定。受控 directcompare 测试覆盖比较工具后的直接回答规则；这组回归没有调用真实模型，不构成真实效果通过。主代理复核记录见 [main-fix-review.json](main-fix-review.json)。

真实效果 runner 已接收并冻结为 10 个文件，状态为 `runner-accepted-real-effects-pending`。主代理离线门禁为 41 passed、2 skipped；两个 opt-in PostgreSQL/MySQL oracle 检查已另行通过（2 passed、0 failed、0 skipped）。Ruff 11 路径及 strict mypy 8 个源文件通过，源码保护检查稳定。详细回执见 [main-runner-review.json](main-runner-review.json)。下一步按两个独立范围运行真实模型：分类回归 18 rows、21 turns；显式 Python-only 受影响效果 36 rows、36 turns，不构成新配对全矩阵。回执确认尚未调用真实 provider；真实效果、SSE 与专项清理结论仍待采集。

根目录 `AGENTS.md` 已检查；本次只是现有功能的错误修复，没有改变功能边界或核心目录结构，因此保持不变。
