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
- 固定 UI 指纹为 `e4a2782b8a6c148083ba68c54bd0f9d8c02e9825ea7f4cefbb7eff61a9f69d6b`。固定源码 mock-API 浏览器门禁与视觉复核通过（1 项测试、18 个场景、36 张截图、0 项 UI 断言失败、0 个页面错误）；会话历史抽屉内容可见，试用只读限制和销售入口移除场景通过。回执记载生产路径无变更、仅两项测试 fixture 有变更，阈值和截图覆盖未变。此证据不证明真实模型行为；`deepseek-flash` 120 条/60 对同条件对照仍未运行。首轮 44.44% 视觉失败保留为历史记录并由本次门禁结果取代当前 UI 状态，见本地 artifact `../../.git/acceptance/main-s14-runtime-1790951108308/main-ui-visual-first-review.json` 与[最终 UI 回执](../phase-15-ui/main-ui-final-review.json)。此前 4 个定点 mock UI 场景与指纹不同的旧共享工作树截图不作为此次验收证据。见 `S:docs/phase-14-deploy/ui-targeted-evidence.md`。
- 十类数据库中六类有目标真实实例证据，TiDB、Doris、StarRocks、OceanBase 只有实现/协议模拟；用户确认先按协议验收保留功能，不能将模拟记录为真实环境通过。真实 OSS/OCR 服务尚未提供。固定 DeepSeek Flash 120 条、60 组同条件对照未运行；原 Java 6 条文件对照因 OSS 缺失受阻，Python 6 条 local 文件路径独立验证不构成匹配对照。见 [数据库矩阵](database-matrix.md) 与 [S15 模型 README](../phase-15-real-model/README.md)。
- 原 Java 后端 289 个源文件只读核对为 0 变化。完整迁移验收仍有明确未完成项，见[追踪表](traceability.md)。

## 状态词与解释

追踪表中的状态词仅使用 `spec/07-测试与验收规范.md` 规定的：`未实现`、`已实现未测`、`模拟通过`、`真实环境通过`、`失败`、`环境阻塞`。状态针对该行说明的验收范围；实现存在不等于端到端或真实模型验收完成。阶段回执、模拟 HTTP 与真实目标实例证据彼此分开。
