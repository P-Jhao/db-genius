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

# S15 阶段实施记录：完整迁移未验收

文档状态：本段状态截至 2026-10-04；记录的代码 snapshot 为 8b045ec9835bd01b39970acb0465127aa4f6785e。S15 阶段实施记录，完整迁移尚未验收。本文记录最终报告修复及后续验证，不取代 S15 全量门禁或真实模型历史记录；更完整的实施说明见[最终报告完整性修复](../phase-15-final-report/README.md)。report-rules 局部修复及 protocol 产品/测试修复均已提交并通过各自受控回归、静态检查；协议变更尚未部署或做真实 provider 复测，原 ValueError 与 paired line 83 framing 的根因未知。完整 paired baseline 已采集，Python 独立答案复核由根接受但仍有未闭合问题。Java 与整体 paired 答案尚未获主代理验收；这不表示工作仍在等待 backend61 FINAL。本文不代表答案、完整 S15 F/C/T 矩阵或完整迁移已验收。

最终 JSON envelope 只用于 `SQLNodes.summarize`；content-only `SQLNodes.decide`、既有公开 SSE 事件与 Usage 字段保持不变。`complete: true` 只表达 envelope 中的格式标志，不能证明答案事实或任务完成。修复未增加调用、自动重生成、工具重放或写操作重放；报告失败不撤销已完成写入，也不删除既有功能。

初次 57 模块门禁为 481 passed、1 failed、4 native skips，唯一失败是旧提示文案断言；pytest 日志与结果在随后的 harness `TypeError` 前已保存，原结果和旧 14 个模型失败 findings 保持不变。经批准的分类断言修复后，fresh 57 模块复验为 482 passed、0 failed、4 native skips（Oracle 3、SQL Server 1），耗时 672.70 秒；Ruff 全量 `app/tests`、strict mypy 全量 `app`（107 个文件）通过，运行期间源码守卫 0 变化。结果 JSON SHA-256：`39c75c2c0d0e04b0db4c526c41d8d93b38105f64aa85e076f97ba48a2a8f65b0`；pytest 日志 SHA-256：`bd7b1f556f9536a5b293ccd3706f533aa92a7d3a9572c4be4969cc7157cd9c85`。代码修复提交 `873a2ca0cde069220fa21a3049881fb1ddf6b31d`；2-file source guard 单独提交 `bfaa13c04cf7c2f64799ddfdbccb8d8eb053a7dd`。本门禁不包含 broker/Worker gate。

选择性 deployment 02 已接受，API image `sha256:a8061cd84b4aaa7e629474be2a23ccef2cfcd49023fb64bf24a8b50401b61df6`，Worker image `sha256:42510a82255ad5eca8b7b2fc0656de16bb16296898206f0c731d2a0372f3faf2`；142 个 source parity 文件、healthy runtime、metrics-init 与 migration one-shots 成功、4 个 volume 保留、39 个 protected container identities 未变。该部署是 selective API/Worker upgrade，未覆盖 clean-start、T-33/T-34；Alembic revision IDs、metrics epoch/multiprocess inventory 未保存。

后续 `report_rules.py` 局部修复已提交 `4e363820b4e8a61a4396a450576ab1251484e43b`，源码 SHA-256 `afeb5754c82592841567812d4347b0e9efe3628a852c83b0e0a143177afd6855`；root receipt `.git/acceptance/main-report-rules-root-gate-20261004-01/root-review.json` SHA-256 `795451fb18958ebb8841f0dd687a7c675114efab301687ef950acf73efea3b41` 接受六模块局部回归 33 passed、0 failed 和 Ruff 通过。该受控回归不证明真实 provider 改善，paired line 83 framing 仍未解决。

57-turn provider 专项终态与 evidence validator exit 0 只证明证据完整性，不表示答案通过。raw machine 分类不改写：classification 6 passed/12 review-required rows；affected 35 review-required/1 failed row，两份专项报告 runtime-stable 且 cleanup 完整。该专项的根人工复核与 backend61 对 affected 36 turns 的独立复核一致：classification 21/21 supported；affected 26 supported、9 条回答解释/无证据断言失败、1 项 task failure（line 12，原因未知）。9 条断言失败在 lines 2/14/20/26/32（unsupported absence/zero branch）、line 8（projection）、lines 24/30/36（MySQL CASCADE）。根复核回执 SHA-256 为 cb6c3642839ca27a9e663219e76f7922c9a52afc52641a586e3322223b35dad9；backend61 专项复核 proposal SHA-256 为 8b539abefb0e739ce325d4fe16f3abbabb4fcef3e9e0a5bc2145bfb234ba7eb1，README SHA-256 为 be1f542b5c1f866458cae03f0e9b6c7c8f84c2d3fa413470941c3d07d4658491。原始 provider raw、逐 turn pointer 和 answer hash 均保留且未改写；该历史专项的 answersAccepted=false、fullMigrationAccepted=false。

