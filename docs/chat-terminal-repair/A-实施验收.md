# A：SQL 缺数据库配置终态与图路由

## 行为边界

- 已确认 `sql_query` 且 `dbConfigIds` 为 `null`、省略或 `[]`：抛出 `BusinessError(400, "error.chat.sqlQueryNoDbConfig")`，复用既有 SSE `usage → error → done` 和错误历史持久化。
- 首次外层分类已明确 SQL（`needsClarification=false` 且 `confidence>=0.7`）：缺数据库配置时，在内部 `taskGoal` 的澄清、授权和数据库工具之前报上述错误。内部目标可因缺资源要求澄清，但不覆盖此资源错误。
- 首次外层分类仍不明确：保留既有澄清流程。`TaskGoal` JSON 契约保持不变。
- `workflow`、`db_compare` 缺资源行为保持既有澄清。
- SQL 的决定节点已通过完成条件、没有工具调用、未结束时，路由到统一 `summarize`。决定文本不构成最终报告；最终报告按既有 JSON 报告契约生成。

## 变更范围

| 文件 | 职责 |
| --- | --- |
| `backend/app/agent/graph.py` | SQL 缺资源业务错误；SQL 决定节点到统一总结节点的条件路由 |
| `backend/tests/test_chat_graph.py` | 缺资源图错误断言；SQL 直答成功样例增加合法最终报告 |
| `backend/tests/test_sql_prerequisite_api.py` | 真实 HTTP 模型适配器、FastAPI SSE、隔离 SQLite 持久化回归 |

`graph_sql.py` 的 SQL 决定节点修改由 B 阶段维护；本阶段只衔接其返回状态。

## 自测验收

验证使用本地可控 HTTP/SSE 模型服务和隔离持久化数据库，不调用线上模型和真实目标数据库。

| 场景 | 断言 |
| --- | --- |
| 确认 SQL 缺库，`null` / `[]`，英文 / 简体中文 | 0 模型调用、0 数据库工具、一次 usage/error/done、一次错误终态和账本记录 |
| 首次明确 SQL，内部目标缺资源澄清或包含未授权库 | 缺库错误先于目标澄清及授权，分类模型仅调用一次 |
| 首次不明确 → 确认 SQL 缺库 → 选择数据库 | 先 clarify、再 error、再成功；数据库 schema 和 execute 各一次 |
| 同会话恢复和记账 | 三个唯一终态任务账本，用量分别为 8 / 0 / 22，总量 30；错误只存一次；决定草稿不进入历史 |
| 其他数据库意图缺资源 | 继续 clarify，0 模型调用 |
| SQL 工具执行后直答、工具终止后总结 | 最终报告经过统一总结；成功最终答复一次 |

执行命令（工作目录 `backend`）：

```powershell
.venv/Scripts/python.exe -m pytest tests/test_sql_prerequisite_api.py tests/test_chat_graph.py -q
.venv/Scripts/python.exe -m ruff check app/agent/graph.py tests/test_chat_graph.py tests/test_sql_prerequisite_api.py
```

最终运行：`19 passed in 74.39s (0:01:14)`；Ruff 静态检查通过，`git diff --check` 通过。

## 验收限制和交接

尚未验证真实生产模型、真实目标数据库及前端浏览器流程；完整跨阶段验收由主代理汇总。没有部署、提交、修改环境配置或原参考项目。

已确认 SQL 缺库的图路径为 0 分类/目标分析模型调用，前置校验先于目标分析与数据库工具；API 的 0 总模型调用断言覆盖新会话和未触发压缩的续聊。首次明确分类路径仍有一次分类调用。既有 API 在进入图之前执行自动上下文压缩，本阶段保留该顺序；极长既有会话触发压缩属于既有内部流程，尚未验证此条件。

已检查工作区与 SQLChat 的 `AGENTS.md`。本次未增加核心业务能力或核心目录，保持两份文件不变；新增和修改的代码文件均不超过 300 行。
