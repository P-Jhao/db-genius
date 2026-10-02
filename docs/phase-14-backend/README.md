# S14 backend 冻结候选

基线：`93175f927beb517beb8992b3ade3486d0a7abf53`。本目录是独立 accepted export 的候选交付，尚未由主代理接受。保留此前 accepted native、SQL repair、C09 metadata/queue diagnostics、S13 DSML/locale、S11/Mongo 与 S05 partial/version/delete；新增 graph/OCR 类型边界直接继承最新基线。

本次交付 30 个 code/test/dependency 文件：12 个已有文件的最小差异、7 个观测模块、11 个测试。`public-minimal.diff` 仅含已有 owned 文件；`owned-files.json`、`manifest.json` 列完整交付。711 个非 owned accepted 文件见 `nonowned-guard.json`。部署/UI、registry/types/adapter、Workflow、graph/streaming、diagnostics helper、db_config_common 保持原字节/归一化内容。未执行共享覆盖、Git 写操作或容器生命周期操作。

## 行为与所有权

| 文件/接口 | 增量 | 保留的关键规则 |
| --- | --- | --- |
| main/api.system/config | API logging/tracing 生命周期、live/ready、两个 metrics 路径、明确观测配置 | 原路由和 R 包装、校验/BusinessError handler、原初始化流程 |
| api.chat/agent.tools | chat/graph/model/tool/persistence spans，固定 outcome 计数，实际可见首块 | 原模型参数、S08 保存/取消顺序、S09 输出限额、DSML 与修复边界 |
| services.database_tools | 一个 import，get_schema/_execute 两个 decorator | 原函数 body AST 全部相同；归属/权限、同一解密 config、Oracle catalog 桥、返回/异常对象、调用次数 |
| db_config enqueue/worker/tasks | publish→worker→schema spans；done/partial/stale/error；S13 locale headers；worker 启动日志 | id/version 参数、版本隔离、删除后回调、partial 可 connected、accepted 脱敏诊断 |
| celery_app | durable control/event queues，固定 traceparent 注入、进程生命周期 lease | 原 publish 不重试、序列化/prefetch；原队列 TTL/expiry |
| observability_* | 低基数 Prometheus、内容隔离 OTLP、诊断清理、双目录进程聚合/锁 | 不采集 prompt/reasoning/SQL/业务结果/异常正文，不增加业务驱动查询 |

`scope-proof.json` 提供 database_tools AST 和 db_config 除 _enqueue 之外所有函数 AST 守卫。worker 的 metadata wrapper 执行同一 extract_metadata 一次；没有重取元数据。

## 已完成验证

| 证据 | 结果 | 层级 |
| --- | --- | --- |
| checks.json，8dac fresh 受影响 worker hook | Ruff；mypy 103；owned strict 28；43 passed / 0 skipped / 18.34s | SQLite、mock/契约；源码 SHA 与本候选一致 |
| pre-refresh-checks.json | 72 passed / 0 skipped / 33.20s | 已完成取消/compare/Oracle bridge/输出/参数/partial/locale/multiprocess 联合回归；保留、不重复 |
| pre-refresh-checks.json.completedAffectedGate | 16 passed / 0 skipped / 21.05s | traceparent-only、固定 Resource 后的真实本机 OTLP HTTP/protobuf 与生命周期；模拟 namespace PID/锁边界 |
| type-refresh-checks.json | 最新类型基线的 Ruff、普通 mypy app、owned strict 28 | 不重复旧业务 gate；以其 complete/exitCode 为准 |
| lock-check.json/dependency-proof.json | uv lock --check；134 个旧 package 版本全部保留，4 direct 观测依赖/11 新 package | 锁定解析，不安装共享环境 |
| main-linux-lock-receipt.json | fork inherited close、独立子 lease、live-init 拒绝、最后关闭后新 epoch 通过 | 主代理真实 Linux 标准库内核锁探针；旧镜像只当 Python 运行时 |

这些集合有重叠，不能相加成独立通过总数。历史 preparatory 59 passed 位于最终 tracestate/Resource 修复之前，仅留阶段记录。已有 gate 的 acceptedBase 不改写；`accepted-refresh.json` 证明最新变化仅非 owned graph/OCR 类型注解，30 个交付源码与 gate SHA 匹配。

新依赖镜像的 Compose build/clean migration、真实 Rabbit4.3.6 prefork Worker、同一 /api/metrics 的真实 task 增量、服务 restart/完整 stack epoch、Nginx SSE 仍由主代理在最终组合镜像验收。本候选没有拿旧 S14 应用镜像代替。可选 test_observability_integration.py 的真实 PG/Rabbit 用例本轮未运行，不将其 skip 算通过。真实 Flash 效果仍属 S15。

## 规格路径矩阵

| 用例 | 后端路径 | 本轮证据 | 组合部署尚需 |
| --- | --- | --- | --- |
| T-31 七语言请求/异步语言链 | accepted S13 Accept-Language/request_locale scope→enqueue locale header→worker locale_scope/finally reset | accepted S13 七语契约；S14 fr/ja 并发、旧无 header 默认与异常后 ContextVar reset | 组合镜像真实 Worker 的语言继承/并发及默认边界，不能以模拟替代 |
| T-32 干净部署/升级 | dependency lock、main startup、migration_ready | 锁版本守卫、迁移 heads 匹配/不匹配、失败释放 engine | 干净 Linux 镜像构建、真实迁移/readiness |
| T-32 队列消费/重启 | enqueue→Celery headers→verify worker | 参数/locale/trace parents；full/partial/stale/error 与回调 rowcount | Rabbit4.3.6、真实 prefork 消费、restart 持久化 |
| T-33 SSE/断连/并发 | ASGI 完整流 span、chat/cancel/persistence、keepalive | mock HTTP 图、SSE 生命周期、原取消/保存联合回归 | Luna Nginx、长请求并发与代理断连 |
| T-34 日志/指标/追踪 | 安全 LogRecord、跨目录 metrics、OTLP HTTP | raw/encoded/dict/header/extra；两目录同 PID 并发/restart/重复 scrape；protobuf 无非受信 trace_state；线程 parent；Linux fork lease | 组合镜像同一 API scrape 观察真实 worker done/partial/stale/error 增量及 init 拒绝 |

AGENTS 根/仓库均检查；功能边界和核心目录未变，保持不修改。
