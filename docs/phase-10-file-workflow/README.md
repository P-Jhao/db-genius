# S10 文件与数据库工作流交接

功能基线：已验收 S09 `0bd3fc8`；独立 SQL repair 已由主代理验收并提交 `a83368f`，S10 feat 集合在此之后集成。开发仅在 `.git/acceptance/s10-integration-1790786050404` 隔离快照进行；共享工作区后续草稿及原 `db-genius` 未改动。已由主代理独立复验并提交 `13d4595`；不代表完整迁移完成，主代理证据见 [main-review.md](main-review.md)。

## 范围与契约

- F-09/F-11、T-03/T-12/T-15/T-16/T-17/T-36：`POST /api/file/upload`、文件归属、本轮附件授权、OSS/显式本地存储、六类文档解析、五类图片 OCR、工作流执行与查询验证。
- 文档：xlsx/xls/csv/docx/pdf/md；图片：png/jpg/jpeg/webp/bmp。上传单文件 20 MiB；`readImage` 沿用原 10 MiB 读取边界。表格返回最多 200 行并保留 `totalRows/data/truncated`；文本/OCR 最多 30,000 字符；PDF 最多 50 页，扫描 PDF 不承诺自动恢复内容。
- 上传返回原公开 VO：`id/originalName/fileSize/contentType/createdAt`；大小及类型允许 null。OSS key、用户 ID、磁盘路径不出现在 VO；模型只接受 fileId。
- `main.py` 相对 S09 仅新增 file router。依赖与锁文件使用 S09 已有文件 SDK，未加入 S14 依赖。AGENTS.md 只新增实际核心目录 `storage/parsers` 的结构说明。
- 保留 S09 的 `graph_sql` 拆分、原提示词、上下文治理、输出制品分页、usage、取消和已成功写入不重放规则。文件服务结果通过 `RunTools.last_result` 登记验证，模型裁剪后的预览不作为完整证据。

## 完成与部分处理的判定

表格导入先读取授权文件，按批执行 literal INSERT，并查询目标数据库中实际保存的列值。验证使用每个数据库的实际 schema、方言和列类型；成功 CREATE/ALTER 后刷新当前 schema，避免沿用旧列类型。MySQL 反引号及 PostgreSQL quoted 标识符均按各自规则处理。PostgreSQL `"Name"/name` 和 `"Imports"/imports` 保持区别；文本编号 `001` 不被数值 `1` 冒充，NULL 不与 `<NULL>`/`None` 文本碰撞。只有数值列按 Decimal 值归一化。

查询上限 100 行不自动使 200 行导入失败：多个直接 SELECT 的真实返回值可累计验证；分页还需有一致排序，重叠查询不能增加相同数据的重复数量。常量、计算值和 CTE 生成的数据不代替已存储行的观察。200 行来源通过完整覆盖后可报完成；207 行来源仍只解析前 200 行，完成写入这 200 行后必须报告部分导入，不能由 readToolOutput 恢复从未解析的行。

普通无附件工作流保留 INSERT/UPDATE/DELETE/CREATE；成功写入后须同数据库、同实际目标表的 SELECT 验证。MD/docx/pdf/OCR 等非结构化附件也可指导真实操作，不套用表格源行逐行覆盖条件；文字未结构化时不声称已逐行完整导入。任何来源截断均限制完整声明。失败读取停止后续写入；已知安全 SQL 诊断允许模型调整语句，未修复失败仍显示未完成；未知写入结果、中止和系统异常不得重试。

## 存储失败与补偿

上传验证通过后生成 `uploads/{userId}/{receipt}.{extension}`，不采用客户端路径。配置缺失或 OSS 失败明确失败，不自动改存本地。

1. 对象写入失败：返回存储失败，未登记元数据。
2. metadata flush 失败且 rollback 已确认：删除本次对象；清理失败返回明确错误并记录 receipt。
3. rollback 失败或 commit 返回异常：保留对象，标明结果需要核对；禁止自动重试和盲目删除。
4. commit 成功后 refresh 失败：保留已提交元数据及对象，标明“元数据已保存但确认失败”。独立连接仍可读取原文件。

服务器日志仅记录 receipt、userId、extension、状态和异常类型，不记录原异常详情或密钥。人工补偿时先确认数据库恢复稳定，用新连接查询该 receipt 对应对象键的 `app.uploaded_file` 记录；有记录时保留对象并恢复确认，无记录且提交结果已确认失败时才清理对象。当前不增加自动恢复写入任务或补偿 API。

