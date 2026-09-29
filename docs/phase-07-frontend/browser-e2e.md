# S07 浏览器联调

状态：原 Vue 页面到真实 FastAPI、LangGraph、隔离 PostgreSQL/MySQL 目标库、SSE 终态和历史回放的浏览器链路均通过。模型仍是本地 HTTP 协议模拟器；真实模型效果另行验收。

## 覆盖范围

`frontend/tests/s07-chat-e2e.test.mjs` 启动原 Vue 页面、真实 FastAPI 应用和本地 OpenAI 兼容 HTTP/SSE 模型模拟器。测试通过页面数据库选择器和聊天输入框发问，检查首轮 POST `/api/chat` 的 SSE `step`、权威 `summary` 与 `done`；从会话列表回放后继续提问，断言第二轮请求携带原 `conversationId`、收到独立 SSE 终态，且再次回放包含两轮消息。此用例不拦截或伪造 `/api` 响应。

测试用临时 SQLite 保存 FastAPI 系统数据。目标数据库默认由测试进程内 SQLite 文件替代 PostgreSQL 驱动连接；该替身只验证真实 FastAPI、LangGraph、SQL 工具调用和浏览器协议串联，不能证明 PostgreSQL/MySQL 方言、驱动、隔离级别或服务端行为。

## 运行

在 `frontend` 目录运行：

```powershell
pnpm test:e2e:s07
pnpm typecheck
pnpm build
```

要求 `backend/.venv` 已安装后端锁定依赖、`frontend/node_modules` 已安装 Playwright，并有可用 Chromium。测试按 Windows `Scripts/python.exe` 或 Unix `bin/python` 使用后端虚拟环境；若解释器不存在会明确报错。默认模式打印 `S07_TARGET_MODE=postgresql-sqlite-substitute`。

若有专用、可销毁的隔离目标库，可设置 `SQLCHAT_E2E_TARGET_DB=postgresql` 或 `mysql`，并提供对应的 `SQLCHAT_TEST_PG_HOST/PORT/DB/USER/PASSWORD` 或 `SQLCHAT_TEST_MYSQL_HOST/PORT/DB/USER/PASSWORD`。测试会创建唯一前缀表、通过聊天真实查询，并在正常结束时删除该表。不要连接生产库；运行中断时应检查并删除 `s07_<随机后缀>` 测试表。

## 本次执行记录

- `python -m py_compile frontend/tests/fixtures/s07_api.py`：通过。
- `pnpm test:e2e:s07`：通过，`S07_TARGET_MODE=postgresql-sqlite-substitute`；1 个浏览器用例通过。
- `pnpm typecheck`：通过。
- `pnpm build`：通过。Vite 报告既有 `__dirname` 配置提示及超过 500 kB 的 chunk 提示。
- 2026-09-29 Docker Desktop 恢复后，独立启动 `sqlchat-migration-test-postgres`（PostgreSQL 16）和 `sqlchat-migration-test-mysql`（MySQL 8）。从专用容器配置将凭据临时注入测试进程，未写入文件或输出明文。
- `SQLCHAT_E2E_TARGET_DB=postgresql` 与 `SQLCHAT_E2E_TARGET_DB=mysql` 分别运行 `pnpm test:e2e:s07`，各 1 个浏览器用例通过。两次均经原页面选择真实目标库、发送一次聊天 POST、收到数据库行数、SSE `done`、回放历史并续问；测试使用随机前缀表并在正常结束后删除。
- 后端 `pytest tests/test_chat_integration.py -q --tb=short` 在同一专用 PostgreSQL 系统库及 PostgreSQL/MySQL 目标实例中为 2 passed。前端 `pnpm typecheck`、`pnpm build` 通过，构建仅有既有 Vite 配置与 chunk 提示。

## 边界

- 本地 HTTP 模型模拟器验证真实 HTTP/SSE 协议接入，不评估真实模型的 SQL 生成质量。
- SQLite 替身模式不构成 PostgreSQL 或 MySQL 的真实数据库验收。
- S07 的真实数据库浏览器闭环门槛已通过；其他分类、澄清及 SQL 行为由后端测试覆盖。真实模型的生成质量与原项目效果对照仍属于 S15，不能从本地模拟模型推断。
