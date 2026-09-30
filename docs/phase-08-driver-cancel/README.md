# S08 数据库在途取消交接

范围：MySQL/PostgreSQL 适配器执行路径。需求对应 `spec/05-Agent与工作流设计.md` 第 8 节、`spec/06-数据访问安全与部署设计.md` 第 1–2 节；验收对应 T-24，及 T-23/T-38 的数据库侧边界。

## 接口与状态

`RelationalAdapter.execute(..., cancel_event: threading.Event | None = None)` 保持旧调用兼容。上层应在开始同步数据库调用前建立共享 `threading.Event`，在浏览器中止、服务端超时或写流失败时设置它。仅取消 `asyncio.to_thread` 的等待任务无法证明数据库语句停止。

- PostgreSQL 用 Psycopg `cancel_safe(timeout=3)` 请求取消；服务端 `statement_timeout` 仍生效。
- MySQL 在独立控制连接上对本次执行连接 ID 发送 `KILL QUERY`；watchdog 也在 SQL 超时时触发，因此写入不只依赖仅作用于 SELECT 的 `MAX_EXECUTION_TIME`。watchdog 在提交前停止并等待控制请求结束，同一执行连接不会在此期间用于后续语句。
- `DatabaseExecutionInterrupted` 继承 `TimeoutError`，提供 `reason` (`cancelled`/`timeout`)、`cancel_request_sent`、`server_termination_confirmed`、`write_outcome_unknown` 和 `cancel_error`。请求发送成功不等于服务端已停止；只有驱动报告 PG SQLSTATE `57014` 或 MySQL 错误 `1317`/`3024` 才将终止标为已确认。语句已返回但提交前收到信号时会尝试回滚，仍以保守的未知写入结果报告，因为 DDL 可能隐式提交。
- 取消信号在提交成功后到达时保留成功结果。写入语句已执行而 `commit()` 失败，或执行期间连接失效时抛 `DatabaseWriteOutcomeUnknown`，不得自动重放。

本驱动提交只覆盖适配器与取消接口；会话接线在 S08 聊天部分单独验收。驱动测试通过不能证明浏览器中止已形成完整闭环。异常中的未知写入状态也必须原样传入工具/会话终态，不能改写为“已回滚”。

## 验证

在 `sqlchat/backend` 下运行：

```text
uv run --no-sync ruff check app/adapters tests/test_adapters_cancellation.py tests/adapter_cancel_fakes.py tests/test_adapters_integration.py
uv run --no-sync mypy app/adapters
uv run --no-sync pytest -q tests/test_adapters_cancellation.py tests/test_adapters_contract.py tests/test_adapters_safety.py tests/test_adapters_integration.py
```

结果：Ruff 通过；mypy 9 个适配器源码文件通过；pytest 43 passed、5 skipped。11 个取消专项协议测试覆盖 PG 驱动请求与服务端确认分离、MySQL `KILL QUERY`、控制连接权限失败、写入超时、语句完成/提交竞态、提交失败和执行中断连。`test_real_running_slow_query_cancel` 为两种数据库分别等待活动慢查询可见后发出信号，并要求驱动返回确认终止；尚未运行到实例。

## 后续真实实例复验（S12 时）

Docker Desktop 恢复后，用独立的 `sqlchat-migration-test-mysql`、`sqlchat-migration-test-postgres` 容器运行 `test_real_running_slow_query_cancel`，两类均通过，且原 `server_termination_confirmed is True` 断言保留。测试凭据只从容器配置临时注入进程环境，未写文件或记录明文。

复验时发现两项测试观测误差并单独修正：MySQL `SELECT SLEEP(10)` 接到 `KILL QUERY` 后可返回 `1` 而不抛驱动错误，此返回不能触发原有的服务端确认逻辑；测试改用耗时的 `information_schema.COLUMNS` 交叉连接，KILL 后驱动明确返回 `1317`。PostgreSQL 使用服务端流式游标时，活动 SQL 显示为 `FETCH FORWARD ...`，原注释标记不再出现在 `pg_stat_activity.query`；测试改观察 `PgSleep` 等待事件，并在每轮查询后回滚观察者事务以刷新统计快照。适配器取消实现未放宽，真实中断必须仍由驱动错误确认。

本次两项真实在途取消已验证；原完整 T-24 仍需与用户会话取消链路一起验收。先前环境阻塞记录保留作为历史阶段状态。

实现依据：[Psycopg Connection.cancel_safe 文档](https://www.psycopg.org/psycopg3/docs/api/connections.html)、[MySQL KILL QUERY 文档](https://dev.mysql.com/doc/refman/9.7/en/kill.html)。

已检查根目录 `AGENTS.md`：功能边界和核心目录未变化，保持原文。

## 主代理提交前验收

2026-09-30，主代理按明确文件及执行路径差异暂存本驱动部分，未将其余数据库的元数据扩展或未完成的聊天/文件工作区改动混入。用 `git checkout-index` 导出暂存版本的隔离副本，再运行上方 Ruff、mypy、四个 pytest 文件；专用 PostgreSQL/MySQL 凭据临时注入进程。结果 **48 passed**，包含两种真实在途慢查询取消；Ruff 通过，mypy 9 个适配器模块通过。这是驱动子阶段验收，不代表完整 T-24 或 S08 全阶段通过。
