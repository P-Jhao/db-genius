# S13 需求与路径矩阵

| 编号 | 路径 / 当前实现 | 验收 / 证据层 |
|---|---|---|
| F12 / T20 / T21 | model + streaming + dsml；HTTP分片/index/ID/参数/reasoning/usage、下一步 tool ID | `test_model_protocol`、`test_model_parameters`、`test_dsml`、`test_dsml_revision`，真实本地 HTTP 协议模拟 |
| F12 / T22 / T36 / C06–07 | content、summary_delta、summary、clarify、error、done；ms timestamp；最终history | `test_dsml_http`、`test_chat_api`、`test_product_locale`、`test_locale_concurrent_sse`；SQLite/history + 本地HTTP |
| F13 / T23 / C07 | classification/stream/tool/summary cancel，partial/usage finally | 预备完整 `test_chat_abort`、`test_chat_abort_api`、`test_context_cancel` 以及 DSML取消专项；未改S08驱动/记账逻辑 |
| F16 / T30 | trial/status public；原13类禁止路径与upload；builtin get/list/doc mask | `test_trial_api_matrix`、`test_trial`；真实HTTP/FastAPI业务+SQLite |
| F16 / T30 / C08 | confirmed入口precheck、classified入口低置信拒绝；正常模式资源权限保持 | `test_trial`、`test_product_locale`、既有 chat/graph及Mongo config/credentials guard |
| F16 / T13 / T12 | trial读取/拒写；普通update commit；DROP/TRUNCATE硬拒绝 | `test_trial_targets`、`test_trial_graph_targets`；真实PG/MySQL4case，HTTP模型模拟 |
| F16 | trial初始化完整/不完整/admin缺失/去重/加密/enqueue | `test_trial`；原源对照，SQLite；保持worker旧版本/删除隔离 |
| F17 / T31 / C05 | 7语言错误/classifying/clarify/路由label/model语言；同/并发HTTP/SSE | `test_product_locale` + `test_locale_concurrent_sse`；后端完整，UI未由本阶段验 |
| F17 / T31 / C05 | create/update/refresh headers规范化；task args两项；worker scope恢复/旧无header | `test_queue_locale`；Celery task对象/并发线程/SQLite production worker业务，外部worker未验 |
| T35 / F19 | 原 sales/contact 不存在且没有成功空壳 | `test_trial_api_matrix`；后端404/OpenAPI扫描；页面归前端owner |
| C01–04 | /api、camelCase、success包、既有token/用户权限 | `test_trial`、`test_chat_api`、queue API、trial矩阵；auth核心未改 |
| C09 | 新trial VO无密码、builtin隐藏；异常不输出provider正文/真实密钥；repr fix守卫 | trial矩阵/7语错误；accepted615 repr与637 metadata脱敏全文件SHA守卫 |
| S09 / S10 / S11 | context/loop/output page；workflow/compare/Mongo只读 | 预备183联合集合+final output/partial/Mongo config组合；business文件未修改守卫 |

状态用“模拟通过 / 真实环境通过”分别对应上述证据；本报告不标“完整迁移通过”。
