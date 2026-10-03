# 修复后定向真实模型专项记录

记录日期：2026-10-03。产品修复代码基线为 `3b97ad1bc5c332070d624b037ff6162fd6ad2b7d`；专项运行及 runner 源 HEAD 为 `bb589d48b91dc96cc3c0039105056019be5ccad0`。两组运行前后 HEAD 与 runtime 指纹均稳定，API 镜像为 `sha256:1858ecb48c85b0c3a5a4d3035ddb616fc615068e64da24017f455ec1579431ff`。两个专项并行执行，不构成延迟/性能 baseline 对照。

## 分类专项

这是 Python-only 分类回归，18 rows、21 turns。机器状态为 `review-required`：6 rows passed、12 rows review-required、0 failed。原始 JSON SHA-256 为 `5ec9063ff6b3b7ea8439f618acdf1efaa99d691db8e68bfd378f72b8ba6fcb63`，JSONL SHA-256 为 `072dc39311410ca0bc44b6b295445109a647f9351fd14092bc8957c35f18651e`。证据：[分类 JSON](classification-20261003044921Z.json) 与 [分类 JSONL](classification-20261003044921Z.jsonl)。

## 受影响效果专项

这是显式 Python-only 受影响效果回归，36 rows、36 turns；整体机器状态为 `failed`，其中 35 rows review-required、1 row failed。唯一失败位于 PostgreSQL compare 第 3 次重复：没有成功工具调用，且 `requiredTools` 与 `comparisonDirectionAndChanges` 检查未通过，未取得结构差异报告。原始 JSON SHA-256 为 `fa62568aa99a57e878be5fc82136c5ebab42faa5522f62f2f2d41bf2d7416301`，JSONL SHA-256 为 `5e2049864aa4d89c5fe3598e6417583a112d1a1da0565c0b252b255207edfc03`。证据：[受影响效果 JSON](affected-python-20261003044921Z.json) 与 [受影响效果 JSONL](affected-python-20261003044921Z.jsonl)。

## 独立完整性与验收边界

主代理数值复核状态为 `integrity-passed-one-behavior-failed`，绑定同一运行 HEAD，并确认完整迁移及最终答案均未获接受；见[主代理数值复核](main-current-real-effect-numeric-review.json)。独立清理/源码复核状态为 `passed`：两套系统用户计数与两个目标计数均为 0，原版 Java 289 个源文件无哈希差异；见[清理与源码复核](main-current-real-effect-cleanup-source-review.json)。

主代理与 6.1 对答案和通用 compare 编排的复核仍有三处答案叙述问题及 compare 工具链问题待修复，本文不预写最终 review 数或接受这些答案。原版 Java 历史失败及 6 组 OSS 文件环境阻塞保持原状。两个 Python-only scope 不是新的完整 120-row/60-pair 对照矩阵，不满足完整迁移验收；真实 OSS/OCR 未配置，TiDB、Doris、StarRocks、OceanBase 仍只有协议/模拟覆盖。该记录仅保存本次实际定向运行结果，后续修复须引用新的独立证据。
