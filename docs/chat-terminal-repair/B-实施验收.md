# B：SQL 最终报告统一收口

## 结论与证据边界

SQL 决策轮不再把无工具调用的正文直接作为终态交付。完成门槛通过后统一进入现有 `summarize`，使用总结角色、原请求与证据历史以及 `final_report=True` 的报告传输契约。完成门槛未通过仍直接给出确定性的限制或失败报告，不额外调用模型。

用户历史记录中两次四页 schema 都完整覆盖 11889 字符，offset 为 0、3407、6803、10204，末页 nextOffset=11889。结构 JSON 包含 10 表、incomplete=false、errorMessage=null。用当前 SchemaEvidence 离线重放，两次均 complete=true。原记录没有保留内部 taskGoal 和模型决策正文；不能断言历史 id48 的原因已唯一证实。当前代码的完整 metadata_only 门槛不会产生零 SQL 失败句。本修改修复可证实的终态路径差异，不将结构化传输完成等同于事实正确。

## 实现契约

- `graph_sql.py`：SQL direct 路径先执行 `completion_override`；失败保持 summary 和 finished=true；通过返回 messages、decision、finished=false，draft 不进入 messages，也不发布。
- A 的 `graph.py` 路由将 SQL 无工具调用且未 finished 的状态转入 summarize。workflow 和 db_compare 行为不变。
- summarize 继续检查原完成门槛，继续使用现有模板和 ReportDecoder。决策 reasoning 展示保留，最终总结 reasoning 也保留。
- `sql_terminal_diagnostics.py` 只记录 taskId、taskGoalMode、terminalPath、overrideApplied、schemaEvidenceComplete、statementsAttempted、statementsExecuted。terminalPath 区分 direct、terminate、step_limit、loop_stop；不记录请求、draft、reasoning、表名、schema 或模型正文。
- 不变更 goal 语义判定，不增加关键词重判，不改变授权、metadata-only 工具限制或 SQL 安全规则。没有修改 API/persistence 模块。

## 真实验收发现的分页账本缺陷

部署后真实 MySQL 第一轮成功，第二轮返回元数据不完整。主代理独立核验实际页区间依次为 `[0,3407)`、`[8000,11419)`、`[3407,6803)`、`[11419,11889)`、`[6803,8003)`。区间并集完整覆盖 `[0,11889)`，仅存在 `[8000,8003)` 三字符重叠。旧 SchemaEvidence 沿精确 offset 键串联，走到 8003 找不到键 8000，错误地把完整证据判为 truncated。这是本次真实验收新确认的代码缺陷；它不证明用户最初 id48 的原因。

`schema_evidence.py` 改为按起点排序合并实际字符区间。合法一致重叠与乱序可完成；同 offset 较短重读不会缩小已有有效证据；有 gap 不完成，不能用 hasMore=false 代替覆盖证明。重叠字符冲突、总字符数变化、负 offset、负总长或区间越界均显式抛错，失败页不写入账本。完整合并后仍解析 JSON 并与已注册 source 比较，未放宽源结构完整性检查。

准确五页、反序五页、gap、冲突重叠、重复短页、越界、总长变化和 source mismatch 新测试与既有 schema 测试合计 16 项通过。脱敏 SQL 诊断 logger 显式设为 INFO；测试证明 root WARNING 下可见，SafeLogFilter 处理后仅保留原白名单字段。未调整全局日志级别。真实脚本的事件类型数组改为计数字典，所有验收判断保持不变。

下一次真实 MySQL 验收第一轮通过，第二轮实际区间为 `[0,3407)`、`[4000,7402)`、`[8000,11419)`、`[11419,11889)`、`[7402,8102)`，确有 `[3407,4000)` 593 字符缺口。此时 schemaEvidenceComplete=false 是正确拒绝，区别于上述并集完整却误判的代码缺陷。追加这一实际 gap 的回归；不自动补页、不调用第二轮重试模型、不放宽证据门槛。

仅增强 `tools.py` 的 readToolOutput 工具描述、offset/length 字段说明，以及 `output_guard.py` 的已有 instruction：从 0 开始，以返回的 nextOffset 继续；length 是请求上限，实际页可能更短，不能 offset+requested length；hasMore=false 只说明该页到尾，不能证明早先没有 gap。artifact instruction 保持紧凑以兼容原 450 字符输出预算；完整语义在工具描述和字段描述中展开。未改预算、默认模型参数或安全规则。新增提示契约测试还验证实际页小于请求 length、下一页使用 returned nextOffset。

