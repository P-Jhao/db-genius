# S15 第二轮真实模型对照复核

复核日期：2026-10-03。第二轮使用 `deepseek-flash` 的真实 provider 矩阵已完成采集，机器报告状态为 `incomplete`，不构成验收通过。本文记录机器计数、数值完整性、参数可比性、清理与源码完整性证据，以及仍待完成的答案复核；不改写 benchmark、JSONL、问题集、oracle 或模型参数。

## 证据

- [第二轮 benchmark 结果](benchmark-20261003T022312342Z.json)，SHA-256：`8e3076a0b347a4d77f3a8f1eaac6501851879ed3e38e953893e47439cf965411`。JSONL 与汇总报告匹配；本轮 120 行、60 组配对、138 个 turn。
- [主代理数值复核](main-second-run-numeric-review.json)，SHA-256：`FBA784585131DE3D7A4375580156B7CB59AF32FEE5F62ED59BD6589DB1E08FE7`。报告中 API usage 不匹配 0、provider 调用错误 0；候选提交为 `49bdaffc2400bf4d9b0de0e56b67314f518b9ec9`。
- [清理复核](main-second-run-cleanup-review.json)，SHA-256：`6351D15E0F906315BB4AF98B85DB2C12609BF0E4512D22DC0657024BE3163F8D`。两套运行库用户计数为 0，PostgreSQL/MySQL 目标数据库及角色计数均为 0。
- [原版源码复核](main-second-run-original-source-review.json)，SHA-256：`137B329BBDF8D8373CD7802AD918D1223DF2F55AA306123854B3F12447506AE6`。原版后端 289 个源文件，SHA 不匹配数为 0。

## 结果状态

| 运行版本 | 通过 | 失败 | 待人工复核 | 环境阻塞 |
|---|---:|---:|---:|---:|
| Python | 11 | 1 | 48 | 0 |
| 原版 Java | 12 | 41 | 1 | 6 |

| 配对状态 | 数量 |
|---|---:|
| 通过 | 11 |
| 失败 | 41 |
| 待人工复核 | 1 |
| 参数不可比 | 1 |
| 环境阻塞 | 6 |

54 组非文件配对中，53 组生成参数匹配，1 组参数不可比：PostgreSQL 歧义问题第 1 次重复的初始分类调用参数匹配；Python 随后误入错误工作流，额外发出 3 次 `temperature=0.7` 的模型调用，Java 则进入澄清后结束。不能将本轮称为“0 组参数失配”。另有 6 组原版 OSS 文件链路因缺少可用服务环境而阻塞；Python 使用本地存储的运行不构成同条件文件对照通过。

机器报告中 Python 与 Java 的失败、待人工复核、参数不可比和环境阻塞项均不计为通过。虽有 11 组配对状态为 passed，本轮总状态仍为 incomplete，整体真实模型验收未完成。usage 与 provider 错误计数只能说明调用计量及请求传输记录完整，不能替代答案或行为正确性复核。

## 人工复核覆盖与已确认问题

三批私有人工复核草稿覆盖第 1–40 行（46 turns）、第 41–110 行（81 turns）和第 111–120 行（11 turns），合计覆盖全部 120 行、138 turns（Python 72，Java 66）。草稿仍为 `draft-only` 且 `rootPass=false`。主代理的独立完整性回执状态为 `integrity-only-passed`，确认原始行绑定、哈希、定位符及覆盖完整，但 `answerProposalAccepted=false`；该回执不采纳草稿逐项答案结论，也不改变本轮 `incomplete` 状态。

另有主代理独立确认的 [第二轮答案问题记录](main-second-answer-findings.json)，状态为 `confirmed-findings-not-complete-answer-acceptance`：其中 9 项是答案叙述问题，涉及 PostgreSQL numeric 扩位重写风险、事务边界和整数位计算，MySQL DDL 隐式提交与未读取的默认值/外键依赖，以及 JOIN/repair 对结果的解释；另 1 项是 PostgreSQL 歧义请求未澄清便调用工具的历史行为问题。六个 compare 案例的差异、方向、scale 和展示 SQL 正确且未执行迁移，但这些事实不使错误叙述通过；MySQL 条件 rename 只是明确标注的假设，不列为错误。具体定位符、回答片段和理由见证据文件。该记录只确认列出的发现，不代表整体人工答案通过，不改写原始机器状态或 benchmark。

## 后续验收边界

本轮固定矩阵只覆盖 PostgreSQL 与 MySQL；TiDB、Doris、StarRocks、OceanBase 的协议测试状态仍不代表真实实例验证。真实 OSS/OCR 服务未配置，OSS 六组阻塞只有在取得可用服务条件并完成等价对照后才能解除。修复后已另跑 Python-only 定向场景，后续应先解决受影响效果失败与答案叙述问题，再依据验收规范判断是否需重跑完整矩阵；保留首轮与本轮原始证据作为历史记录。新的运行仍须明确记录参数可比性、最终人工答案结论、原版 OSS 条件、清理计数和原版源码完整性；健康检查、受控模型回归及数据库 fixture 不替代真实 provider 效果验收。

