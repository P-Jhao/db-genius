# S15 分类与报告证据修复

## 范围与来源

第二轮固定矩阵已完成 120 行、138 轮，原始结果保留。初始隔离补丁来自 `.git/acceptance/s15-clarification-fix-20261003/candidate.patch`，涉及分类提示、图路由与 SQL 图。已接受产品修复基线涉及 `backend/app/agent/{graph,prompts,graph_sql,report_rules}.py`，并新增三项受控测试：`test_classification_actionability.py`、`test_compare_risk_guidance.py` 和 `test_compare_direct_report_rules.py`。原 120 组用例、oracle、模型参数、prompt 资源和 Java 参考项目未改。修复后真实效果专项现已采集，但仅是 Python-only 定向范围；分类结果仍为 review-required，受影响效果结果有一项失败，尚不能宣称线上误路由或报告失真已被完整修复验收。

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

## 已接受产品修复基线的历史主代理回归

主代理对已接受产品修复基线 `3b97ad1bc5c332070d624b037ff6162fd6ad2b7d` 完成 23 个受影响测试模块回归，199 passed、0 failed、0 skipped，耗时 265.09 秒；Ruff 对 `backend/app` 与 `backend/tests` 全量通过，strict mypy 对 `backend/app` 的 105 个源文件通过。门禁记录的 128 个源码路径哈希保持稳定。这项历史回归绑定该固定基线，不覆盖后续新增的 compare 编排候选。受控 directcompare 测试覆盖比较工具后的直接回答规则；这组回归没有调用真实模型，不构成真实效果通过。主代理复核记录见 [main-fix-review.json](main-fix-review.json)。

真实效果 runner 已接收并冻结为 10 个文件，状态 `runner-accepted-real-effects-pending` 是其接收时回执中的状态。主代理离线门禁为 41 passed、2 skipped；两个 opt-in PostgreSQL/MySQL oracle 检查已另行通过（2 passed、0 failed、0 skipped）。Ruff 11 路径及 strict mypy 8 个源文件通过，源码保护检查稳定。详细回执见 [main-runner-review.json](main-runner-review.json)。其后两个独立 Python-only 真实模型范围已运行：分类回归 18 rows、21 turns，6 passed/12 review-required/0 failed，整体 `review-required`；受影响效果 36 rows、36 turns，35 review-required/1 failed。后者失败为 PostgreSQL compare repetition 3 未取得成功工具调用和结构差异结果。完整结果见 [TARGETED-RUN-REVIEW.md](TARGETED-RUN-REVIEW.md)，原始 JSON/JSONL 与两份主代理数值/清理源码复核回执随 `db409e9` 固定。主代理独立人工复核另见 [main-current-answer-findings.json](main-current-answer-findings.json)：57 个 turn 的 locator/status/答案哈希均已绑定，确认 1 项任务失败、7 项答案事实问题和 1 项准备 metadata 措辞问题；该记录不整体采纳其他措辞建议，也不代表最终答案通过。两组并行运行，不构成新配对全矩阵或性能 baseline；最终答案未获接受，compare 工具调用失败和已确认答案事实问题仍待修复并以新证据复验。主代理复核记录指出完整迁移与最终答案均未接受；SSE/runtime、usage、清理与源码证据分别见 [main-current-real-effect-numeric-review.json](main-current-real-effect-numeric-review.json) 和 [main-current-real-effect-cleanup-source-review.json](main-current-real-effect-cleanup-source-review.json)。

## 2026-10-03 V5 fresh run 与独立答案复核

以下为 V4 截止后新启动的运行，不能与上方 `20261003044921Z` 的旧专项合并。分类 run `classification-20261003092425Z` 为 18 rows/21 turns、6 passed、12 review-required、0 failed、69 model calls，整体 `review-required`；受影响效果 run `affected-python-20261003092425Z` 为 36 rows/36 turns、36 review-required、0 failed、120 model calls，整体 `review-required`。两次运行的 runtime fingerprint 均稳定；这些 machine 状态不是答案通过结论。

根代理另行复核两项新运行合计 57 个 turn，29 个 supported、13 个 factual-claim-failure、1 个 task-failure、14 个 wording-only turns。14 个措辞 turn 不计失败；15 个 accepted findings 中 14 个为失败 findings、1 个为措辞 finding。复核绑定所有 turn 的 locator 和答案 SHA，并独立核对 189 次 provider usage、运行状态与执行检查；六项 compare 分页均由两页结果合并得到完整结果，且没有执行 migration SQL。最终答案和完整迁移均未接受，14 个 failure findings 保持待修复。具体 machine/human 边界及回执哈希见[新一轮复核记录](FRESH-PREFLIGHT-REVIEW-20261003.md)。四份新 run JSON/JSONL 保留原字节并列于同目录。

## 2026-10-03 Compare preflight 受控修复交接

受控实现提交为 `9c077413105a9ec3236416f21b83b4fae18753bb`（`fix: 保障结构对比执行与报告证据边界`）。新增的 `backend/app/agent/compare_preflight.py` 纳入 F-10 实现路径；候选还包括真实只读结构 diff 执行、分页、七种语言的上下文容量估算，以及受控验证过的安全 SSE 报告边界。主代理审查范围为 19 个文件（4 个生产源码、15 个测试），并确认原 Java 289 个源文件只读核对 0 变化；这些结论只绑定此提交和受控测试范围。

初轮真实 PostgreSQL/MySQL/MongoDB 目标启用的 38 模块回归为 329 passed、1 failed、0 skipped。唯一失败位于 `tests/test_classification_actionability.py::test_explicit_sql_without_confirmation_routes_and_executes`，原因是断言仍要求旧共享证据规则文案。初轮日志原样保留于[pytest 日志](pytest-compare-preflight-initial.log)。只修改两处测试措辞后，相关 3 模块复查为 23 passed、0 failed、0 skipped；生产源码哈希与初轮相同，日志见[措辞修正后复测](pytest-compare-preflight-assertion-recheck.log)。两个结果是不同范围，绝不能加总成 352 passed 或描述为一次全量 330 项通过；也没有证据称修正措辞后再次完整运行了 38 模块。

最终 Ruff 全量 `app`/`tests` 通过，strict mypy 106 个生产文件通过。根主审状态为 `controlled-regression-accepted-real-model-pending`。审查 JSON [main-preflight-fix-review.json](main-preflight-fix-review.json) 保留原 review 正文并附代码提交与 root 证据哈希；两个 pytest 附件已作敏感内容扫描，0 检测命中。

该受控门禁本身未触发部署或真实 provider 调用。主代理其后另行报告定向部署已完成，并启动两个新真实模型专项，但当前尚无终态；该 runtime 与新运行证据不属于本节门禁记录。历史 120 行/60 组矩阵与 57 turn 答案复核未改写，原记录的 1 项任务失败、7 项答案事实问题、1 项 preparation-metadata 措辞记录保持原状态；完整迁移和最终答案仍未接受。

根目录 `AGENTS.md` 已检查；本次只是现有功能的错误修复，没有改变功能边界或核心目录结构，因此保持不变。
