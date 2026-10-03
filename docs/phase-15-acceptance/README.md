# S15 Acceptance Documentation Candidate

记录日：2026-10-03。正式文档目录为 `sqlchat/docs/phase-15-acceptance/`；本文整理最终验收状态与证据路径。完整迁移验收尚未通过。

## 证据基线

- `S`（实现及阶段证据）指向[正式 SQLChat 仓库根](../../)与该仓库已接受的 `docs/phase-*` 阶段文档；追踪表中的源码路径相对于仓库根，阶段文档路径同样从仓库根解析。
- `R`（S14 公开运行回执）位于[正式 phase-14-main 文档目录](../phase-14-main/)；追踪表中的 `R:` 文件名相对于该目录。
- `A`（S15 全量后端审计原始产物）是本地可恢复、未纳入 Git 的审计 artifact，根目录为 `../../.git/acceptance/s15-backend-final-audit-aed4e0402ef04aae97ca8e5396b8a7ac/`。首次失败运行保留在 `health-window-20261002-7f0f699e/run-aca23265460c/`，最终运行在 `health-window-20261002-7f0f699e/run-98feb6511329/`；两者不作为正式文档链接。
- S15 模型工具资料见[真实模型 README](../phase-15-real-model/README.md)、[操作说明](../phase-15-real-model/OPERATIONS.md)和[参数基线](../phase-15-real-model/PARAMETERS.md)。

## 当前验收状态

- S14 全量 stop/init/up 的部署运行门槛通过：API、Worker、前端、PostgreSQL、RabbitMQ 健康，迁移与指标初始化任务退出码为 0，就绪端点返回 200。正常运行配置恢复后仍健康，明确选择 local 文件存储并关闭临时 trace export。见 [首启回执](../phase-14-main/main-health-full-start-receipt.json) 与 [正常运行回执](../phase-14-main/main-normal-runtime-start-receipt.json)。
- 指标周期初始化清除了 API 侧 3 个、Worker 侧 5 个识别出的数据库文件，并保留两侧普通标记文件。真实 HTTP→队列→Worker trace、`fr`/`ja` 并发与后续 `en` 复位通过；Linux 上传路径和符号链接定点测试 14 通过。见 [初始化回执](../phase-14-main/main-explicit-epoch-init-receipt.json)、[trace 回执](../phase-14-main/main-trace-only-03-result.json)与 [Linux 上传回执](../phase-14-main/main-linux-upload-symlink-receipt.json)。
- S15 最终完整后端门禁**通过**：1179 通过、0 失败、5 个环境/能力 profile 跳过。Ruff、strict mypy（103 个源文件）、broker unavailable、部署契约 4 项均通过，791 个源文件守卫保持。见 [最终审查](../phase-14-main/main-backend-full-final-review.json)、[最终 pytest 日志](../phase-14-main/main-backend-full-pytest.log)、[strict mypy 日志](../phase-14-main/main-backend-full-mypy-strict.log)、[Ruff 日志](../phase-14-main/main-backend-full-ruff.log)、[broker 负向日志](../phase-14-main/main-backend-full-broker-unavailable.log)；机器可读结果为本地恢复 artifact `../../.git/acceptance/s15-backend-final-audit-aed4e0402ef04aae97ca8e5396b8a7ac/health-window-20261002-7f0f699e/run-98feb6511329/results.json`。
- 首次全量运行曾有 1178 通过、2 失败、5 跳过；两项是过时的 Oracle/SQL Server unsupported 断言。仅测试断言改为真正未知类型后，完整复跑通过，生产源文件未改。首次失败证据仍保留，不覆盖。五项跳过由独立队列、真实 Chrome/Nginx 5 项、真实重启前后 prepare/verify，以及 Linux 上传完整模块 14 项补证。见 [首次审查](../phase-14-main/main-backend-full-first-review.json)与 [最终审查](../phase-14-main/main-backend-full-final-review.json)。
- 固定 UI 指纹为 `e4a2782b8a6c148083ba68c54bd0f9d8c02e9825ea7f4cefbb7eff61a9f69d6b`。固定源码 mock-API 浏览器门禁与视觉复核通过（1 项测试、18 个场景、36 张截图、0 项 UI 断言失败、0 个页面错误）；会话历史抽屉内容可见，试用只读限制和销售入口移除场景通过。回执记载生产路径无变更、仅两项测试 fixture 有变更，阈值和截图覆盖未变。此证据不证明真实模型行为；本段是后续完整模型矩阵运行前的 UI 历史截点。首轮 44.44% 视觉失败保留为历史记录并由本次门禁结果取代当前 UI 状态，见本地 artifact `../../.git/acceptance/main-s14-runtime-1790951108308/main-ui-visual-first-review.json` 与[最终 UI 回执](../phase-15-ui/main-ui-final-review.json)。此前 4 个定点 mock UI 场景与指纹不同的旧共享工作树截图不作为此次验收证据。见 `S:docs/phase-14-deploy/ui-targeted-evidence.md`。
- 十类数据库中六类有目标真实实例证据，TiDB、Doris、StarRocks、OceanBase 只有实现/协议模拟；用户确认先按协议验收保留功能，不能将模拟记录为真实环境通过。真实 OSS/OCR 服务尚未提供。首轮、第二轮各完成一次 DeepSeek Flash 120 行/60 组机器对照，第二轮另有 138 turns，状态仍为 incomplete；修复后的 Python-only 分类与受影响效果专项是有限范围，不是新的配对矩阵。原 Java 6 条文件对照因 OSS 缺失受阻，Python 6 条 local 文件路径独立验证不构成匹配对照。见 [数据库矩阵](database-matrix.md)、[S15 模型 README](../phase-15-real-model/README.md) 与[定向运行记录](../phase-15-classification-report-fix/TARGETED-RUN-REVIEW.md)。
- 原 Java 后端 289 个源文件只读核对为 0 变化；第二轮及修复后复核均保留此历史完整性结果。完整迁移验收仍有明确未完成项，见[追踪表](traceability.md)。