## 2026-10-03 修复后定向真实效果复测

在正式修复候选 `3b97ad1bc5c332070d624b037ff6162fd6ad2b7d` 与冻结 runner 基线 `bb589d48b91dc96cc3c0039105056019be5ccad0` 上，另运行了两个互不配对的 Python-only 专项；两组运行前后 source HEAD 与 runtime 指纹稳定。分类专项为 18 行、21 turns，6 行 passed、12 行 review-required、0 行 failed，整体状态仍是 `review-required`。受影响效果专项为 36 行、36 turns，其中 35 行 review-required、1 行 failed；失败项是 PostgreSQL compare 第 3 次重复，未取得结构差异工具结果（0 次工具成功），所以没有可验收的结构报告。

这些专项不是新的 120 行/60 组 Java/Python 配对矩阵，也不解除原 Java 失败或 6 组 OSS 文件链路环境阻塞。主代理独立复核绑定 57 个 turn 的定位符、状态和答案 SHA，确认 1 项任务失败、7 项答案事实问题及 1 项准备 metadata 措辞问题；该复核不代表整体答案接受，compare 调用失败及确认的问题仍需修复和新证据。完整迁移与真实模型矩阵仍未通过；保留本节为修复后的窄范围效果记录，原第二轮历史状态与十项已确认答案问题不改写。专项原始证据和本记录随提交 `db409e9` 固定；相关文件字节与证据哈希经主代理校验。专项原始证据见 [分类 JSON](../phase-15-classification-report-fix/classification-20261003044921Z.json)、[受影响效果 JSON](../phase-15-classification-report-fix/affected-python-20261003044921Z.json) 和[当前答案复核记录](../phase-15-classification-report-fix/main-current-answer-findings.json)。

## 2026-10-03 后续 compare preflight 受控代码门禁

在本节所述第二轮模型运行后，另有提交 `9c077413105a9ec3236416f21b83b4fae18753bb` 完成 compare preflight 窄范围受控回归审查。初轮 38 模块在真实 PostgreSQL/MySQL/MongoDB 目标启用下为 329 passed、1 failed、0 skipped；失败是测试仍断言旧共享规则措辞。仅修改两处测试措辞后，复跑分类/路由相关 3 模块得到 23 passed、0 failed、0 skipped；该复查确认生产源码与初轮一致。两个计数属于不同门禁范围，不得相加；修正后的全 38 模块复跑没有证据。最终 Ruff 全量 `app`/`tests`、strict mypy 106 个生产文件通过。根审查及证据绑定见[main-preflight-fix-review.json](../phase-15-classification-report-fix/main-preflight-fix-review.json)。

该受控回归本身不执行部署或模型调用。V4 快照记录时，主代理另行报告的定向部署已完成而两个新真实模型专项尚未终态；V5 后续复核已绑定它们的公开回执。新运行结果与本文此前记录的 120 行/60 对第二轮 benchmark、20261003044921Z Python-only 专项和它们各自的人工复核互相独立，不替换或累加原始 machine status。新 proposal 的根代理 57-turn 复核见下节；旧 review 中的 1 项任务失败、7 项答案事实问题及 1 项准备 metadata 措辞记录继续作为历史 evidence 保留。

## 2026-10-03 later compare-preflight fresh runs and answer review

两项新的 Python-only provider run 在 V4 内容截止后完成。分类 `classification-20261003092425Z` 有 18 rows/21 turns，6 passed、12 review-required、0 failed、69 model calls；受影响效果 `affected-python-20261003092425Z` 有 36 rows/36 turns，36 review-required、0 failed、120 model calls。两项 machine status 均为 `review-required`，runtime fingerprint 稳定；它们不是新的 Java/Python 配对全矩阵。JSON、JSONL 与运行 SHA 保存在[后续复核包](../phase-15-classification-report-fix/FRESH-PREFLIGHT-REVIEW-20261003.md)。

根代理独立审阅了两项新运行的全部 57 turns：29 个 supported、13 个 factual-claim-failure、1 个 task-failure、14 个 wording-only turns。措辞 turn 不计失败；根接受的 finding 共 15 条，其中 14 条为失败、1 条为措辞。答案 locator/SHA、运行 raw 状态、189 次 provider usage 和执行检查均绑定；6 项 compare review 的两页数据合并后与完整结果一致，未执行 migration SQL。最终答案和完整迁移均未接受，14 个 failure findings 保持开放待修复。该结论绑定的新 frozen proposal SHA `5d6f5233eba2f2ef29d95e5afeda6332b416da40fdc12d79022b996d33ba1f11`，人工回执为 [root-final-answer-review-20261003.json](../phase-15-classification-report-fix/root-final-answer-review-20261003.json)。
