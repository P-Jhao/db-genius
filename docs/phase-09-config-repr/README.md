# 数据库连接配置 repr 脱敏独立修复

基线：accepted a56734b（Mongo/S11 已接受；仅额外文档补录）。

`DbConnectionConfig.password` 使用 `field(repr=False)`，阻止异常诊断和 pytest fixture repr 自动回显密码。字段、顺序、构造参数、`config.password`、`asdict` 及驱动收到的值保持原样。不是完整序列化脱敏；受控业务持久化仍需密码值，输出不可直接使用 `asdict`。

仅修改 `backend/app/adapters/types.py`，新增 `backend/tests/test_connection_config_repr.py` 和本说明；不含 schemaName、Oracle/SQL Server 注册或其他 native 草稿。AGENTS.md 边界/目录不变，检查后保持原样。

验证：`ruff check app/adapters/types.py tests/test_connection_config_repr.py` 全通过；strict `mypy app/adapters/types.py` 1 source file 通过；`pytest tests/test_connection_config_repr.py -q` 1 passed（2.29s）。测试经真实 SQLAlchemy/PyMySQL driver entry 捕获原密码值，无目标实例网络连接。
