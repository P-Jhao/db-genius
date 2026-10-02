# S14 后端运行契约

## 健康与采集路由

| 路径 | 响应 | 依赖 |
| --- | --- | --- |
| /api/health | 原 R 包装：code=200，data.status=UP，原 timestamp | 兼容入口，未更改为 ready |
| /api/health/live | HTTP200，R code=200/data.status=UP | 进程能响应 |
| /api/health/ready | 全检查 UP 时 HTTP200/R UP；任一失败 HTTP503/code=503/data.status=DOWN | database、broker 固定 checks，不输出异常正文/连接 URL |
| /api/metrics | Prometheus plaintext | 项目兼容采集入口 |
| /metrics | 同一 handler/相同正文与 content type | 采集别名，不用 R 包装 |

数据库 probe 使用 NullPool，每次 engine 在 finally dispose；检查实际 Alembic repository heads 与系统库 app.alembic_version。默认 PostgreSQL connect_timeout=3s、statement_timeout=3s、lock_timeout=3s。Rabbit 默认 connect_timeout/read_timeout/write_timeout=2s，ensure_connection max_retries=0，context release。

3s 和 2s 是分别施加的驱动 I/O 阶段预算，不能声称整个 ready 5 秒墙钟硬截止；DNS/OS 调度、协议分段及多次 SQL 可能延长。Luna healthcheck timeout=30s 是外部客户端执行预算，interval/retries 独立；不意味着服务端取消请求。真实本机 stalled AMQP 用 0.2s 设置并验证 <3s/资源释放；不是目标 Rabbit 故障环境证明。

## 指标跨进程与完整栈 epoch

固定 Linux volume root：`/var/lib/sqlchat/prometheus`。API/worker 位于独立 PID namespace，必须分目录写，不能共同使用 counter_1.db 路径。

| 服务 | PROMETHEUS_MULTIPROC_DIR | SQLCHAT_METRICS_MULTIPROCESS_ROOT |
| --- | --- | --- |
| api | /var/lib/sqlchat/prometheus/api | /var/lib/sqlchat/prometheus |
| worker | /var/lib/sqlchat/prometheus/worker | /var/lib/sqlchat/prometheus |

PROMETHEUS_MULTIPROC_DIR 必须在 Python 导入 prometheus-client 前设置。完整 stack 启动时先完成 Luna owned metrics-init，再启动两服务。两个目录必须初始化、不含 symlink；root/helper 的 shared/exclusive 生命周期 lease 防止 init 删除活服务文件。

后端锁模块 SHA：`19fbab5a03a846a059ea0d529e9c26e41fe16779d3c1b53778c125f0b8fc7f23`。API lifespan 和 worker 主/子进程持 shared lease。lease close 仅关闭 fd，不显式 LOCK_UN，以保留 prefork 继承引用。Luna init helper 先拿 `exclusive_epoch(root: Path)` 非阻塞排他锁，拿不到必须非零拒绝；只删除 api/worker 的合法 counter/histogram_<数字>.db，不递归其他目录，不删除 lifecycle lock。本后端不清理 metric files。

单服务 restart 不触发 init，不清零另一服务/本 epoch 的累计。完整停服后重新创建 stack 才开始新 epoch。collector 从固定 api/worker 目录获取 full paths，单次 public MultiProcessCollector.merge(files, accumulate=True) 汇总 counter/histogram，使用 fresh CollectorRegistry，不叠本进程 registry。重复 scrape 不写回、不增加次数。旧子 PID 文件在本 epoch 内代表累计历史，不冒充当前活跃进程 gauge。

这个方案只承诺当前 Compose 的一个 api 服务/一个 worker 服务与其 prefork children；新增独立 replica 的目录/生命周期需要单独设计。本轮不新增 pid、task、user、db、SQL 等 metrics labels。kind/tool/operation/outcome/reason 都固定枚举，不识别值统一 other。失败数据(success=False)、partial schema、timeout、cancelled、write_outcome_unknown、stale 分层；工具完整原 result 用于 outcome，不能因 bounded artifact 丢错误而计 done。

已锁 prometheus-client 0.26.0，实际 installed source 签名/SHA 见 multiprocess-source-proof.json。官方依据：https://prometheus.github.io/client_python/multiprocess/ 。本项目双服务目录层补足不同容器同 PID 文件碰撞，调用其 public merge(files) 默认 accumulate=True。

## 追踪、日志与语言

OTLP_ENDPOINT 是无 credentials/query/fragment/path 的 HTTP(S) base URL，导出 /v1/traces。采样 0..1；默认 .1。content collection 不支持，显式 true 拒绝。Resource 仅显式固定 service.name，不引入任意 OTEL_RESOURCE_ATTRIBUTES。

外部 HTTP/task 只提取 SDK 校验的 traceparent；从空 Context 开始，忽略 tracestate/baggage。publish 注入只保留受控 traceparent，并删除已有不可信 tracestate/baggage。locale 是 accepted S13 的唯一 locale header/ContextVar，在 request/task scope finally reset；业务任务 args 保持 (id, version)。旧无 header 任务遵守原默认语言。不改 fixed 中文状态/英文 metadata renderer 边界。

完整 ASGI span 等到 SSE app 返回后才结束；HTTP→chat.run→chat.graph→model/tool→database，以及 prepare/save/set_intent/finalize 的线程 context 保持。HTTP→queue.publish→celery.db_config.verify→database.schema 有同 trace ID 的父子关系。只固定 span/attribute keys，异常只 error.type，不录 events/正文/prompt/reasoning/SQL/results/header 值；task id 仅 span 关联，不作 metric label。

日志委托 accepted core.diagnostics.sanitize_diagnostic 处理 known raw/percent/quote_plus/repr/JSON 转义、URI userinfo 和正确引号边界；仅再增加 SQL/parameters/content 日志规则，不维护另一份旧脆弱 credentials regex。API startup 与 worker logger/task_logger startup 接线；已有/后来添加的 handlers 及 late extra 都经过安全 record.getMessage。异常不附 traceback/provider body。

OTLP exporter timeout=3s，shutdown force_flush 等待预算 1000ms，属于 best effort；不保证退出时全部送达，也不声称 SDK 内部网络/线程完整墙钟硬截止。lease close 在 finally 保证。新容器实际 shutdown/export 由组合 gate 验证。

## 主代理复验入口

在 fresh accepted export 只叠 owned manifest；先按 SHA/bytes 校验并审 public-minimal.diff。已有 checks/pre-refresh evidence 保留，按具体疑点选择新 gate，避免无理由重复旧业务集合。全 app/tests Ruff；mypy app；mypy --strict --follow-imports=silent 的 28 个文件见 owned-type-files.json。新观测测试命名 test_observability*.py；队列 durable 测试为 test_celery_queue_policy.py。

可选真实 readiness 测试需要内部 SQLCHAT_TEST_PG_HOST/PORT/DB/USER/PASSWORD 和 SQLCHAT_TEST_RABBIT_URL。测试创建/精确清理随机 s14_ready_<uuid> 数据库；不重建系统 app 库。无凭据时 skip 仅说明未验，不能代替通过。运行前由 root 协调数据库窗口，本交付没有运行该用例。

最终 Linux 组合 gate 应在同一个 /api/metrics 读消费前后值，验证真实 worker done/partial/stale/error 的对应增量；两路 aliases 等价且反复 scrape 稳定。再验证单服务 restart 不重复/污染；活服务运行时 metrics-init 明确拒绝；全部停服重建新 epoch 才清零。Compose/Nginx/deploy/init helper 由 Luna 唯一维护，backend 路由/锁/依赖由本候选维护。
