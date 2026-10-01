# S11 数据库结构对比交接

## 基线与范围

最终隔离副本基于 accepted `9703123f279b669276b3e655b926b63365047e89`，保留 S10 `13d4595`、SQL repair `a83368f`、模型参数 `a8e6a3a`、部分元数据连接规则 `bdc0cc8`、MySQL family `ef1c17c` 和独立 PG 游标修复 `9703123`。原 S11 草稿基于 `ef1c17c`，已核查本阶段三份既有业务文件在新 accepted archive 中未被其他阶段修改后，仅移植本阶段授权改动；graph.py/streaming/context_compress/adapter 及全部其余 accepted 文件逐字节保留。未修改共享工作区、原 Java 项目或执行 Git 提交。

本阶段覆盖 F-10、T-03/T-14/T-18/T-19/T-23/T-27/T-36，以及对比安全结论的七语言输出。已有 AGENTS.md 已检查，功能边界与核心目录均已列出结构对比能力，不新增实现细节记录。

## 行为与证据

- `pre` 是当前结构，`test` 是期望结构。确定性报告保留 `newTables`、`droppedTables`、`alteredTables`，支持 ADD_COLUMN、DROP_COLUMN、MODIFY_COLUMN、MODIFY_NULLABLE；按实际标识符比较，排序稳定，不推断跨引擎类型等价，也不宣称覆盖触发器、过程、权限等对象。
- 报告额外包含 `preSchema` / `testSchema` 两份本次 compare 实际抽取的 SchemaMetadata，供新增表字段、类型、nullable、主键以及新增 NOT NULL 列的部署报告取证。仅复用已获得的两侧结构，不重新查询以替换对比时点。既有 diff 字段不变；这两个附加字段增大报告体积，可能触发原 4000 字裁剪，完整制品分页与已完整读证守卫继续生效。
- 元数据仅来自服务端已归属且就绪的数据源配置。请求选定的 pre/test 顺序不能由模型交换。对比 executeSql 仅接受本轮 pre/test ID，按该配置的真实 adapter.is_read_only 判断并执行，模型提供的 dbType 不能影响方言。检查与执行使用同一已解析配置。
- 拒绝 SELECT INTO、可写 CTE、嵌套写和多语句。合法 SELECT、目标方言 SHOW/DESC/EXPLAIN 仍可读取；对比只读执行开启 adapter 的物理只读事务保护，保留超时、取消与最大行数边界。迁移 SQL 只作为报告输出，执行工具不会执行。
- 原 db-compare 提示词保持不变。完成实际 compareDatabases 后，只有完整同引擎、非推断且模型已取得完整报告的情形允许正常模型总结。未调用对比、部分读取失败、跨引擎、采样推断或未读完裁剪报告会输出确定性限制说明，模型无法覆盖该结论。
- 裁剪报告使用 RunTools.last_result 作为权威来源；readToolOutput 页必须与该报告的实际偏移、总长和内容一致。重复预览、空洞页或其他制品不能解除截断状态。
- 兼容未来 Mongo 的 schemaInferred/sampleSize 可选字段，出现时严格校验类型。sampleSize 是**每个集合的采样上限**，不是实际读取总数；空库仍可能声明该上限。采样本身不作为读取失败，明确报告观察到的差异及未观察到的字段仍可能存在，不承诺精确无差异或可直接执行迁移。实际 metadata 错误仍 complete=false。
- 安全总结支持 en、zh-CN、zh-TW、es、fr、ja、ms，直接翻译固定事实与限制文案，保留数据库名、错误和中性字段变化，不调用 LLM 重写。仅此对比分支在本阶段处理；S10/SQL repair 的历史安全文案缺口留 S13。
- 元数据取消在两侧读取前后检查；取消后不再读取另一侧或调用总结模型。当前 extract_metadata 内部不具备在途取消接口，已有目标超时继续生效，不声称中途已终止服务器元数据查询。

## 测试范围

真实 PostgreSQL 15432 和 MySQL 13306 使用 UUID 命名的可销毁 pre/test 数据库，覆盖增删表、增删列、类型/nullable 变化、方向反转、跨引擎、反引号或双引号特殊名称、受控读取与拒绝写入。测试仅销毁自己创建的数据库。PostgreSQL nextval 的副作用被真实只读事务拒绝，序列状态保持未调用。