OCR 优先采用完整 OCR 凭据对；OCR 双空时才使用完整 OSS 凭据对；任意半对配置显式失败。OCR 空白/空/nontext 内容均失败。没有实际 OSS/OCR 配置时不得报告真实服务成功。

## 验证证据

环境：Windows、Python 3.12.7、pnpm 11.1.3；专用 PostgreSQL 16 `127.0.0.1:15432`、MySQL 8.0 `127.0.0.1:13306`。连接凭据由测试脚本在进程内读取专用容器配置，没有保存或打印。

| 验证 | 状态与证据 |
|---|---|
| Ruff `check app tests` | 通过，`ruff.txt` |
| mypy `app` | 74 个源码文件通过，`mypy.txt`；SDK 边界用显式 Protocol/结构检查，未全局忽略缺失导入 |
| 完整 pytest，真实 PG/MySQL | 274 passed、4 环境跳过，312.62 秒；结果见 `pytest.txt`，包括原 S02–S09 与 S10 回归 |
| 上传 API、归属、超大/损坏文件、事务补偿 | 实际 FastAPI HTTP + SQLite 元数据/本地存储契约测试通过；生产 PG 元数据上传 API 不单独冒称完整联调 |
| CSV 导入两类真实目标数据库 | 本地上传→文件服务→实际 HTTP 模型协议→LangGraph→PG/MySQL 写入→查询验证通过 |
| 200/207 行、模型裁剪、制品分页、100 行 SQL 上限 | 两类数据库各执行 200/207 行，4 个实际集成用例通过；200 行完成，207 行明确部分导入 |
| 特殊标识符、小数、文本编号、NULL | 真正 MySQL/PG 反引号/引号表字段，CSV Decimal/XLSX NULL，PG 大小写表列正反例通过 |
| 普通 UPDATE/DELETE/CREATE、MD/OCR 指导 UPDATE | 实际 SQLite 目标与 HTTP 模型协议模拟通过；查询后才允许完成，截断文档拒绝全量声明 |
| 修复 SQL | 独立 `docs/phase-09-sql-repair` 集合已由主代理验收并提交 `a83368f`；S10 另覆盖两类真实数据库的 missing-column 修复与未修复分支 |
| 前端 frozen lock 安装、vue-tsc + 生产构建 | 通过，`frontend-install.txt/frontend-build.txt`；Vite 配置与包大小提示为既有构建警告 |
| 浏览器上传契约 | 2/2 通过，`frontend-upload.txt`；API 为模拟响应，明确区别于真实后端联调 |
| OSS/OCR SDK 契约 | 模拟服务通过；真实云服务因缺凭据/可用环境为**环境阻塞** |

完整 pytest 的环境跳过：S05 live Celery worker 2 项与专用断开 broker 1 项未在本轮设置测试环境；Windows 用户无创建目录符号链接的权限，相关 LocalStorage symlink 真实用例跳过 1 项。跨用户 fileId、OSS key 归属以及普通路径穿越检查均执行通过。这 4 项不能标为真实环境通过。

复跑：`docs/phase-10-file-workflow/run-backend-checks.ps1` 仅访问现有专用容器，不启动或清理容器；依赖运行时选当前 backend/.venv 或隔离快照对应仓库的既有 runtime。前端：`pnpm install --frozen-lockfile`、`pnpm build`、`node --test tests/s10-upload-contract.test.mjs`。

冻结文件清单见 `files.tsv`，包含实际 SHA256；独立 SQL repair 文件不在 S10 feat 集合中重复暂存。编译产物、缓存、node_modules、虚拟环境不交付。主代理验收后串行提交，不覆盖共享工作区后续阶段草稿。

## 下一阶段记录

- S11 另行派发：compare 读取限制须用各目标数据库既有安全 AST 判定，不能仅依据 `exp.Select`；拒绝 SELECT INTO、CTE 内写入和多语句，支持原合法 SHOW/DESC/EXPLAIN；同时补方言解析。当前未改共享 compare。
- S15 对照发现的独立模型参数缺陷由主代理另派 fix：普通 Agent/tool/summary 对齐 temperature 0.7；分类调用省略 temperature/top_p/max_tokens/response_format 并关闭 thinking，保留原提示词格式要求与 Pydantic JSON 严格校验。当前 S10 未修改模型协议或参数，真实模型效果对照仍待后续验证。
- 当前 WorkflowSchema 仅映射已验收的 MySQL/PostgreSQL；SQLite 为测试契约。后续数据库按 S12 单独扩展与验收；trial/DSML/观测/部署/Celery 后续稿未混入。
