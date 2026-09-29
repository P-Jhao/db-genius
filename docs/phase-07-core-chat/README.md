# S07 核心聊天后端交接

状态：后端阶段实现与隔离环境联调通过；前端联调和主代理验收另行记录。

## 范围

对应 F-06、F-07、F-08、F-14，C-06 至 C-08，T-10、T-11、T-22、T-25。`app.agent.graph` 使用 LangGraph `StateGraph` 的分类、澄清、前置条件、简单问答和 SQL 工具循环条件边。确认意图跳过分类，但数据库与会话仍检查归属和连接状态。SQL 分支在模型调用前读取 S05 的真实元数据，再通过 `executeSql` 调用同一服务执行语句；无执行而直接声称查询结果会报错。单轮成功写语句重复调用被拒绝。

`POST /api/chat` 返回 `text/event-stream`，帧为 `data: JSON`，含 taskId、step、type、content、毫秒 timestamp；使用 `Cache-Control: no-cache` 和 `X-Accel-Buffering: no`。提供 conversation/classifying/classified/clarify/routing/thinking/content/step/summary_delta/summary/usage/error/done。`GET /api/chat/conversations`、`GET /api/chat/conversations/{id}/messages`、`DELETE /api/chat/conversations/{id}` 保持 `{code,message,data}` 包装及用户隔离。简单问答的 `content` 和 Agent 的 `summary` 按完整文本入库，续问重建上下文时排除过程、错误和澄清内容。

## 验证

| 场景 | 环境 | 结果 |
|---|---|---|
| 分类、低置信度澄清、非法 JSON、确认意图前置条件、SQL 工具、终止与重复写入 | 本地 HTTP 模型协议模拟；数据库服务定向替身 | 通过 |
| POST SSE、续问、用量、消息回放、跨用户拒绝与删除、内部异常不泄露 | 本地 HTTP 模型协议模拟 + SQLite 系统库 | 通过 |
| 模型工具调用到实际元数据、INSERT、SELECT，再独立查询目标表 | 本地 HTTP 模型协议模拟 + 隔离 PostgreSQL 16、MySQL 8 目标库 + PostgreSQL 系统库 | 两库通过；临时表随机命名并精确删除 |
| `pytest -q tests/test_chat_graph.py tests/test_chat_api.py tests/test_model_protocol.py` | 本地 Python 环境 | 24 passed |
| `pytest -q tests/test_chat_integration.py` | 隔离容器环境变量临时注入 | 2 passed |
| `ruff check app/agent app/api/chat.py app/services/chat_store.py tests/test_chat_*.py` | 本地 | 通过 |
| `mypy app/agent app/api/chat.py app/services/chat_store.py` | 本地 | 通过 |

真实联调从测试容器环境读入口令，仅放入 pytest 进程环境，不写文件或输出。HTTP 模型是协议模拟，因此不能据此声明真实 LLM SQL 生成准确率。

## 后续

S08 接手浏览器断连/模型流/在途 SQL 的取消传播、部分答案、终态幂等和 Token 并发累计。本阶段的 SSE 生产任务在流结束时取消，但数据库同步调用包在线程中，取消 asyncio 任务不等于驱动语句终止；已有写入也没有跨调用回滚承诺。当前成功写入仅在单个运行中按原始语句防止重复调用，不能代替跨重试执行账本。

S09 接手原提示词完整对齐、上下文压缩、工具输出结构化裁剪与制品分页。当前 `readToolOutput` 只在同一运行内保存输出；运行结束即不可读取。S10/S11 分别接手文件工作流与数据库结构对比；目前选择对应意图可分类和校验前置资源，但执行分支会显式返回未实现错误。压缩 REST 路由尚未实现，不能视为 S07 历史能力已覆盖压缩。真实前端到真实模型的端到端效果仍待主代理验收。

已检查仓库 `AGENTS.md`：本次没有新增功能边界或核心目录，保持不变。
