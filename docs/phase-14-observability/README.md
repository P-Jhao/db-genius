# S14 Health, Metrics, and Tracing Handoff

记录日：2026-10-02。本文面向正式目录 `sqlchat/docs/phase-14-observability/`，描述已验收 Compose 候选的运行约束与观测数据生命周期。实现位于[SQLChat 仓库根](../../)；关键文件为 [`docker-compose.yml`](../../docker-compose.yml)、[`observability_multiprocess.py`](../../backend/app/core/observability_multiprocess.py)、[`observability_metrics.py`](../../backend/app/core/observability_metrics.py) 和 [`run_worker.py`](../../backend/deploy/run_worker.py)。公开运行回执与 S14 部署文档位于 [phase-14-main](../phase-14-main/)。完整后端原始审计是本地可恢复、未纳入 Git 的 artifact，路径为 `../../.git/acceptance/s15-backend-final-audit-aed4e0402ef04aae97ca8e5396b8a7ac/`。

## 运行拓扑与约束

- 一套 Compose 栈运行一个 API 服务容器和一个 Worker 服务容器。SQLChat 的 `AGENTS.md` 明确此约束：未改变指标 PID 隔离设计前，不增加同角色副本。
- API 和 Worker 把同一个 named volume `metrics_multiprocess_data` 挂到 `/var/lib/sqlchat/prometheus`。容器各有独立 PID namespace，因此写入不同子目录：`api/` 与 `worker/`。API 以 `PROMETHEUS_MULTIPROC_DIR=/var/lib/sqlchat/prometheus/api` 初始化 Prometheus client；Worker 使用 `/var/lib/sqlchat/prometheus/worker`。两者接收共同 root `SQLCHAT_METRICS_MULTIPROCESS_ROOT=/var/lib/sqlchat/prometheus`。
- `GET /api/metrics` 通过服务聚合器读取两个角色目录，将 counter/histogram 序列合并为 Prometheus 文本。角色目录避免两个容器各自的 PID 1 写入相同指标文件；不能把它们合并成一个 writer 目录。
- 指标 label 为有限枚举或 `other`；不包含 taskId、userId、SQL、模型文本、数据库结果或 URL。缺少供应商 usage 时只记录模型调用，不推算 Token。

核心实现：[`docker-compose.yml`](../../docker-compose.yml)、[`observability_multiprocess.py`](../../backend/app/core/observability_multiprocess.py)、[`observability_metrics.py`](../../backend/app/core/observability_metrics.py)、[`observability_metrics_lock.py`](../../backend/app/core/observability_metrics_lock.py)、[`run_worker.py`](../../backend/deploy/run_worker.py)。

## 指标文件与完整周期

共享卷结构：

```text
/var/lib/sqlchat/prometheus/
  .lifecycle.lock
  api/counter_<pid>.db
  api/histogram_<pid>.db
  worker/counter_<pid>.db
  worker/histogram_<pid>.db
```

Compose 的 `metrics-init` 是一次性初始化服务，先成功退出后 API 和 Worker 才能启动。它运行 `backend/deploy/init_metrics.py`，对共享 root 获取 exclusive lifecycle lock，再检查 `api/`、`worker/`，仅移除严格匹配 `counter_<数字>.db` 或 `histogram_<数字>.db` 的旧文件。初始化器拒绝相对 root、目录/指标文件符号链接与无效路径；普通 marker、未知文件、嵌套目录和 `.lifecycle.lock` 不在删除范围。

API 与 Worker 初始化观测时各自取得 shared lifecycle lease。因此任一服务存活时，初始化器都拿不到 exclusive lock，必须失败而不能清理活跃指标。`metrics-init` 不是单服务重启 hook。只有确认 API 和 Worker 均已停止后显式开始新的完整指标 epoch，才允许初始化器清理已知指标文件。

S14 主代理实际执行的 epoch 初始化成功：API 侧移除 3 个、Worker 侧移除 5 个识别文件；两侧普通标记文件哈希不变。完整 `stop/init/up` 后迁移与初始化退出码为 0，API、Worker、前端、PostgreSQL、RabbitMQ 全部 healthy，就绪端点 HTTP 200。见 [epoch 初始化回执](../phase-14-main/main-explicit-epoch-init-receipt.json)与[全栈健康回执](../phase-14-main/main-health-full-start-receipt.json)。

## 单服务重启的实际保留语义

单独重启 API 或 Worker 时不要运行 `metrics-init`，也不要清空共享卷。本次真实 Compose 回执为：

