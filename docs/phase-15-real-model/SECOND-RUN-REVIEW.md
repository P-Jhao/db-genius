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

## 人工答案复核与待调查问题

两份私有人工复核草稿均为 `draft-only` 且 `rootPass=false`：第 1 批覆盖第 1–40 行、46 个 turn；第 2 批覆盖第 41–110 行、81 个 turn，合计覆盖 110 行、127 个 turn。第 111–120 行不在这两批草稿中，且尚无最终人工结论；本文不采用草稿中的逐项判定，也不标记整体人工复核通过。PostgreSQL rewrite/rollback/precision 整数位、MySQL DDL 回滚承诺，以及 PostgreSQL repair 第 3 次重复中对 NULL 的否定，均仍需结合原始证据核实，不能当作已证实的正确答案或行为。

## 后续验收边界

本轮固定矩阵只覆盖 PostgreSQL 与 MySQL；TiDB、Doris、StarRocks、OceanBase 的协议测试状态仍不代表真实实例验证。真实 OSS/OCR 服务未配置，OSS 六组阻塞只有在取得可用服务条件并完成等价对照后才能解除。修复后应以新候选复测受影响场景，并按需要重跑完整矩阵；保留首轮与本轮原始证据作为历史记录。新的运行仍须明确记录参数可比性、最终人工答案结论、原版 OSS 条件、清理计数和原版源码完整性；健康检查、受控模型回归及数据库 fixture 不替代真实 provider 效果验收。
