# S15 首轮真实模型对照复核

复核日期：2026-10-03。首轮 `deepseek-flash` 实际 API 对照已完成采集，机器结果 `status` 为 `incomplete`，不构成通过验收。本文记录结果边界与已确认缺陷；未改写原始 benchmark、问题集、oracle 或模型参数。

## 证据

- [首轮 benchmark 结果](benchmark-20261002T220250206579Z.json)，SHA-256：`e3ad52b468ea545af715328663b8aa036b45a9c3811b492d8bc044da798a8f51`。本轮共 120 行、60 组配对，3 次重复。
- 独立清理复核 artifact：`../../.git/acceptance/main-first-benchmark-cleanup-review.json`，SHA-256：`bb7336fbc41ba154fb719fba7ee1e528444af6d5e5dd0484aa95c75e09ab5354`。复核通过；记录的两套运行库用户计数、PostgreSQL/MySQL 目标计数均为 0。
- 原版后端源码复核 artifact：`../../.git/acceptance/main-first-benchmark-original-source-review.json`，SHA-256：`f5ec74d774069cd14cfd0fea4b60f8ee2b4d662d79f40cca12432dc4c153f51f`。复核通过，289 个源文件无 SHA 差异。

## 结果状态

| 运行版本 | 通过 | 失败 | 待人工复核 | 环境阻塞 |
|---|---:|---:|---:|---:|
| Python | 6 | 11 | 43 | 0 |
| 原版 Java | 12 | 42 | 0 | 6 |

54 组非文件配对均标记参数一致，参数失配数为 0。另有 6 组 `file_import` 因原版 OSS 环境不可用而阻塞；Python 使用 local 存储的文件运行不构成同条件对照通过。`review-required` 和失败项都不能计入通过，完整迁移验收仍未完成。

## 已确认缺陷

- **Python JOIN 结果**：六次 JOIN 运行中五次返回了额外 ID 列；四个客户及金额正确，但结果投影不符。基准中 JOIN 类仍有失败项，不能将其他重复运行折算为该行为已修复。
- **Python 拒绝场景**：6 次 `reject` case（合计 12 个 turn）出现通用英文 fallback，触发明确拒绝校验失败。该问题仍待修复和复验。
- **原版 Java 数据源定位**：成功读取 database document 时正文未附上该 API 配置的 ID 标识，模型随后会猜测 ID，可能导致工具定位配置失败。但并非每次都失败：有一次 follow-up 第二 turn 猜到真实 ID 并成功。这是对照原版的源码缺陷，不是基准通过证据。

43 个 Python `review-required` 结果尚待逐项人工复核；Python/Java 失败项也需要原因分析和修复验证。原版 Java 的 6 组文件导入阻塞须待可用 OSS 条件后再形成匹配对照。清理计数为 0 和原 Java 源文件无变化只证明环境清理及基线完整性，不改变 benchmark 的 `incomplete` 状态。