- API 确认重启，Worker 启动时间未变；18 个 counter series 逐一比较，`counterDiffs` 为空，`initializerNotInvoked=true`。
- Worker 确认重启，API 启动时间未变；同样检查 18 个 series，`counterDiffs` 为空，`initializerNotInvoked=true`。
- 单服务重启仍处于当前 metrics epoch。该角色沿用原容器 PID namespace 的 PID 文件，另一角色目录的序列保持；不会因单服务启动清零，也不会重复累计已存在历史。

实际回执：[API 单服务重启](../phase-14-main/main-api-single-restart.json)与[Worker 单服务重启](../phase-14-main/main-worker-single-restart.json)。同 PID 两角色并发写入、API/Worker 各自重启后打开原 PID 文件、跨目录聚合由 [`test_observability_multiprocess.py`](../../backend/tests/test_observability_multiprocess.py) 验证。完整 epoch 的精确删除范围由 [`test_deploy_metrics_init.py`](../../backend/tests/test_deploy_metrics_init.py) 与 [`test_observability_metrics_lock.py`](../../backend/tests/test_observability_metrics_lock.py) 验证。

文件、会话、token 使用量的真实服务重启持久性是另一条证据，见 [持久化回执](../phase-14-main/main-persistence-receipt.json)。它由 PostgreSQL 与上传存储持久化保证，不能与 Prometheus metrics 文件保留混为一谈。

## 健康、追踪与日志

- `GET /api/health` 保持原 R 包装；`GET /api/health/live` 提供存活状态；`GET /api/health/ready` 检查系统数据库 Alembic head 与 RabbitMQ 可达性，成功 HTTP 200、失败 HTTP 503，不返回连接 URL、凭据或异常正文。
- OTLP 默认关闭；启用时 endpoint 必须是无凭据、query 与 path 的 HTTP(S) base URL。采样率范围校验；`SQLCHAT_OBSERVE_CONTENT=true` 会被拒绝。本阶段不采集 prompt 或业务内容。
- W3C `traceparent` 从 HTTP 请求进入聊天与工具链；Celery 验证任务沿用 trace context、用户标识和请求语言。span 用固定名称，taskId 只作为 span 属性而非 metric label；不附加 prompt、SQL、结果、密钥或异常文本。
- 日志过滤器清除 traceback、SQL/参数块、带认证 URL 和常见密钥字段。生产代理关闭 SSE buffering；keepalive 注释不改变 POST 路径或 data event 协议，断连触发共享取消并等待 producer 收尾。

实现与测试：[`observability_health.py`](../../backend/app/core/observability_health.py)、[`observability_tracing.py`](../../backend/app/core/observability_tracing.py)、[`observability_logging.py`](../../backend/app/core/observability_logging.py)、[`test_observability.py`](../../backend/tests/test_observability.py)、[`test_observability_tracing.py`](../../backend/tests/test_observability_tracing.py)、[`test_observability_security.py`](../../backend/tests/test_observability_security.py)、[`test_observability_lifecycle.py`](../../backend/tests/test_observability_lifecycle.py)、[`test_deploy_persistence.py`](../../backend/tests/test_deploy_persistence.py)。

## 结果与限制

最终后端候选 manifest SHA `8f49dff0680400dc084da8aaa2da5596377b3b4db2c0b71d537a520ca50f1709`：1179 passed、0 failed、5 个受控 profile/capability skips；Ruff、strict mypy（103 个源文件）、部署契约 4 项及 broker-negative 1 项通过，791 个源码守卫保持。五项跳过分别由独立队列运行、真实 Chrome→Nginx 5 项部署测试、重启前后 prepare/verify、Linux 上传模块 14 项通过补证。见[公开最终审查](../phase-14-main/main-backend-full-final-review.json)、[公开 pytest 日志](../phase-14-main/main-backend-full-pytest.log)、[公开 Ruff 日志](../phase-14-main/main-backend-full-ruff.log)、[公开 strict mypy 日志](../phase-14-main/main-backend-full-mypy-strict.log)与[broker 负向日志](../phase-14-main/main-backend-full-broker-unavailable.log)。机器可读最终结果为本地恢复 artifact `../../.git/acceptance/s15-backend-final-audit-aed4e0402ef04aae97ca8e5396b8a7ac/health-window-20261002-7f0f699e/run-98feb6511329/results.json`。

真实 OTLP collector/Jaeger 未接入；横向增加 API/Worker 副本未在本拓扑支持。旧的“Prometheus 仅单进程内存 registry”描述不适用于此候选：当前部署使用共享 multiprocess volume 和角色目录。`../../AGENTS.md` 单 API + 单 Worker 约束继续有效；本文不修改 AGENTS 或功能边界。
