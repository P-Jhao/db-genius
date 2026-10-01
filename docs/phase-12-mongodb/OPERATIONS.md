# 复验操作

在本隔离副本运行，使用共享 backend/.venv 已安装的 Python；不安装新工具或改部署配置。以下脚本从 Docker inspect **内部**读取专用容器凭据，只生成临时子进程环境和脱敏输出，不输出 inspect、环境、连接 URL 或密码。

```powershell
$python = 'C:/Users/22126/Desktop/web/text2sql/sqlchat/backend/.venv/Scripts/python.exe'
& $python docs/phase-12-mongodb/verify_real_mongo.py
& $python docs/phase-12-mongodb/verify_relational_bridge.py
```

专用 Mongo 为 `sqlchat-s12-mongo` loopback:17017；测试逐次创建 `s12_mongo_<uuid>` 数据库和合成 items 集合/索引，只精确清理该随机库并验证数据库集合前后相等。公开 adapter 没有写入接口。连接未就绪则失败，不 restart/delete 容器。不要对已有 frozen 证据执行重写；复验应先在主代理 fresh 导出副本中整合唯一清单。

关系桥接使用专用 PG15432、MySQL13306、Maria13307，只清理测试所建随机表/角色；workflow 的系统 store 是临时 SQLite/service fixture。它不配置 SQLCHAT_TEST_DATABASE_URL，不重建 PG app。共享 public 目标元数据抽取与随机 DDL 仍需和其他代理串行，避免 catalog 读取竞态。实际 engine 与 HTTP 模拟模型分别标记，不能归为真实模型效果。

```powershell
Set-Location backend
& $python -m ruff check app tests ../docs/phase-12-mongodb/verify_real_mongo.py ../docs/phase-12-mongodb/verify_relational_bridge.py
& $python -m mypy app
& $python -m pytest tests/test_mongodb_diagnostics.py tests/test_mongodb_metadata.py tests/test_mongodb_adapter.py -q
```

`final-freeze.json` 与外部交付的清单 SHA 可用于逐文件复验。冻结后不再修改；具体审查缺陷使用独立 revision。无需重跑无修改疑点的 20 项真实 Mongo 或之前 191 项确定性集合；最终最小新 HEAD 桥接和诊断修复分别有证据。
