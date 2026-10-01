# 主代理连接配置 repr 验收

从 accepted a56734b 导出新副本，仅覆盖 3 个冻结输入。freeze.json SHA c34652522ce21a7a813fddd7d8e7f5376c03a35fd3f1f08d2a0a08cc1c9f4baa，501 个原基线守卫及全部输入摘要匹配。主代理逐字确认 types.py 仅 dataclasses.field 导入与 password field(repr=False)，未含 schemaName/原生数据库草稿。

主代理全 app/tests Ruff、strict app mypy84 通过；连接 repr、Mongo 凭据与基础契约三个测试文件 17 passed、0 skip、6.92秒。驱动入口测试走真实 SQLAlchemy/PyMySQL 参数构造并拦截网络连接，不能称为真实数据库连接验证。密码读取和 asdict 仍保留原值，repr 不再自动显示密码；本修复不意味着任意显式序列化都已脱敏。

原冻结保持不变，仅主代理文档/日志规范末尾空行；AGENTS无功能边界或核心目录变化，保持不变。