## CID22：重复 schema 注册覆盖旧 artifact 的代码缺陷

最终镜像 7515d1a65094602806f95934a3de00b4e8c5cff0b0cb99a5dbdbd51ce940ee0d 的真实 CID22 第一轮表清单通过，第二轮仍返回 92 字符限制 summary。B 通过 `docker exec ... python deploy/connection_env.py python -` 只读持久化记录核实，第二轮不是漏页：实际四页 `[0,3407)`、`[3407,6803)`、`[6803,10204)`、`[10204,11889)`，坐标合法、总长一致、gap 为 0、末页 hasMore=false。分页前模型额外调用一次 getDatabaseSchema，刷新结构与旧 artifact 四页拼接 JSON 完全相同，均 10 表、incomplete=false、errorMessage=null，SQL 调用为 0。

旧 register 按 dbId 覆盖唯一 SchemaObservation 的 artifactId，导致旧 artifact 的随后分页被忽略。离线重放“注册旧 ID→同源注册新 ID→旧 ID 读完”得到 complete=false；同样四页用当前 ID 重放 complete=true，证明刷新丢证据是代码缺陷。此结论只适用于此次可恢复的 CID22 运行，不追溯断言用户原 id48 原因。

修复保存 artifactId→(dbId, 独立 SchemaObservation) 账本，同时保留每库最新结构 observation。每个 artifact 的页区间独立验证与合并，不能跨 artifact 或跨库拼页。旧 artifact 只有完整读完且 JSON 等于该 artifact 已注册 source 后才成立；只有其 source 又等于当前最新结构时，才认可当前已交付证据。同源重读不抹除完整事实；真正改变 source 后旧证据失效，直到新 source 独立完整交付。重复 artifact ID 注册到不同库/结构显式报错。未增加真实调用、补页或模型重试。

新增账本测试覆盖未读/部分/完整后同源刷新、inline 完整证据后 truncated 注册、source 真正改变、多库、跨 artifact 不拼接、identity 冲突；真实 Graph 路径覆盖 0/2/4 页后刷新 × direct/terminate；真实 API/SQLite persistence 覆盖刷新前后正常报告、length 与未闭合 JSON，仍检查 SSE/history/reasoning 顺序一致。所有相关文件低于 300 行，没有新增源文件。

验收命令（静态与回归完成后主代理再更新缓存镜像，由主代理进行一次真实 MySQL 验收）：

```powershell
backend/.venv/Scripts/python.exe -m pytest backend/tests/test_schema_goal_evidence.py backend/tests/test_sql_terminal_summary.py backend/tests/test_sql_terminal_summary_api.py -q
backend/.venv/Scripts/python.exe scripts/acceptance/chat_terminal_repair.py
```

最终真实 MySQL 验收已由主代理完成：镜像 `53bf544f390362925644f6ded482bd64820eb5d7f3cd239c487e1d95006b94e6` 的 API/Worker 均 healthy，ignored 证据 `.git/acceptance/chat-terminal-repair/20261006T104855273988Z.json`、CID24，四个 case 全部 passed。confirmed 缺数据库精确 error、零模型调用、history 一致；prior simple_chat 通过。表清单第一轮经 terminate，完整 schema、无 override、SQL 执行 0，匹配独立 10 表，955 字符、7 模型调用、4 页、5 个 reasoning 块；第二轮经 direct，完整 schema、无 override、SQL 执行 0，匹配独立 10 表，1459 字符、7 模型调用、4 页、4 个 reasoning 块。两轮 SSE summary、deltas、持久化 history 与 reasoning replay/顺序全部一致。此成功保留之前实际 run 的区别：CID20 为真实 gap 的模型漏页限制，CID22 为同源 schema 刷新覆盖 artifact 账本的应用缺陷，均已在上文记录，未删除失败证据。

## Fixture 与回归

