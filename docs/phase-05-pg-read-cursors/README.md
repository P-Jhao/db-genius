# PostgreSQL 只读命令游标独立修复

## 问题与修复

基于 accepted `ef1c17c6f11aecf386139c38f350db5f51684b88` 的独立导出，不包含 S11 业务或公共元数据新接口。S11 真实回归发现，合法 `EXPLAIN SELECT ...` 被 psycopg 包装成 `DECLARE CURSOR FOR EXPLAIN ...`，PostgreSQL 返回 SyntaxError；`SHOW` 同样不属于可 DECLARE 的查询。

`RelationalAdapter` 仅新增 `_stream_results` hook，默认仍沿用原 read_only 选项。`PostgreSqlAdapter` 对已经通过原安全校验的只读语句按目标 PostgreSQL AST 判断：SELECT 与 set operation 保持服务器游标，SHOW/EXPLAIN 使用普通游标。安全策略、StatementPolicy、SQL 文本、事务、超时、取消、行数限制和重试规则均不变；不重试失败 SQL，也不关闭所有 SELECT 流式读取。

普通游标结果仍 `fetchmany(max_rows+1)` 并裁剪返回。普通游标可能在 driver 内部缓冲命令结果，不能声称这些命令具备 SELECT 的服务器流式内存边界；常规 SELECT/CTE SELECT/UNION/INTERSECT/EXCEPT 保持真实 ServerCursor。

## 验证

使用 `run-checks.ps1` 在专用 PG 15432 / MySQL 13306 / MariaDB 13307 环境运行，不回显容器中的凭据。

- `ruff check app tests`：通过（ruff.txt）。
- `mypy app`：严格检查 76 个模块通过，未使用 ignore-missing-imports（mypy.txt）。
- 指定适配器、MySQL family、MariaDB、SQL repair、workflow repair、取消/中止回归：**208 passed、0 skipped，54.94 秒**（pytest.txt）。完整命令与环境读取方式见脚本。

新增 23 项独立测试中，18 项在真实 PG 的普通模式与 `trial_mode=True` 下执行 SHOW ALL、SHOW statement_timeout、EXPLAIN、合法 EXPLAIN ANALYZE、普通大 SELECT、CTE SELECT 以及 UNION/INTERSECT/EXCEPT，检查真实 psycopg cursor 是否具名。10000 行 SELECT 和 SHOW ALL 返回 7 行且明确 truncated=true。4 项 SELECT INTO、CTE DELETE、EXPLAIN ANALYZE DELETE、多语句在只读模式开连接前拒绝；1 项对真实 EXPLAIN ANALYZE pg_sleep 在途执行发起驱动取消，确认服务端终止且没有未知写入状态。

现有实际 PG/MySQL 执行、元数据、慢查询取消和 MariaDB/MySQL family 回归一并通过。`trial_mode=True` 测试覆盖对比工具使用的只读 adapter 执行契约；实际 S11 服务/graph 对比分支仍由 S11 在接受本修复后的独立整合回归验证，不能将本集合称为 S11 feature 验收。

## 冻结

`files.tsv` 列出仅两份适配器文件、一份独立测试、本文、运行脚本、三份日志及 `preserved.tsv` 的 SHA-256/字节数。`preserved.tsv` 记录 accepted archive 中其余 432 个文件均逐字节保留，包括模型参数、S10 graph/workflow、SQL repair、部分元数据规则、registry/types/WorkflowSchema/main.py。

AGENTS.md 已检查，功能边界与核心目录未改变，保持原样。没有 Git 提交、共享业务写入、原 Java 修改或容器启动/清理。冻结后交主代理独立复验，后续 S11 仅叠加本修复的 accepted commit。
