# PostgreSQL 只读游标主代理验收

基于 accepted 3d1c5cc 独立导出，逐项验证子代理冻结清单 9 个文件的原始 SHA-256，并验证 ef1c17c 原始 accepted archive 中 432 个保留文件。ef1c17c 到本次基线只有 4 份验收回执文档变化，业务、测试与依赖没有变化。

主代理复跑 ruff check app tests、严格 mypy app（76 个模块）均通过；18 个指定测试文件在独立 PostgreSQL 16、MySQL 8、MariaDB 11.4 实例上 **208 passed、0 skipped，116.92 秒**。命令及输出见 main-checks.txt。本次没有真实模型调用，也不代表 S11 功能已验收。

审查确认只有 PostgreSqlAdapter 的游标选择及 RelationalAdapter 的对应 hook 改动。SELECT/CTE SELECT/集合查询继续使用真实具名服务器游标；SHOW/EXPLAIN 使用普通游标，保持结果裁剪、事务、安全判定及驱动取消。新增测试观察真实 psycopg cursor；禁止写入在连接前拒绝；EXPLAIN ANALYZE 慢查询取消经服务端确认。

普通游标可能在驱动内部缓冲命令结果，返回行上限不能当作这些命令的流式内存承诺。S11 仍需在接受本修复后验证真实比较服务与报告分支。

files.tsv 与 preserved.tsv 保留原冻结字节证据；主代理提交副本仅统一文档、日志和运行脚本末尾换行，清单不是提交后文件字节摘要。原冻结副本未改变。末尾换行调整文件如下：
- docs/phase-05-pg-read-cursors/mypy.txt
- docs/phase-05-pg-read-cursors/pytest.txt
- docs/phase-05-pg-read-cursors/ruff.txt
- docs/phase-05-pg-read-cursors/run-checks.ps1

AGENTS.md 已检查，工程功能边界与核心目录未改变，保持 accepted 版本不变。未修改原 Java 源码、共享业务草稿或任何凭据；本次仅主代理恢复四个既有专用测试数据库，没有新建/删除数据卷或容器。

本阶段已接受提交：9703123（fix: 修复 PostgreSQL 只读命令游标与查询流式执行）。提交号在后续文档回执补录，未改写功能提交历史。
