# S08 Chat 中止与用量交接

## 行为

- SSE 连接断开和总请求超时设置同一 `threading.Event`。当前总请求上限为原项目的 300 秒；15 秒无数据时发送 SSE 保活。模型流在等待上游数据时检查取消信号并关闭上游异步流。
- 图节点在分类、路由、工具与总结之间检查信号。SQL 工具将该事件传给适配器的 `execute(..., cancel_event=...)`，等待同步驱动调用返回或抛出中止状态后才收尾；不把取消 `asyncio` 等待视为数据库语句终止。
- 数据库中止记录取消请求是否发出、服务端是否确认终止、写入结果是否未知。已确认写入只记录完成次数；不会自动重试或承诺回滚。终态消息的 `metadata_json` 含 `taskId`、`runStatus`、`completedWriteCount` 和可用的 `databaseInterruption`。
- 若用户已看到部分正文或总结增量，中止后存一条 `aborted` 消息，后续入模历史会排除它。已有完整 `summary` 时保存该总结，不另写 `aborted` 消息；任务状态仍为 `aborted`。
- 正常、错误和中止统一通过 `chat_store.finalize_run` 在一个事务中写终态消息、累计已收到的服务商 Token、登记 taskId。重复收尾不再增加 Token 或写消息。无服务商 usage 尾包时 Token 保持 0；`callCount` 仍反映发起的模型调用。

## 验证

此阶段单独集成在 S07 + S08 驱动取消的验收副本；未引入后续阶段的上下文压缩、文件工作流、结构比较、试用模式、DSML 和观测模块。在验收副本 `backend` 目录运行；以下 `VENV` 指向主工作区已有虚拟环境：

```powershell
$VENV = 'C:\Users\22126\Desktop\web\text2sql\sqlchat\backend\.venv\Scripts'
& "$VENV\ruff.exe" check app/agent/graph.py app/agent/streaming.py app/agent/tools.py app/agent/cancellation.py app/api/chat.py app/services/chat_store.py app/services/database_tools.py tests/test_chat_abort.py tests/test_chat_abort_api.py tests/test_chat_abort_real_api.py
& "$VENV\mypy.exe" app/agent/graph.py app/agent/streaming.py app/agent/tools.py app/agent/cancellation.py app/api/chat.py app/services/chat_store.py app/services/database_tools.py
& "$VENV\python.exe" -m pytest -q tests/test_chat_abort.py tests/test_chat_abort_api.py tests/test_chat_graph.py tests/test_chat_api.py tests/test_model_protocol.py
```

2026-09-30 验收副本：Ruff 通过；mypy 7 个 S08 源码文件通过；S08 模拟取消、S07 聊天图/API/模型协议共 34 passed。测试覆盖分类前取消、模型正文流中止、上游长时间无响应时关闭模型流、SQL 工具收到驱动中止、总结增量中止、部分答案只落一次、正常/错误终态去重、请求超时与 ASGI 断连信号。HTTP 模型使用本地模拟服务；SQLite 验证聊天持久化逻辑。

### 真实 HTTP 断连到数据库取消（T-23/T-24 补验）

`tests/test_chat_abort_real_api.py` 用本地 HTTP SSE 模型模拟服务及真实 Uvicorn/TCP 客户端，先在隔离 PostgreSQL 16、MySQL 8 目标库提交一条 INSERT，再启动 20 秒慢 SELECT；独立连接确认语句已经在服务端运行后，客户端关闭流连接。测试核对该目标会话在 5 秒内不再执行慢查询、模型没有后续 SELECT/总结请求、会话只落一条 `aborted` 终态、两次模型调用的 12 Token 只累计一次、`completedWriteCount=1`、已提交行仍可回读。目标表名随机生成并精确删除；系统会话用临时 SQLite。没有 `SQLCHAT_TEST_PG_*` / `SQLCHAT_TEST_MYSQL_*` 测试环境变量时对应实例用例跳过。

PostgreSQL 执行连接在测试内设置随机 `application_name`，独立观察连接以该标识和 PID 锁定 `pg_stat_activity` 中的 `PgSleep`。适配器使用服务端游标，因此运行中的查询显示为 `FETCH` 而非原始 SELECT；用例进一步确认同一目标 PID 停止等待。MySQL 以 SQL 中随机标识和 `SHOW FULL PROCESSLIST.Id` 锁定会话。两库均保持真实适配器执行、驱动取消与 ASGI 断连路径；只模拟模型供应商。MySQL `SLEEP` 在 `KILL QUERY` 后可能返回正常结果，所以 `serverTerminationConfirmed` 元数据仍为 `false`，但测试从独立服务端会话证实原慢查询消失，且 `cancelRequestSent=true`。

在配置了专用目标库临时进程变量后，运行：

```powershell
& "$VENV\python.exe" -m pytest -q tests/test_chat_abort_real_api.py tests/test_adapters_cancellation.py
& "$VENV\python.exe" -m pytest -q tests/test_chat_integration.py tests/test_adapters_integration.py
```

2026-09-30 专用容器验收：PostgreSQL/MySQL 真实断连和驱动测试 13 passed；在临时提供隔离系统库与目标库进程变量后，S07 HTTP 聊天集成和适配器集成 7 passed。测试没有输出或保存数据库凭据。

## 未验证与风险

- 浏览器经 Compose 代理的真实断连及多进程并发收尾仍需部署联调；本次新增验证的是实际 TCP 客户端到 Uvicorn ASGI、真实目标数据库的链路。PostgreSQL 收尾依赖会话行锁；测试使用的 SQLite 系统库不提供等价的跨进程行锁保证。
- 300 秒请求上限目前为聊天 API 内常量；若部署需要不同上限，后续可将其移至配置项并与代理读取超时统一校验。

本阶段未改变功能边界或核心目录，已检查根目录 `AGENTS.md`，无需修改。

主代理独立复验：2026-09-30，验收副本中同一次运行上述中止/API/图/协议和真实 PostgreSQL/MySQL 集成、取消用例，共 54 passed（86.47 秒）；全量 Ruff 通过，mypy 检查全部应用源码。浏览器与代理联调仍留待 S14，未标记完整迁移通过。
