# S13 后端产品行为 / DSML

本目录记录后端实现与分层验收，不能代表前端交互、真实 Flash 效果或真实 Celery 部署已经通过。独立副本基线是 accepted `637be1da324a677df17bf52d300adb65bee60169`，保留 `615ff1f` 密码 repr、`780becf` STOP、C09 元数据脱敏与此前 S08/S09/S10/S11/Mongo/数据库族代码。

## 最小变更

26 个 owned 文件：15 个应用模块和 11 个测试；唯一既有测试修正是 `test_db_config.py` 三个 publish mock 接收 locale headers，原业务参数和断言不变。`main.py` 仅增加 trial router import / registration。

- DSML：只在已暴露工具的模型调用中恢复完整受限协议；fullwidth/ASCII DSML wrapper 或独占 DSML invoke 可恢复，普通 simplified invoke 需同一 structured call 作证。正文和代码示例不会执行；工具 allowlist、已知旧参数别名、参数结构/必填项/未知字段、重复 ID、无穷数和歧义明确失败。原 valid structured JSON object 优先；空或语法损坏参数可由相匹配 DSML 补齐，ID 保留。不同工具名、数量或缺失 ID 不做猜测。
- 分片按 index 独立聚合 ID / name / arguments，修正 LangChain 对同 index、不同 ID 片段的分组行为。reasoning、response metadata、真实 usage 保留；重复 usage 只采用最终快照；调用温度和分类 thinking 参数保持 accepted 原规则。
- summary_delta 跨块保留待判定协议片段，完整最终摘要使用同一清理结果，POST SSE 与历史一致。content 普通正文保留原文本，不恢复执行。classification JSON 不清理。取消检查仍先于恢复、工具和收尾；usage finally 至多一次。
- `/api/trial/status` 公开返回原包装；confirmed HTTP 与 graph/classified 双入口拒绝试用 workflow/db_compare（低置信 / clarification 也不绕过）。普通资源授权、允许写入、现有受限 API、内置脱敏不扩大/删除。
- 初始化恢复原固定安全 warn + skip（连接不全 / admin 不存在），完整路径去重、密文、version 与队列保持。
- 7 语言为 en、zh-CN、zh-TW、fr、ms、ja、es。澄清、classifying、routing 从原 i18n 资源取文案，原主意图 + 可选 simple 降级的 1/2 项恢复；流错误使用现有键或独立安全文案。create/update/refresh 从 HTTP 捕获规范化 locale，Celery headers 明确传入，业务 args 仍 `(id, version)`；worker ContextVar scope finally reset，旧无 header 默认 en。

## 原源码依据

只读原目录 `db-genius/db-genius-backend`：

