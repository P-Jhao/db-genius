# SQL 驱动错误修复边界

基线：已验收 S09 `0bd3fc8`。待主代理独立验收并以 `fix:` 提交；本目录不代表已提交。

原链路中，目标数据库返回语法、表名、列名等可修复错误时，会直接中断 Agent，模型没有机会按 spec/05 §5.1 调整 SQL。`RunTools.execute` 现在仅将明确白名单诊断转换为 `success=false` 的工具结果；模型仍受步数、重复调用、权限、SQL 安全规则以及已成功写入禁止重放的约束。失败不计为成功执行。

PostgreSQL SQLSTATE 白名单：42601、42P01、42703、42702、42803、42883。MySQL 错误码：1052、1054、1064、1146。SQLite 仅在测试边界接受已知语法/不存在表、列、函数/歧义列诊断。

白名单还必须同时满足：错误中的 statement 与当前目标语句一致；连接未失效；适配器已回滚且没有“Rollback also failed”说明。系统库查询错误、未知写入结果、取消/超时、完整性冲突、权限和安全拒绝继续抛出或中止，不能进入默认写入重试。

独立文件集合：`backend/app/agent/tools.py`、`sql_errors.py`、`backend/tests/test_sql_repair.py`、`test_sql_error_boundary.py`，以及本目录文档/证据。只依赖 S09 既有模块，不依赖 S10 workflow/schema/file 服务。

验证：`python -m pytest -q tests/test_sql_repair.py tests/test_sql_error_boundary.py tests/test_sql_termination.py --tb=short`，真实模型 HTTP 协议模拟与实际 SQLite 目标执行；PG/MySQL 驱动诊断另由 S10 的真实目标工作流回归覆盖。结果见 `pytest.txt`。当前仅模拟模型协议，不代表真实模型 SQL 准确率。