部分元数据失败测试在真实 driver 查询中注入不存在字段错误，其余提取与目标均真实；这不是自然权限配置故障的环境取证。真实适配器整合测试的配置 Session 为受控代理；跨用户、状态及模型参数权限另外由真实 SQLite 应用配置库和 FastAPI 测试覆盖。

模型响应来自受控真实 HTTP SSE 服务，覆盖实际对比、分类、工具回传、总结、截断页、取消、失败、usage 和历史回放。七语言测试比较方向、数据库名称、实际列变化、采样限制与安全结论，不以英语词序固定翻译。

未来 Mongo JSON 只读策略委托与推断元数据测试为受控模拟；本基线 registry 尚不包含 Mongo，不能作为真实 Mongo 结构对比通过证据。OSS/OCR 实际服务仍缺环境配置，本阶段不伪报外部验证。前端未修改，已有 S10 build/upload 契约保持原样。

## 验证与冻结

使用 `run-checks.ps1` 从专用 Docker 容器内部读取测试环境，不回显密钥，执行 Ruff、严格 mypy app 和完整 pytest；真实 PostgreSQL/MySQL/MariaDB 基线回归均启用。

最终 accepted `9703123` 基线运行：

- `ruff check app tests`：通过（ruff.txt）。
- `mypy app`：严格检查 79 个模块通过，未使用 ignore-missing-imports（mypy.txt）。
- `python -m pytest -q -rs --tb=short`：**521 passed、6 skipped，614.36 秒**（pytest.txt）。本次没有失败，包含新增权威 schema、真实比较读取错误反馈/修正、七语言安全报告、PG 游标修复及全部已接受 S10/模型参数/SQL repair/取消回归。

6 项跳过逐项记录：S15 专用真实效果目标验证入口未显式启用 2 项；live Celery worker 的 SQLCHAT_TEST_BROKER_URL 未配置 2 项；未使用 broker 端口的负向环境未配置 1 项；Windows 目录符号链接权限不足 1 项。它们不是通过证据，也不影响本阶段实际 PG/MySQL/MariaDB 连接、结构和执行覆盖。外部 OSS/OCR 缺配置的限制保持原 S10 记录。

首次完整回归 `pytest-initial.txt` 记录 491 passed、4 failed、6 skipped（393.63s）：三项多语言测试词序假设错误，以及真实 PostgreSQL EXPLAIN 在服务器游标下执行失败。前者已修正，34 项对比语言/证据/graph 局部回归通过（27.53s）；后者已独立验收提交 `9703123`，不混入 S11 feature。

权威 schema 字段增加后的独立 `test_schema_diff.py` / `test_compare_evidence.py` 回归 20 passed（6.42s），覆盖新增表主键及可空类型、新增非空列、partial schema 与大结构分页。不涉及主验收正在使用的 PG app 系统库。

随后新增受控比较读取可恢复错误的 PG/MySQL 两项测试，定向运行 `pytest-repair.txt` 记录 2 failed（16.79s），均发生在建立 disposable target 前的连接超时/拒绝。只读 docker inspect 当时确认专用 PG/MySQL/MariaDB 均 exited；未自行启动或绕过。主代理恢复专用目标后，两项均已在本次完整真实回归通过；保留失败日志以区分当时环境失败与最终结果。

`files.tsv` 为本阶段 14 份授权源/测试和交接文档、脚本、日志及 `preserved.tsv` 的 SHA-256/字节数清单，不包含自己的 SHA。`preserved.tsv` 对 accepted archive 中其余文件逐字节核对；既有业务仅 graph_sql.py、tools.py、database_tools.py 三份发生本阶段改动。独立 PG 修复的 adapter/test/docs 作为本次 accepted 基线保留，不重复交付或覆盖。

本阶段无前端改动，不重新声称进行了前端 build；沿用已验收 S10 build/upload 证据。主代理后续 `ecb011f` 仅增加交接 receipt 文档，没有业务/测试变化；当前真实 gate 保持基线 `9703123`，主代理集成需保留其最新文档。冻结后业务不再改动，等待主代理独立验收。