| 行为 | 原具体路径 / 方法 | 本次差异 |
|---|---|---|
| DSML 恢复 / 摘要清理 | `db-genius-agent/src/main/java/com/dbgenius/agent/DsmlToolCallParser.java`；`ToolCallAgent.java:333,494–539,686` | 恢复在取消之后；有效 structured 参数优先；协议摘要剥离。Python 增加受限上下文和明确歧义拒绝，防普通示例执行。 |
| DSML 参数类型 / 残余正文 | `db-genius-agent/src/test/java/com/dbgenius/agent/DsmlToolCallParserTest.java` | 首见类型、string=true 保留空白、数字/boolean；完整块与残余 wrapper 保留普通正文；非有限数字失败。 |
| 试用状态 | `db-genius-web/src/main/java/com/dbgenius/controller/TrialController.java:18–25` | 补公开状态路径，响应 `{code,message,data:{trialEnabled}}`。 |
| 试用接口 | `db-genius-service/src/main/java/com/dbgenius/trial/TrialGuard.java`、`TrialGuardAspect.java`；服务 `@TrialDeny` | 多数 accepted guard 保留；仅补 intent 双入口、状态路由与初始化原跳过行为。 |
| 初始化 | `db-genius-web/src/main/java/com/dbgenius/config/TrialDataInitializer.java:45–99` | incomplete/admin 缺失固定安全警告并跳过；去重/加密/enqueue 保留。 |
| 澄清选项 | `db-genius-web/src/main/java/com/dbgenius/intent/IntentRouter.java:164–207`，`buildOptions` | accepted 固定 4 项改回主意图首项、非 simple 才加 simple；缺 SQL/compare 条件替换首项提示 label。 |
| SSE 文案 | 同 `IntentRouter.java:71–80,117–119,209–216`，`intentLabel` | 原 `chat.classifying`、`chat.routing`、`chat.clarify.*`、`intent.*` 七语资源复用。 |
| 固定 status/doc 边界 | `db-genius-model/src/main/java/com/dbgenius/model/enums/DbConfigStatus.java`；`db-genius-service/src/main/java/com/dbgenius/service/database/DatabaseDocRenderer.java` | 原固定中文状态、英文元数据文档保留；不翻译业务字段、SQL结果、组件诊断。只将可译 BusinessError 按任务 locale 安全诊断。 |
| 销售删除 | `db-genius-web/src/main/java/com/dbgenius/controller/SalesContactController.java:19–26` | accepted 无路由；测试 `/api/sales/contact` 返回 404，没有成功空壳。 |

## 验收与命令

从本目录所属独立副本执行（使用共享已安装 Python，不安装依赖）：

```powershell
& C:/Users/22126/Desktop/web/text2sql/sqlchat/backend/.venv/Scripts/python.exe docs/phase-13-backend-product/verify_checks.py
& C:/Users/22126/Desktop/web/text2sql/sqlchat/backend/.venv/Scripts/python.exe docs/phase-13-backend-product/verify_real_targets.py
```

`verify_checks.py` 只保存命令、exit、count、时间、失败 test ID 和源 SHA，逐阶段落盘；不保存 provider body、完整 prompt/reasoning、密钥。`verify_real_targets.py` 内部 read-only inspect 精确专用 PG15432/MySQL13306 绑定，凭据只传子进程，脱敏后输出结果；不操纵生命周期。随机 `s13_trial_<uuid>` 表仅精确建清，生产服务权限与图使用 SQLite 系统 store，模型由本地实际 HTTP/SSE 服务器模拟。

当前结果读 `checks.json`、`real-trial-targets.json` 和 `preparation-checks.json`；后者与 `real-trial-targets-preparation.json` 仅历史预备证据，不作为最终原澄清文案证明。前次 15 文件检查会话遗失终态，因此本次仅重做缺失收尾，未将缓存或进度点当成通过，也未重跑已完整 183 项。

## 状态与限制

- 后端确定性与协议、真实 PG/MySQL 副作用分开记录。真实模型（deepseek-flash 同参数对照）留 S15，未用 mock 替代。
- 真实 Celery worker 的多语言消息、Nginx/部署/重启留 S14 独立验收，本阶段用真实 Celery task request 对象及并发作用域契约；不是外部 worker 通过声明。
- 原前端 UI、七语页面与 EOF 交互由前端 owner 验收；本阶段只给后端 HTTP/SSE/history 对应证据。
- 用户未配置真实 OSS/OCR，保留 S10 模拟证据，真实 T17 环境阻塞，本阶段不寻找凭据。
- 关系库/native/Mongo/Workflow/compare/observability/依赖均非本阶段改动范围；S11 静态工具过程文字保留 accepted 行为。C09 部分 metadata、PG 游标、write outcome/cancel、模型参数均由守卫保留。
- root 与 sqlchat AGENTS 已检查，能力边界和核心目录无变化，文件保持不变。未修改共享 WT/原 Java，未提交/reset/清理/启停容器。

冻结后按 `final-freeze.json` 精确文件、bytes 和 SHA 验收；`public-diff.patch` 相对 BASELINE，仅 owned 代码/测试，`guards.json` 检查剩余 accepted app/关键公共文件。