## 状态词与解释

追踪表中的状态词仅使用 `spec/07-测试与验收规范.md` 规定的：`未实现`、`已实现未测`、`模拟通过`、`真实环境通过`、`失败`、`环境阻塞`。状态针对该行说明的验收范围；实现存在不等于端到端或真实模型验收完成。阶段回执、模拟 HTTP 与真实目标实例证据彼此分开。

## 2026-10-03 正式组装与真实模型状态更新

此前记录中的真实模型对照“尚未运行”描述的是当时状态。本次 `deepseek-flash` 实际模型对照现已完成采集，共 120 行、60 组配对；机器记录仍标记 `incomplete`，因为验收结果包含失败和待人工复核项。Python 为 11 失败、43 待人工复核、6 通过；Java 为 42 失败、12 通过、6 组文件导入环境阻塞。54 组非文件配对的参数均匹配，参数失配为 0；6 组 `file_import` 因 Java OSS 环境不可用而无法形成匹配结果，Python local 文件运行不计作匹配通过。详见[真实模型基准记录](../phase-15-real-model/benchmark-20261002T220250206579Z.json)。

正式组装已从冻结基线 `cbe4815f1aa7ac7c266040f69f9231f8487bafbd` 完成 835 个目标文件的 root 复核：835/835 匹配、273 个后端路径 0 处不匹配、前端源码指纹为 `e4a2782b8a6c148083ba68c54bd0f9d8c02e9825ea7f4cefbb7eff61a9f69d6b`、配置私有值匹配数为 0；717 个文件写入、118 个未变、2 个 draft 隔离。正式记录见[组装审查](main-assembly-review.json)。

对应提交为 `a55adb29eacebdb6881dc8bdf8a85e276e68286e`（旧数据库注册断言修正）、`710e048c3c5981fbfd002c0440a6a4b19880df99`（部署与跨进程监控）、`f2cbd4f47747fae0a9beb2f24dad7bbbc38bed0d`（固定源码 UI fixture 与截图稳定性测试）和 `c4ec379c9e23b0db135b7f85f094d47e40ea81da`（验收与组装证据文档）。正式代码组装已完成；真实模型结果仍未通过验收，不能据此宣布完整迁移通过。

首轮真实模型对照已发现待修复的 JOIN 结果差异、Python 拒绝场景英文 fallback 与原版 Java 配置定位缺陷；43 个 Python 结果还需人工复核，6 组 Java 文件导入需 OSS 条件才能匹配。详细分类与清理/源码完整性证据见[首轮真实模型复核](../phase-15-real-model/FIRST-RUN-REVIEW.md)。

## 2026-10-03 Compare preflight 受控修复门禁

提交 `9c077413105a9ec3236416f21b83b4fae18753bb` 经主代理审查，受控门禁状态为 `controlled-regression-accepted-real-model-pending`。初轮 38 模块回归启用真实 PostgreSQL、MySQL、MongoDB 目标，共 329 passed、1 failed、0 skipped；单一失败是旧测试措辞断言。初轮失败日志继续保留：[初轮 pytest 日志](../phase-15-classification-report-fix/pytest-compare-preflight-initial.log)。只调整两处测试措辞后，另行复测 3 模块为 23 passed、0 failed、0 skipped，生产源码哈希与初轮一致。两组结果不可加总，也不表示修正措辞后的 38 模块完整复跑通过。