57-turn provider 专项的 source31 指纹与其历史冻结提交 bfaa13c04cf7c2f64799ddfdbccb8d8eb053a7dd 匹配；该结论只适用于这项冻结版本的历史专项，不描述当前 HEAD。该专项 165 个 Usage calls 计数一致；direct-authoritative/0-delta 由根复核认可，simple_chat 使用 content-only，不计作 summary_delta。协议只读诊断观察到 ValueError，但具体根因未知且未真实复现；16 个 synthetic controls 仅通过离线预期，不能代表真实故障复现。
protocol-observation 候选 manifest SHA-256 为 fca212848544d37ecc6d9db6768bf52c4966f046155f47e172daf7f7598943de，root offline 67 checks passed、5 个既有模块算法 AST equal。相关产品与测试候选经根隔离亲跑 62/62 passed（50 个实际 validator codes、8 个 stage、guard 稳定、externalAttempts=0），root receipt SHA-256 为 860de9d45161e7b714163b21f71539ba11c0d63d01656022b9651026916fe5ea，test-candidate manifest SHA-256 为 f3c55b4e1f2f4c249fff1c2b3f8069c48ce38feb139396fa0efed2a08cab8b76。正式 root 回归对 16 个模块报告 194 passed、0 failed、3 个既有 Alembic deprecation warnings、141.86 秒；之后的 62 项静态修正复验为 62 passed、0 failed，不与 194 相加。最终 root receipt SHA-256 为 2524300d0202338f6fbc45676d1b099ee2033250b5c3ee6b29912ecfe0b57b75，确认 Ruff app/tests 和 strict mypy 108 源文件通过，最终提交为 8b045ec9835bd01b39970acb0465127aa4f6785e。没有新部署或真实 provider 复测。
report-claims 候选最初审核时标记为 candidate-reviewed-not-applied；这是历史状态。其 R01–R03 三条规则与追加约束现已合入 report_rules.py，并由提交 4e363820b4e8a61a4396a450576ab1251484e43b 实施，六模块局部回归 33 passed、0 failed，Ruff 通过。真实 provider 效果仍未验证，line 12 的 R04 task failure 未解决或重写。初始审查回执 SHA-256 为 d09890670c1b6916ee127779bb6730e2dbe73d4037892e75e18a7016e36185ae。

完整 paired baseline 已完成 120 行/60 对，根回执状态 `matrix-collected-runtime-and-cleanup-verified-not-accepted`，只接受数据采集、guard 与 cleanup。Raw JSON SHA-256 `7e980428db0da00aa9acbd03747c66aee05ded492106b720019d11ff19353383`，JSONL SHA-256 `86d2b13eb1a9447cc893da96ed3994081f4c2fcbbff186c35943446b27a6fe3e`；root receipt `.git/acceptance/main-paired-terminal-root-review-20261004-01.json` SHA-256 `5399cd64389f9f20bb6865e522b6d690985960a39b3139dda37d2a2964284276`。Java 60 rows/66 turns：11 passed、43 failed、6 environment-blocked。Python 60 rows/72 turns：12 passed、47 review-required、1 failed；54/54 database oracles passed。root 配对级矩阵 audit 汇总 42 failed、1 not-comparable、6 environment-blocked、11 passed。

Python 的 60 rows/72 turns 独立答案复核为 58 supported、6 claim-correction、7 evidence-insufficient、1 task-not-delivered；根回执 SHA-256 为 0482a2063b55c51807545603dd7a0af4e9ee8a8507ae3d9c82d5b3cb58ba0d8c，接受该独立复核结论但保留未闭合问题，未改写原始 machine status。原 Python machine rows 仍为 47 review-required、12 passed、1 failed。54 个固定数据库 oracle 均与已保存的执行投影一致；line 83 主查询受支持，但最终报告因 invalid_report_envelope 未完整交付，具体 envelope 违规项未知；聚合结果不足以证明 absence/COALESCE 分支，被 allowlist 投影去除的辅助列也不证明模型未查询。该 72-turn 结论与旧 57-turn 专项的 47/9/1 不可直接比较。Java 与整体 paired 答案尚未获主代理验收，且不以等待 backend61 FINAL 为前提；答案、完整迁移和整体 S15 均未接受。
53/54 非文件 pairs 的 generation parameter profiles 相同；1 个 PostgreSQL ambiguity repetition 1 保留原 GenerationParameterMismatch / not-comparable，因为 Java/Python 分别走分类/普通调用分支、profile sets 不同，不代表参数数值被改。6 个 OSS/file pairs 在 Java 保持 blocked，Python 六个 file rows 独立。清理核查范围仅为本次 132 个 database fixtures、2 个 API sessions 及其 owned-prefix；该范围的 before/after runtime 与 owned inventory 一致，12 个 protected containers 未变，cleanup failure/unknown count 均为 0。范围外资源未穷尽，因此不作 global zero-residue 声明。Python MySQL JOIN rep2 查询正确且 streamComplete=true，但 final report framing 为 invalid_report_envelope；具体违规项未知，不将其与旧真实 ValueError 诊断混同。

S15 完整验收仍需汇总 F-01–F-19、C-01–C-09、T-01–T-38 的逐项证据和阻断项，本节不能替代完整矩阵。用户已接受 TiDB、Doris、StarRocks、OceanBase 及 OSS/OCR 链路的模拟/环境例外；应标明未获相应真实环境验证，不得把模拟写成真实通过，也不得因此删除相关能力。paired Python 独立复核已由根接受但 findings 未闭合；Java 与整体 paired 答案尚未获主代理验收，这不代表等待 backend61 FINAL。答案、完整迁移和整体 S15 均未接受。

本文仅记录阶段状态；旧失败运行、旧 14 findings 与原 Java/OSS 边界不覆盖、不合并、不重写。
