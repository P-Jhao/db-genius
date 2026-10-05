# A：SQL 目标与结构证据修复实施验收

适用基线：SQLChat `784b72c`；本轮修改未提交。只修改 SQLChat，参考项目 db-genius 未变更。本文件记录 A 子代理负责的内部目标、工具边界、元数据证据与总结装配；推理展示/持久化由 B 负责，演示数据由 C 负责。

## 已批准计划与内部契约

- 公开 Intent 仍为 `simple_chat`、`sql_query`、`workflow`、`db_compare`；ChatRequest 没有新增用户字段，`classified` SSE 仍只有 intent/confidence/reasoning/needsClarification。
- 普通分类一次模型调用解析 `ClassifiedTask`，在原分类字段之外携带必填 `taskGoal`。仅 sql_query 必须为目标对象，其余意图必须为 null；不拆成第二次分类。
- confirmed sql_query 跳过意图分类，先校验已有资源前置条件，再做一次无工具的内部目标分析。缺数据库时仍直接澄清，零模型调用。
- 内部调用使用 `json_contract='task_goal'`、`emit_reasoning=False`；普通分类仍使用 classification=True、emit_reasoning=False。由 B 的 ModelStream 承接 JSON 能力并禁用内部 thinking，内部目标不会作为正文、推理或 SSE 字段展示。

TaskGoal 所有字段必填，Pydantic strict=True、extra=forbid：

```json
{
  "mode": "metadata_only",
  "dbIds": [12],
  "tableScope": [{"dbId": 12, "tables": ["orders"]}],
  "confidence": 0.99,
  "needsClarification": false,
  "reasoning": "请求明确要求结构元数据"
}
```

- mode 仅允许 metadata_only 或 statement_execution；只要混合请求包含实际数据查询或语句执行，必须为 statement_execution。
- dbIds 必须是已授权资源中的正整数且去重；tableScope 必须恰好覆盖目标 dbIds，一库一项。tables=null 表示全库；具名列表不能为空、不能重复、不能含空白表名。
- 模型按当前问题与有效历史进行语义判断；没有新增关键词或正则分支用于推断任务目标。选库、附件或出现 SELECT/DROP 文字本身不能补足缺失目标。
- 分类或目标 confidence<0.7，或 needsClarification=true，均在读取结构/执行语句前澄清。非法字段或越权 dbId 显式失败，不能降级成可执行目标。

## 工具与证据边界

metadata_only 的模型工具白名单只有 getDatabaseSchema、readToolOutput、doTerminate；即使绕过模型工具列表直接调用 RunTools.execute，也在计数和驱动执行前返回权限错误。statement_execution 延续实际 SQL/MongoDB 执行、安全检查、试用限制、错误修复与写入中止规则。

RunTools._schema 统一登记 prepare 读取与后续 getDatabaseSchema 调用。SchemaEvidence 区分服务原始结果、模型实际可见结果、artifact 分页；读取结构永远不增加 statements_attempted/statements_executed。

完整元数据需要：目标每个数据库都已读；原始结果是合法表目录；incomplete 明确为 false；不存在截断或非空 errorMessage；目标表均存在；目标表列目录、列名、type、nullable 均可用。空的完整表目录可证明数据库没有表。缺目录、null、partial、缺完整性标记、目标缺表、列属性缺失、尚未完整读取的输出 artifact 都只支持局部证据。

comment:null 等显式属性空值登记为 knownNullAttributes，缺失属性登记为 omittedAttributes，二者不会混淆。注释为空不会导致有效列结构被判失败；没有捕获的默认值、注释等不能推断成不存在，EVIDENCE_RULE 继续约束模型的属性结论。

输出被 bound_json 裁剪后，只有 readToolOutput 从 offset=0 连续实际送达整个 artifact，并与原始 schema 一致，才升级为完整。尚未全量分页时，原始结果中未交给模型的表名/属性不计入可见事实。模型提前结束时输出确定性的局部结构未完成说明，包含范围、可见表、限制和缺失表；不把截断数据恢复成成功报告。