最终 Ruff 全量 `app`/`tests` 通过，strict mypy 106 个生产文件通过。提交范围为 19 个文件（4 个生产源码、15 个测试）；compare-preflight 实现涵盖真实只读结构差异执行、分页、七种语言的上下文容量估算和受控安全 SSE 边界。原 Java 源文件 289 项只读核对无变化，两个 AGENTS 文件未改。证据及根审查哈希见[受控修复审查 JSON](../phase-15-classification-report-fix/main-preflight-fix-review.json)；3 模块复测日志见[复测 pytest 日志](../phase-15-classification-report-fix/pytest-compare-preflight-assertion-recheck.log)。

此处受控门禁本身不包含部署或真实 provider 复跑。准备 V4 文档时主代理另行报告定向部署已完成，两个新真实模型专项刚启动且当时尚无终态；这些后续运行回执不属于本候选门禁记录。历史 120 行/60 组矩阵仍为 incomplete，57 turn 答案复核中的失败、事实问题和 metadata 措辞记录保持原状态。该门禁只覆盖受控实现与回归范围，不代表 F-10 全量验收、真实模型效果或完整迁移/最终答案通过。

## 修复后定向真实模型结果

已接受产品修复基线 `3b97ad1bc5c332070d624b037ff6162fd6ad2b7d` 的历史受控回归为 23 个测试模块 199 passed、0 failed、0 skipped；Ruff 全量 app/tests、strict mypy app 105 个源文件通过，128 个源码路径哈希稳定。该回归只绑定此固定基线，不覆盖后续 compare 编排候选。正式效果 runner 的独立离线门禁为 41 passed、2 个 opt-in 数据库 oracle 检查补跑后 2 passed、0 failed、0 skipped；Ruff 11 路径、strict mypy 8 个 helper 源文件通过，目标后端 140 个路径守卫稳定。部署候选 API/Worker/前端镜像、readiness 与健康检查通过；这些证据证明受控实现和运行基线，不证明真实模型行为。

随后两个真实 provider 专项以 `bb589d48b91dc96cc3c0039105056019be5ccad0` 为运行源 HEAD，前后 runtime 稳定。Python-only 分类回归 18 rows/21 turns 状态为 `review-required`（6 passed、12 review-required、0 failed）；显式 Python-only 受影响效果 36 rows/36 turns 状态为 `failed`（1 failed、35 review-required，失败为 PostgreSQL compare 第 3 次重复无结构差异工具结果）。两组并行运行，不是性能基线，也不是新的 Java/Python 配对 120 行矩阵。主代理独立复核绑定 57 个 turn 的定位符、状态和答案 SHA，确认 1 项任务失败、7 项答案事实问题及 1 项准备 metadata 措辞问题；这份部分复核不代表最终答案整体验收。原 Java 失败及 OSS 阻塞不改写。上述证据没有使完整迁移验收通过。raw scopes 与[修复后定向结果记录](../phase-15-classification-report-fix/TARGETED-RUN-REVIEW.md)已随提交 `db409e9` 固定。另见[当前答案复核记录](../phase-15-classification-report-fix/main-current-answer-findings.json)、[分类修复复核](../phase-15-classification-report-fix/main-fix-review.json)、[runner 回执](../phase-15-classification-report-fix/main-runner-review.json) 与 [runtime 回执](../phase-15-classification-report-fix/main-runtime-review.json)。

## 2026-10-03 后续 compare-preflight 证据

V4 截止后新增的定向部署已通过应用健康、迁移版本和指标 epoch 独立检查及 141 个源码映射路径检查；四个命名卷、受保护容器及前端镜像保持。该部署未重跑 clean-start、整栈启停、T-33 或 T-34 门禁，这些范围仍由既有 S14 回执支撑。此后两项新的 Python-only provider 运行已终态，machine status 均为 `review-required`：分类 18 rows/21 turns（6 passed、12 review-required、0 failed），受影响效果 36 rows/36 turns（36 review-required、0 failed）。这两项运行与本 README 上述较早结果分开记录，不得合并或覆盖原件。

独立答案复核覆盖新两项运行的 57 turns：29 supported、13 factual-claim-failure、1 task-failure、14 wording。措辞 turn 不计失败；根代理确认 14 个 failure findings 与 1 个 wording finding。最终答案与完整迁移均未接受。公开 JSON、SHA-256 和部署/机器/人工结果的证据边界见[新一轮复核记录](../phase-15-classification-report-fix/FRESH-PREFLIGHT-REVIEW-20261003.md)。
