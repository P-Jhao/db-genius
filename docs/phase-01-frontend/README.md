# S01/S13 前端契约修复

提交：`d9f5aa2`。

## 范围

- Vite `/api` 开发代理指向 FastAPI 的 8109 端口。
- POST `/chat` 收到无 `done` 的正常 EOF 后收敛消息和全局 streaming 状态；旧请求结束不能覆盖新请求；错误仍停止重试。
- 移除三处前端显式 `any`，保留原组件渲染和选择行为。
- Docker 构建上下文排除 `.env` 及 `.env.*`，保留公开的 `.env.example`。

## 验收

在 `frontend` 目录执行 `pnpm typecheck`、`pnpm build` 和 `node --test tests/sse-eof.test.mjs`。三项均通过。SSE 测试模拟无 `done` 的正常 EOF，检查消息状态恢复、后续发送可用，以及等待超过默认重试间隔后 POST 没有重复；HTTP 错误也不会重试 POST。重叠发送场景先插入新用户消息，再替换旧流，验证旧 assistant 状态收敛且延迟旧响应不污染新消息。本机缺少 Playwright 自带 Chromium，测试使用已安装的 Chrome 回退运行。

## 边界

本次只验证前端契约与模拟 SSE；真实后端、模型和数据库链路由后续联调验收。项目 `AGENTS.md` 的功能边界与核心目录结构未变化，无需修改。