`tests/fixtures/chat_terminal_schema.json` 仅保存用户附件中已经脱敏的 schema 结构 JSON：库名/主机均为 `*`、端口为 0，未保存聊天、reasoning、token 或模型请求。11889 字符按真实 OutputArtifacts 4000 字符输出预算分页，准确得到原四个 offset。

新增 `test_sql_terminal_summary.py` 与 `test_sql_terminal_summary_api.py` 覆盖：

1. 真实四页 schema 完整交付后，错误 direct draft 与 doTerminate 统一得到 10 表清单；SQL 尝试和成功数均为 0。
2. 历史 simple_chat 声称无法访问数据库，最终总结仍收到当前完整 schema；错误 draft 不进入最终模型消息、SSE 或 durable history。
3. 缺页与源 incomplete=true 保持确定性限制报告，不额外请求最终总结模型。
4. statement_execution 零 SQL 和失败 SQL 仍给出权威未完成报告；不被 direct/terminate 成功断言覆盖。
5. direct 最终报告 finish_reason=length 或 JSON 未闭合触发原错误路径，不保存伪成功 summary；正常报告 SSE delta、summary 和 SQLite durable history 一致。
6. direct 决策 reasoning 和 final reasoning 分别持久化，顺序正确，没有重复 reasoningContent。终态诊断白名单与各路径标记有断言。

旧 SQL direct 成功测试只补充最终报告响应，并保持原 SQL 效果、事实、类型、投影、权限、安全和计数断言；最终报告调用计数按新增一轮更新。native/trial 测试 fixture 同步更新但未运行全数据库矩阵。

本地验证：首轮目标测试 89 通过，2 个旧 direct fixture 缺最终响应；补齐后复验相关测试 45 通过。新增完整分页/API 与 loop_stop、step_limit 诊断断言最终复验 15 通过。生产模块与验收脚本 mypy 通过；新增测试按 `--follow-imports=silent` 检查通过（普通测试 mypy 会连带报告旧测试类型问题）。修改文件 Ruff 通过。

## 真实本地 MySQL 验收入口

部署后由主代理执行，脚本不会修改模型或数据源配置，不会创建或删除表，不会清理会话：

```powershell
backend/.venv/Scripts/python.exe scripts/acceptance/chat_terminal_repair.py
```

默认目标 http://127.0.0.1:8109、已有数据库配置 id2、sqlchat-api-1 容器。可通过参数显式选择已有配置；只允许本机 HTTP。登录仅从 ignored 根 `.env` 读取 SQLCHAT_BOOTSTRAP_USERNAME/SQLCHAT_BOOTSTRAP_PASSWORD。必须 GET 验证目标配置 status=1 且 MySQL/掩码内置配置，并验证 active model 为 deepseek-flash；随后在现有 API 容器独立调用 schema 服务，核实真实数据库类型 MySQL、完整结构和 10 表，避免把模型文字当 oracle。

真实 case 包含：confirmed SQL 缺数据库（精确中文 error、没有 clarify、usage/done 各一次、callCount=0、history 持久化同 error）；simple_chat 旧历史；同会话连续两轮“有哪些表”，第一轮 confirmed SQL、第二轮正常分类。检查 schema 表名覆盖、无 executeSql、SSE/history summary 相同、delta 相同、已有 reasoning 内容与顺序一致、无重复字段。供应商不返回 reasoning 只作为观察信息，不单独判失败。

输出仅为 `.git/acceptance/chat-terminal-repair/<timestamp>.json`：计数、布尔值、事件类型计数、conversationId；不保存 token、key、schema、正文或 reasoning。失败边界只输出异常类型。真实请求未由 B 子代理执行。

## 本机构建限制

标准 Docker 构建获取 ghcr.io/astral-sh/uv:0.11.25 token 遇到网络超时。没有修改 tracked Dockerfile 或依赖。按主代理要求准备 ignored `.git/acceptance/chat-terminal-repair/Dockerfile.cached`，从现有 sqlchat-terminal-repair-base:6776645 本机镜像复制 backend/app 增量构建；继承现有 ENTRYPOINT/CMD，最终恢复 sqlchat 用户。依赖未变，该临时文件不提交。主代理负责构建、替换 API/Worker 并执行上述真实验收。

检查根 AGENTS.md 和 sqlchat/AGENTS.md：本次仅终态行为修复，无核心功能边界或目录结构变化，两份文件保持不变。
