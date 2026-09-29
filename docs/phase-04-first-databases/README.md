# S04 MySQL / PostgreSQL 适配器交接

状态：实现及独立真实数据库验证通过；尚待主代理差异审查、服务层接线及阶段提交。

## 范围与接口

对应 F-03、F-04、F-08、F-16 和 T-06、T-11 至 T-14、T-24 的适配器部分。目标库连接与系统库连接分开。上层完成用户归属检查、连接口令解密和试用状态判定后，构造 `DbConnectionConfig`，经 `get_adapter(db_type)` 调用：

- `validate_config(config)`：关系库主机、端口、库名、用户名和密码必填，错误显式抛出。
- `test_connection(config)`：真实执行 `SELECT 1`，连接失败抛异常。
- `extract_metadata(config)`：中性 `SchemaMetadata`，PostgreSQL 只取 `public`；单表失败保留其他表并标记 `incomplete/errorMessage`。
- `generate_document(config)`：使用相同元数据源生成原格式 Markdown；不完整信息写入文档。
- `execute(config, sql, trial_mode=False, timeout_seconds=30, max_rows=100)`：实际提交普通写入、只读事务执行试用查询，返回 JSON 可序列化结果。
- `is_read_only(sql)`：使用相同 SQLGlot 安全判定。

`QueryResult` 查询路径含 `success/rowCount/data/truncated`，非结果集路径含 `success/affectedRows/message`。未知 affected row count 为 `null`，不会用 0 冒充。Decimal 输出字符串保留精度，日期时间输出 ISO 文本，二进制输出 Base64。未知类型抛错。结构化 SQLAlchemy URL 保留含 `@:/#` 的密码。

## 安全与执行

SQLGlot 按目标方言解析完整语句。多语句、无法分类的命令、DROP、TRUNCATE、ALTER ... DROP 均拒绝；试用模式还拒绝写入 CTE、SELECT INTO、普通 DML/DDL。MySQL 可执行注释拒绝，普通注释和字符串中的禁用词不会误伤。MySQL 支持 SHOW/DESCRIBE/EXPLAIN；PostgreSQL 支持简单 SHOW 和 EXPLAIN 语句。普通 INSERT/UPDATE/DELETE/CREATE 已实测。

每次操作使用 `NullPool` 和上下文管理关闭目标库连接，不留按用户增长的持久连接。PostgreSQL 用事务内 `statement_timeout`；MySQL SELECT 使用 `MAX_EXECUTION_TIME`，驱动还有 socket 读写超时。结果使用流式游标只保留至多 101 行用于判断是否截断；关闭游标会消耗尚未读取的 MySQL 结果，但不会全部保存在内存。响应前检查实际耗时，超过限制抛错。MySQL `SLEEP()` 被中断时可能返回普通值，所以墙钟检查是必要的。

MySQL 写语句不受 `MAX_EXECUTION_TIME` 全面约束。驱动读超时使调用失败并释放连接，但断线后的服务器执行与提交状态可能未知；上层不可自动重试有副作用的操作，也不可声称已回滚。独立在途取消接口留待 S08 设计和驱动验证。

## 验证证据

环境：既有独立容器 `sqlchat-migration-test-mysql`（MySQL 8，`127.0.0.1:13306`）和 `sqlchat-migration-test-postgres`（PostgreSQL 16，`127.0.0.1:15432`）。测试从容器环境读取测试口令到进程变量，不写入文件。临时表和角色使用随机名并在测试结束删除；首次夹具失败产生的三个表、两个角色已按确切名称核对并清理，未操作容器本身。

| 检查 | 命令/方式 | 结果 |
|---|---|---|
| 安全与契约单元测试 | `python -m pytest tests/test_adapters_safety.py tests/test_adapters_contract.py -q` | 32 通过 |
| 真实数据库集成 | `python -m pytest tests/test_adapters_integration.py -q --tb=short`，提供 `SQLCHAT_TEST_PG_*` / `SQLCHAT_TEST_MYSQL_*` 测试环境变量 | 3 通过 |
| 静态检查 | `python -m ruff check app/adapters tests/test_adapters_*.py`；`python -m mypy app/adapters` | 通过 |

真实用例包括：带空格表名、表/列注释、索引、102 行截断为 100 行、读写和试用拒写、特殊口令用户、含 `%` 的 SQL 与 LIKE、1 秒慢 SELECT 和 MySQL 慢 UPDATE。PG 受限角色对第一张表无 SELECT 权限时，行数为 `null` 且标记不完整；第二张可读表仍正确得到行数 1，证明 savepoint 隔离。

## 后续接线与限制

S05 数据源服务接入适配器时负责用户归属、解密、状态和任务版本，不把明文密码写到公共 VO。S07 Agent 工具从服务层调用同一 `execute`，传入系统设置的 30 秒 / 100 行和实际试用状态。S08 验证取消在途 PG/MySQL 查询和未知写入结果。当前适配器没有取消句柄，也没有测试任意方言 DDL；无法可靠解析的 SQL 会显式拒绝。PostgreSQL `EXPLAIN (FORMAT ...)` 等扩展形式尚未覆盖。MySQL 大型流式结果的游标关闭需要消耗剩余行，可能延长总耗时；不会把超时后的结果报成成功。

仓库 `AGENTS.md` 已检查，主代理已将新增的 `backend/app/adapters` 核心目录写入目录说明；本阶段不包含其他功能边界调整。
