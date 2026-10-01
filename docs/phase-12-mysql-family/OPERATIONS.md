# 复验操作

从隔离副本 backend 运行，使用现有共享虚拟环境解释器，无需安装或修改依赖。先核对导入路径属于此副本：

```powershell
$s12Python = 'C:\Users\22126\Desktop\web\text2sql\sqlchat\backend\.venv\Scripts\python.exe'
& $s12Python -c "import app.adapters.registry as r; print(r.__file__)"
& $s12Python -m ruff check app/adapters/mysql_family.py app/adapters/mysql_family_metadata.py app/adapters/registry.py app/agent/workflow_schema.py tests/test_mysql_family.py tests/test_mysql_family_outcomes.py tests/test_mysql_family_metadata_errors.py tests/test_mysql_family_workflow.py tests/test_mariadb_integration.py
& $s12Python -m mypy app/adapters/mysql_family.py app/adapters/mysql_family_metadata.py app/adapters/registry.py app/agent/workflow_schema.py tests/test_mysql_family.py tests/test_mysql_family_outcomes.py tests/test_mysql_family_metadata_errors.py tests/test_mysql_family_workflow.py tests/test_mariadb_integration.py
& $s12Python -m pytest tests/test_adapters_safety.py tests/test_adapters_contract.py tests/test_adapters_cancellation.py tests/test_mysql_family.py tests/test_mysql_family_outcomes.py tests/test_mysql_family_metadata_errors.py tests/test_mysql_family_workflow.py tests/test_mariadb_integration.py tests/test_runtime_governance.py tests/test_sql_repair.py tests/test_workflow_evidence.py tests/test_workflow_graph.py tests/test_workflow_integration.py tests/test_workflow_identifiers.py -q
```

缺少任何 SQLCHAT_TEST_MARIA_HOST/PORT/DB/USER/PASSWORD 时，真实四例 skip。配置完整后显式检查 host 为 localhost/127.0.0.1 且 port 为专用 13307，否则报错。主复验内部读取 `docker inspect sqlchat-s12-mariadb` 的 Env/端口，核对正在运行与 loopback 13307 映射，禁止打印 inspect 原文、凭据或带密码 URL。数据库名与 root 口令仅放入 pytest 子进程的临时环境，运行：

```text
python -m pytest tests/test_mariadb_integration.py -q
```

调用 pytest 时捕获 stdout/stderr，输出前替换内部读取的口令及其 repr/URL 编码形式；不要把口令作为 CLI 参数传入，不保存明文测试输出。每次写入 fixture 只创建随机 ``s12 order`items <uuid>`` 表，finally 精确 DROP 此表并确认信息模式中消失。前后读取 SHOW TABLES 集合一致才确认精确清理。慢查询只使用随机 s12_timeout_/s12_cancel_ 标记，观察 PROCESSLIST 时排除观察连接自身；不删除其他表，不停止、重启或删除容器/卷。

主复验后只按 freeze.json 的 changedFiles 清单整合业务/测试/文档，不复制此副本全部目录。preservedFiles 为逐字未变的 accepted S08/S09 依赖，不属于本阶段变更。registry 必须保留 accepted 既有键并仅新增本族五类，不复制共享混合草稿。新文件最高 300 行规则已检查。

最终 freeze 基于 accepted `5b9c543`，已整合 adapter 层和 S10 WorkflowSchema 五类 dialect/列名规则；真实主复验待执行。新副本为 `s12-mysql-family-e75ad3eb362e410381522fc16e5a8a21`，旧 `c795fb` 仅保留检查证据来源，不能整份复制旧公共文件。四类真实引擎未配置时保持环境阻塞，不能通过 MariaDB 或 MySQL 代验；不进入 MongoDB 阶段。