## 总结与推理调用

SQL direct answer 与 doTerminate 后 summary 使用同一 completion_override：metadata_only 依赖完整目标范围元数据；statement_execution 依赖真实成功语句。零成功语句都返回权威未完成报告；明确禁止执行的请求保持禁止说明，真实语句失败保留错误。direct 零 SQL 原有 RuntimeError 改为与 terminate 一致的未完成总结，受控测试仍断言没有成功执行或虚构成功。

已执行成功写入去重、未知写入结果中止、工作流导入验证规则继续保留。失败后被模型修复并成功执行的语句仍保留历史错误观测，不因曾经报错而掩盖随后验证到的真实成功。

summary_prompt_messages 装配原 `tool-call-summary_en.md` / `tool-call-summary_zh_CN.md` 的 system/user 段落。只剔除精确匹配的原 Agent 首个 SystemMessage，保留 schema、有效历史、工具过程、原问题与 EVIDENCE_RULE；最终 ModelStream 追加 REPORT_CONTRACT，使 Markdown 正文放入严格 JSON report 信封，公共 SSE 只展示解封后的报告。

用户可见工具决策与最终总结明确 emit_reasoning=True；内部步骤浓缩明确 False。固定规划提示改为 chat.planning，多语言资源覆盖 en/zh-CN/zh-TW/fr/es/ms/ja。元数据未完成说明也通过各语言资源输出。

## 验证

使用现有 `backend/.venv/Scripts/python.exe`；没有安装依赖、启动 Docker 或调用真实模型。

| 范围 | 结果 |
|---|---|
| 最新目标/结构新测试 | 34 passed |
| SQL 图、分类、终止、真实 SQLite 错误修复 | 64 passed |
| SQL 事实、模型参数、DSML、输出裁剪、循环、native 驱动控制用例、历史信封、可观测链 | 84 passed |
| 七语言分类/错误与结构提示 | 21 passed |
| compare/workflow 与真实 PG/MySQL 图 fixture 更新 | 20 passed，6 环境依赖 skipped |
| Ruff app/agent 与新增目标测试 | All checks passed |
| mypy app/agent --follow-untyped-imports | Success，30 source files |

新测试覆盖 metadata 普通分类/confirmed、direct/terminate 双路径、显式 null、服务失败/partial、目标缺失、完整分页、metadata 伪造 SQL 工具和直调绕过、低 confidence/模糊澄清、strict 字段拒绝、混合结构与实际查询/写入，以及跨库目标证据覆盖。既有 SQL confirmed fixtures 都增加显式目标响应，模型调用次数/usage/assertion 索引同步调整；没有删除驱动、安全、真实结果或禁止 SQL 断言。

最新新增的缺完整性标记、混合写入与跨库证据测试已包含在 34 passed 中。最终全 app Ruff/mypy 与组合测试以主代理报告为准。

## 未验证与交接

- 此处语义目标测试使用受控 HTTP 模型输出，证明严格合同与执行链边界；不能代替真实模型对自然语言 goal 的准确率验证。
- 本子任务没有启动 Docker、执行真实模型或 PG/MySQL 外部目标。10 表演示数据库内容与内部目标没有耦合；线上 scope 全量元数据若超过工具输出限制，模型仍需要实际分页后才能完整交付。
- 演示结构的 databaseName='*' 脱敏继续由原服务保证；本次证据与未完成总结只使用数据库 ID，不把底层 blog 数据库名称引入公开摘要。
- 已检查根和 SQLChat AGENTS.md；功能边界和核心目录没有改变，保持原文件。
- 最终验收应关注真实模型能否对 10 表结构正确分页，并在无需 SQL 的结构问题上只用元数据完成；提前终止必须如实报告局部结构，不得放松证据判据。
