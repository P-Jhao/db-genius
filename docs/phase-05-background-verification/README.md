# S05 数据源异步验证与文档刷新

状态：已实现并通过专项真实环境验收。提交：`1071f3f`。

## 范围与契约

- F-03/F-04、T-03/T-04/T-05/T-06/T-30/T-36：`/api/db-config` 的 CRUD、同步连接测试、同步文档生成、异步刷新、文档读取和试用内置配置保护。
- `app.services.database_tools.get_schema(user_id, db_id)` 返回可 JSON 序列化的 `SchemaMetadata`；`execute_statement(user_id, db_id, statement)` 返回 `QueryResult`。两者检查配置归属和连接状态。查询执行沿用 S04 适配器的 SQL 安全、试用只读、超时与行数上限。
- 创建、编辑、刷新将状态置 0 并递增 `verification_version`，只把配置 ID 和版本发到 RabbitMQ。Worker 连接目标库、抽取完整元数据、渲染文档，再以 `id + version + status=0` 条件事务更新为 1 或 2。旧任务和删除后的回调不写回。
- RabbitMQ 发布失败将状态改为 2，并在 `statusDesc` 提供诊断；刷新接口同时返回错误。超过 `verification_timeout_seconds` 的待验证配置在读取时转为可见失败，覆盖 Worker 被终止等无回调情形。
- 试用模式在启动时为管理员初始化内置 MySQL 配置；内置项不可编辑、删除、测试或刷新。VO 和文档接口隐藏类型、主机、端口、库名、账号与文档，Agent 元数据也隐藏连接位置。明文密码和密文均不返回。

## 文件

- `backend/app/api/db_config.py`：原路径和响应包装。
- `backend/app/services/db_config*.py`：CRUD、状态机、任务回写、试用初始化及公共转换。
- `backend/app/services/database_tools.py`：S07 冻结的同步工具边界。
- `backend/app/tasks/`：Celery 实例与验证任务。
- `backend/app/main.py`：数据源与 S07 chat router 注册、试用初始化。
- `backend/app/core/config.py`：验证超时配置。
- `backend/tests/test_db_config.py`：真实系统库、目标库、消息队列专项测试。

## 验证证据

环境：专用 PostgreSQL 16 系统/目标容器 `sqlchat-migration-test-postgres`，专用 MySQL 8 目标容器 `sqlchat-migration-test-mysql`，本阶段新建 `sqlchat-s05-rabbit`（RabbitMQ 3.13，127.0.0.1:15673），独立 Celery `solo` Worker。容器凭据只在测试进程环境变量中使用，未写入文件。

| 检查 | 结果 |
|---|---|
| `uv run --frozen --extra dev ruff check app tests` | 通过 |
| `uv run --frozen --extra dev mypy app` | 49 个源码文件通过 |
| `uv run --frozen --extra dev mypy tests/test_db_config.py` | 通过 |
| `uv run --frozen --extra dev pytest tests -q --tb=short` | 首次 61 通过、14 跳过；最终全套运行 62 通过、17 跳过、1 失败，失败项为 S06 `test_cancel_closes_provider_stream` 的 3 秒等待超时；单独重跑该项 1 通过。全套运行未注入专用数据库变量 |
| `uv run --frozen --extra dev pytest tests/test_db_config.py -q --tb=short`，注入真实 PostgreSQL/MySQL 与 RabbitMQ 环境 | 6 通过、1 跳过；跳过项为单独故障注入模式 |
| 同一专项命令仅运行 `test_unreachable_broker_persists_failure`，broker 指向未监听的本地端口 | 1 通过；队列发布失败持久化为状态 2 |

非 eager 的实际 Celery Worker 日志显示 `sqlchat.db_config.verify` 被接收并完成。实时测试分别证明正确连接的 0→1（带文档）和错误连接的 0→2（带错误诊断）。模拟发布任务仅用于确定性验证旧版本、删除回调和试用限制；不作为队列链路通过证据。

## 交接与剩余项

- `mypy app tests` 当前有 49 个错误，位于其他阶段的测试文件；本阶段源码与测试独立 mypy 通过，`mypy app` 全通过。
- 主代理随后复跑全量 pytest：63 通过、17 个环境条件跳过；此前 S06 时序性失败未重现。S05 专项真实环境用例均通过。
- Windows 开发机 Worker 使用 Celery `solo` 仅作链路验证；生产按规格采用 Linux Worker。进程被杀死时依靠读取端超时诊断；部署阶段仍需验证 Worker 重启和持久化。
- 未做部署 Compose 首启/重启或前端端到端验收；属于 S14/S15。S07 工具接口已冻结，后续文件工作流和结构比较将另行补全。
- 本阶段代码和初版交接文档已由主代理提交为 `1071f3f`；本段验收结果随文档补录提交。
- 专用 RabbitMQ 容器 `sqlchat-s05-rabbit` 暂保留运行供主代理复验；独立测试 Worker 已停止。
