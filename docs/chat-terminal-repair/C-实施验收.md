# C：前端终态回归实施与验收

## 范围与实现

本阶段不修改 Vue 业务代码；现有 `useSse`、chat store、MessageBubble、SseStepCard 和历史会话还原已支持错误终态。新增独立 Playwright + Node 测试，运行真实 Vue 页面，使用 mock SSE 与 mock 历史 API。测试服务使用动态独立端口、独立临时 Vite cache，结束时关闭浏览器与 Vite，不启动 Docker。

新增文件：
- `frontend/tests/chat-terminal-repair.test.mjs`
- `frontend/tests/fixtures/chat-terminal-browser.mjs`
- `frontend/tests/fixtures/chat-terminal-vite.config.mjs`

为适配后端 SQL 统一 final_report 契约，最小更新 S07 模型 fixture：每轮 SQL 工具执行后先返回决策 draft，再返回 `report` / `complete` 结构化报告。原有 SQL 实际执行、结果文本、历史回放和 POST 次数断言均保留，追加 summary_delta 拼接等于终态 summary 的断言。

## 回归检查

| 项目 | 断言 |
| --- | --- |
| 未选库确认 | 首轮 clarify；点击确认发送原问题、sql_query、同一会话、空数据库选择 |
| 错误终态 | 红色 error 卡片原样显示“SQL 查询需要至少选择一个数据库配置”；没有第二张 clarify |
| 输入恢复 | textarea 恢复可用，填写后发送按钮可用，无 streaming indicator |
| 错误刷新 | 刷新历史列表后继续会话，error 卡片与原 clarify 保留；不重复 POST |
| 元数据报告 | summary_delta 拼接与 summary 一致；终态单张报告；晚到 delta 不污染定稿 |
| reasoning / 表格 | 已完成 reasoning 默认折叠且可展开；Markdown 表格完整显示两行字段 |
| 报告历史 | 刷新后 reasoning、报告表格一致；不重复 POST |

## 执行记录

2026-10-06，前端目录执行 `pnpm typecheck` 与 `pnpm build` 均成功（exit 0）。生产构建仍有既有大 chunk 和 Vite native loader 提示，不作为本次新增错误。

前端目录执行 `node --test tests/chat-terminal-repair.test.mjs`：2 / 2 通过、exit 0，耗时 23.76 秒。首轮调试发现 mock glob 误匹配源码路径，随后改为 `/api/` pathname 谓词；另一次发现依赖预构建导致动态模块重载，独立 Vite 配置固定预构建依赖，避免影响业务测试。

## 验证边界

Mock UI 通过不代表真实后端或真实数据库通过。真实 FastAPI SSE 与持久化回归由主代理复跑默认 S07 隔离 SQLite fixture；这是测试替身，不是 PostgreSQL 实测。真实目标数据库仅 MySQL，由 B 的只读脚本验收；不使用只读演示账号执行 DDL，不声明 PostgreSQL / SQLite 生产数据库能力完成验收。主代理复核结果写入同目录 `主代理验收.md`。

已检查根目录与 sqlchat 的 AGENTS.md；本次不改变业务边界或核心目录，因此保持不变。未提交原用户图片、JSON 附件或真实密钥。
