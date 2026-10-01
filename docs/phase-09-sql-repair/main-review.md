# 主代理独立验收

基于 `e58c8e9` 的 index 导出只含已验收 S09 功能的副本，覆盖子代理冻结清单的 7 个文件及清单本身；未复制 S10 文件/工作流或其他后续业务。冻结清单 SHA256：`496fee78b3c4873447eae53842e42821a757f2cbd9abe229f5dfef9bc9f58402`，7 个文件逐一核验成功。

主代理检查差异：既有 `types.py` 仅补 error/sqlState/errorCode 类型；既有 `tools.py` 仅补 DBAPIError 白名单处理。新增 sql_errors 模块保留语句一致、失效连接、回滚失败、系统错误及未知写入边界，不引入默认写入重试。原取消传播与成功写入拒绝重放保留。

在独立副本 backend 目录使用仓库已有虚拟环境执行：

- `python -m ruff check app tests`：通过。
- `python -m mypy app`：57 个源模块通过。
- `python -m pytest -q tests/test_sql_repair.py tests/test_sql_error_boundary.py tests/test_sql_termination.py tests/test_chat_abort.py tests/test_chat_graph.py --tb=short`：44 passed，41.74 秒。

这些测试使用受控 HTTP 模型和实际 SQLite 数据库，不作为真实模型效果证明。真实 PostgreSQL/MySQL 诊断修复另在 S10 冻结回归验收，不把子代理的该阶段结果冒充本次独立复验。

已检查工作区根和 SQLChat 的 AGENTS.md；没有核心目录或功能边界变化，本修复不修改 AGENTS.md。按清单暂存，仅本地中文规范 fix 提交，不覆盖共享工作区后续草稿。清单描述冻结副本字节；Git 的换行规范化可能改变工作树字节表示。

本地提交：`a83368f fix: 允许模型修复安全可恢复的数据库语句错误`。本页的补录不改变冻结副本 SHA 清单的历史含义。
