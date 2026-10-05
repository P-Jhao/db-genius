# B：推理流与历史回放实施验收

日期：2026-10-06。基线：`784b72c`。本阶段仅本地修改与测试，未提交代码、启动 Docker 或调用真实模型。

## 接口与行为

`ModelStream.call` 保留原参数，追加 `emit_reasoning: bool | None = None` 和 `json_contract: JsonContract | None = None`。

- `emit_reasoning=None` 保持原控制关系：正文事件开启时展示实际供应商推理，正文事件为 `None` 时隐藏。
- `emit_reasoning=True` 可以在 `event=None` 的工具决策中独立展示 `reasoning_content`；正文决策内容和 DSML 不因此对外发送。
- 分类和 `json_contract="task_goal"` 属于内部分析，强制隐藏正文与推理，并移除返回消息中的供应商推理字段。二者仅发送原有 `thinking.disabled` 参数，不全局启用供应商 thinking。
- 显式 `task_goal` 契约不可与 classification/final_report 标记或工具同时使用；供应商意外返回工具调用时显式拒绝。
- JSON object 请求仍只由服务端端点/模型精确白名单启用；普通决策、聊天和压缩参数保持既有行为。
- `ObservedModelStream` 透传新参数，原埋点与用量记录语义保持一致。内部跨轮压缩显式使用 `emit_reasoning=False`。

A 阶段负责调用点：分类与目标提取隐藏、单轮压缩隐藏、工具规划和总结开启推理；简单聊天继续使用默认 content 兼容行为。用户可见的 `classified` 事件仍为原四字段，内部 taskGoal 不进入公共分类事件。

## 回放与终态

新增 `services/chat_records.py`，只缓冲本轮已发送的 `reasoning` 与 `step` 文本。连续推理片段按模型调用 ID 和 step 合并，同一步中的不同模型调用保持独立记录。

API 发送事件前检查共享取消信号；通过该检查后的分片形成帧并缓冲、入队，过程中不进行数据库调用或额外取消检查。取消发生在形成帧时，也保留这次已经进入发送路径的片段。既有 content/summary_delta 部分答案缓冲继续保留。

`finalize_run(..., records=...)` 在既有会话锁与 `finalizedTaskIds` 账本事务内依次写入推理、步骤、终态，再累加已知用量。done/error/aborted 使用同一条终态路径；重复 taskId 不追加回放消息或 Token。异常 flush 显式记录 taskId 与错误类型，不输出原始敏感异常文本。

历史推理使用已有 `type="reasoning"`、`content` 字段，不同时写入 reasoningContent，避免前端重复展示。ConversationsPage 已支持此类型，B 不改前端。步骤仍使用原 tool/step 记录。有效上下文只选取 user/content/summary 等原允许类型，推理、工具步骤与不完整 aborted 均不会成为有效模型答案。

## 文件所有权

B 修改：

- `backend/app/agent/streaming.py`、`json_capabilities.py`。
- `backend/app/api/chat.py`、`backend/app/services/chat_store.py`。
- 新增 `backend/app/services/chat_records.py`。
- 经根代理授权追加 `backend/app/core/observability_runtime.py` 的参数透传、`backend/app/services/context_compress.py` 的显式隐藏参数。
- 新增 `test_reasoning_stream.py`、`test_reasoning_api.py`、`test_reasoning_store.py`。
- 更新 `test_chat_api.py`、`test_chat_abort.py`、`test_final_report_api.py`、`test_json_capability_http.py` 的内部目标响应/用量契约；`test_final_report_locale.py`、`test_protocol_observation_boundary.py` 仅扩展 fake finalize 签名接收 records。

A 的 graph/types/tools/prompts、C 的试用数据/前端/部署文件不由 B 修改。工作区与 SQLChat 根 AGENTS.md 均已复查；本阶段没有新增业务边界或核心目录，保持不变。

## 已执行验收

使用 `backend/.venv/Scripts/python.exe -m pytest`，供应商为本机 HTTP/SSE 假模型，系统存储为 SQLite 测试数据库，目标数据库服务 mock 为 MySQL 类型场景。

| 验证范围 | 结果 |
| --- | --- |
| test_reasoning_stream：控制兼容、分片聚合、内部契约隐藏、白名单格式、取消计费、意外工具拒绝 | 11 passed |
| test_reasoning_api：真实 HTTP → ObservedModelStream → LangGraph → API → 历史；分类/确认两路径、两次规划与总结、无推理、error/abort、终态竞争、flush 失败 | 7 passed |
| test_reasoning_store：回放/终态/用量一次事务、重复终态、失败整体回滚、排除上下文 | 2 passed |
| test_chat_api、test_chat_abort、test_json_capability_http | 合并执行通过；其间新增 goal 用量期望已修复 |
| test_final_report_api | 8 passed |
| test_final_report_locale、test_protocol_observation_boundary、reasoning API/store | 合并执行 26 passed |
| B 的 16 个源/测试文件 Ruff | All checks passed |
| B 的 7 个应用文件 mypy（follow-imports=silent） | Success |
| git diff --check | 通过 |

## 限制

回放缓冲在终态一次落库，进程被强制杀死且无法执行终态时，不保证保留内存中的过程片段；本阶段不新增断点续传或崩溃恢复能力。供应商没有返回推理或没有返回尾部 usage 时，分别不制造推理内容、不估算精确计费用量。

终态竞争回归验证了终态事务已成功后再进入 abort 的重入去重；未为 SQLite 引入生产级行锁模拟。生产环境继续依赖既有 PostgreSQL 会话行锁与终态账本。未做真实模型、真实目标数据库或 Docker 验收。
