# S07 前端聊天契约样例

状态：源码推导样例、模拟网络浏览器测试通过；真实 FastAPI 浏览器链路在进程内 SQLite 目标库替身模式“模拟通过”。尚未从浏览器直连真实 PostgreSQL/MySQL，因此 S07 完整门槛未通过。

## 依据与样例

- 规格：`spec/04-接口与数据契约.md` 的 C-02、C-03、C-06、C-07 和 SSE 表；`spec/07-测试与验收规范.md` 的 T-22、T-25、T-36。
- 原 Java：`ChatController.chat` 是 POST SSE；`IntentRouter.route` 发分类、路由、澄清和流内错误；`SimpleChatHandler` 发 `content`、`usage`、`done`；`BaseAgent`/`ToolCallAgent` 发 `step`、`summary_delta`、权威 `summary`、`usage`、`done`。
- 原历史：`ConversationServiceImpl.getMessages` 返回消息行；`SimpleChatHandler` 将最终正文存为 `type=summary`；`SqlQueryHandler` 将工具响应存为 `role=tool,type=tool` 的 JSON 文本，总结存为 `type=summary`。当前 Python S07 实现还会将澄清对象 JSON 文本存为 `role=assistant,type=clarify`。
- `frontend/tests/fixtures/chat-contract.json` 给出简单问答、SQL、澄清、错误和直接 EOF 的代表性事件序列，以及简单问答/SQL/目标版澄清的历史响应。内容与时间戳是脱敏测试值，不是生产抓包，也不证明目标后端已发送相同数据。

## 核对结果

| 行为 | 原实现与目标契约 | 前端模拟网络结果 |
| --- | --- | --- |
| 简单问答 | `content` 增量拼接；最终历史 `summary` | 正文拼接、推理块关闭、usage 和会话 ID 保留；停止加载 |
| SQL Agent | `step` 为展示文本；`summary_delta` 增量，`summary` 是权威全文 | 步骤保留文本；最终全文覆盖不一致的增量；停止加载 |
| 澄清 | 原 Java 的 `clarify` 后可能有 `usage`，直接 EOF，无 `done` | 澄清选项和 usage 保留；停止加载 |
| 流内错误 | `error` 后直接 EOF，无 `done` | 错误块保留；停止加载 |
| EOF | 未必收到终态帧 | 已收正文保留；停止加载且不重放 POST |
| 历史 API | `{code:200,message:"success",data:[...]}`、camelCase、可空字段 | API 客户端能消费模拟响应；历史内容与流式最终内容一致 |
| 澄清历史 | 当前 Python S07 保存 JSON 文本，历史页需重建 `ClarifyCard` | 模拟历史继续会话后卡片可见；点击选项携带原提问、会话 ID 和确认意图再次 POST |

`frontend/tests/chat-contract.test.mjs` 用 Playwright 在浏览器中向 `/api/chat` 注入上述 SSE 帧，并对 `useSse` 与 Pinia store 的结果断言；另以模拟 REST 响应检查历史客户端和澄清卡片的确认操作。`frontend/tests/sse-eof.test.mjs` 已覆盖 HTTP 503、终止旧流和无终态 EOF。

新增的 `frontend/tests/s07-chat-e2e.test.mjs` 启动原 Vue 页面和真实 FastAPI，通过本地 HTTP 模型 SSE 模拟器完成分类、SQL 工具调用、SSE 总结及结束帧；随后对同一会话续问、检查原 `conversationId` 和第二次 SSE，再经真实历史 GET 回放两轮消息；不拦截 `/api`。本次 `pnpm test:e2e:s07` 通过，目标库模式为 `postgresql-sqlite-substitute`。它证明前后端浏览器链路，但 SQLite 替身不能证明 PostgreSQL/MySQL 方言与驱动兼容。详细运行方式和环境变量见 [browser-e2e.md](browser-e2e.md)。

历史回放测试还模拟了聊天页装载时读取的 `/model-config/active`。遗漏该请求曾使测试环境把它转发到真实后端，401 触发全局退出，回放卡片随页面跳转消失。该依赖现已纳入模拟响应，组合测试连续运行五次通过。

## 待联调与差异

- `chat-contract.test.mjs` 只验证前端对模拟网络的消费；`s07-chat-e2e.test.mjs` 已覆盖真实 FastAPI 和历史回放，但本次使用 SQLite 目标库替身。仍需在浏览器测试中接入真实隔离 MySQL/PostgreSQL，组合验证目标库结果、SSE 结束和历史回放，才能满足 S07 完整闭环。后端独立的两库真实集成记录见 `docs/phase-07-core-chat/README.md`，该证据尚未与本次浏览器流程组合。历史澄清属于目标 Python 扩展，原 Java 未持久化该卡片。
- 原 Java 的 `context_compact` 是对象型事件；原前端类型漏掉它，现已补类型。当前 `SseStepCard` 默认按字符串显示，若 S09 开启该事件会显示 `[object Object]`，需在相应阶段按 `message` 渲染并测试。
- 原持久化历史可以出现 `compressed` 与 `aborted`。现已补 `Message.type`；当前历史回放逻辑只显式处理部分类型，S08/S09 应核对中断和压缩后的回放标识。`sql`、`result`、`file_parsed` 属于原前端历史联合类型，不能据此认定为 S07 SSE 帧。

## 本地验证

- `pnpm typecheck`
- `pnpm build`
- `node --test tests/chat-contract.test.mjs tests/sse-eof.test.mjs`

以上命令在 Windows 本地前端目录运行通过。构建仅出现现存 Vite 配置与大 chunk 提示。测试状态为“模拟通过”，不是“真实环境通过”。
