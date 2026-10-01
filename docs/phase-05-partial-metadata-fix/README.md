# S05 部分元数据兼容修复

F-03 / T-05、T-06：连接成功与元数据完整性分别表示。原 DbConfigServiceImpl.java 187–199 行先根据 tryConnect 设置 CONNECTED，再生成文档；250–257 行将 adapter 的 errorMessage 交给 DatabaseDocRenderer 渲染。部分元数据不被当作连接失败。

accepted `5b9c543757cb4e83031226762131f36b6fa6907b` 的 Python worker 和手动 generate_doc 在 incomplete=True 时抛错，最终 status=2，文档被清空。该规则使已明确标记索引缺失的 StarRocks 适配器即使连接成功也不可用于聊天，是代码阻断，不是引擎环境故障。

独立修复仅修改 services/db_config_worker.py 的拒绝条件与 db_config.py 的 generate_doc：合法 SchemaMetadata 包含 incomplete 时照常渲染，连接成功保持 status=1，文档保留 Error reading metadata 及具体缺失信息。手动生成先验证真实连接，false 或异常仍失败，避免连接错误被适配器封装为部分元数据后假称已连接。元数据提取抛出、文档渲染抛出仍 status=2，并清空文档和时间；诊断继续脱敏。文档生成成功不表示 schema 完整，get_schema 的 incomplete 原样保留，比较工作流必须按自身规则提示不完整和人工复核。

版本/status 条件更新和用户归属未改。新增测试用独立临时 SQLite 系统持久化验证状态机，适配器使用明确测试替身：完整/部分 0→1、手动生成、刷新后旧任务退出、连接 false/异常、提取/渲染失败→2、执行期间更新版本或删除的条件更新隔离，以及跨用户 schema 和 SQL 服务拒绝。底层 schema 授权路径与普通 SQL 安全/repair 回归通过；S11 比较功能在本基线尚未接受，其高层完整验收由该独立阶段执行。此测试不是实际目标引擎或真实 Celery 验收。

命令（隔离副本 backend，使用现有虚拟环境）：

```text
python -m pytest tests/test_db_config_partial.py tests/test_db_config.py tests/test_adapters_contract.py tests/test_adapters_safety.py tests/test_sql_repair.py -q
python -m ruff check app/services/db_config_worker.py app/services/db_config.py tests/test_db_config_partial.py
python -m mypy app/services/db_config_worker.py app/services/db_config.py tests/test_db_config_partial.py
```

结果：54 passed、7 skipped；Ruff 通过，mypy 3 文件通过。七个 skip 为未提供系统 PostgreSQL、真实目标数据库或 broker 配置的既有 S05 用例，不计通过。主独立复验待执行。未触发真实目标或容器生命周期操作，未重跑先前 S14 worker/部署证据。

此 freeze 与 S12 family、Mongo、参数对齐和 S11 分开；没有复制共享草稿、改共享工作树/index、原 Java、family 冻结或 S15 helpers，未提交/reset/清理。AGENTS.md 已检查，核心目录和业务边界不变，保持原样。
