# 部分元数据修复主代理验收

状态：独立 fix 验收通过；提交号由后续实施状态补录。

从已接受 a8e6a3a 导出独立副本，仅叠加子代理冻结的5个变更文件；freeze.json SHA256 9cbd035e5f82a86a9cdc9c889d877ee3deeeebfe4ca3f3ca34189e069e6c0fdc，5个变更与18个保留文件均逐项核对原始SHA，保留文件另与旧accepted基线规范换行后比对。共享业务草稿未覆盖。业务 diff 仅worker不再拒绝partial，以及手动生成先连接测试后保留partial；渲染、归属、版本条件更新和加密未改。

主代理独立执行全app/tests Ruff、strict mypy app（74模块）及3个变更模块mypy通过；实际专用PostgreSQL/MySQL注入凭据，pytest6文件 **63 passed、3 skipped、21.08秒**。3skip为未启用的live Celery2与故障broker1，不能计通过。main-checks.txt保存命令及脱敏输出。

新增partial状态机使用真实SQLite系统持久化与明确适配器替身，覆盖部分/完整连接0→1、文档明确错误提示、手动刷新、连接false/异常、提取/渲染异常→2、版本更新/删除后防回写、跨用户schema及SQL拒绝；原S05/S04专项另验证真实PG系统库与两类目标连接、完整元数据/真实执行。不能把partial替身测试描述为真实StarRocks或真实Worker验证。

原Java连接成功保持connected、部分结构错误写入文档，Python按此对齐；仅元数据字段缺失不阻止正常聊天，但结构对比仍须保留不完整警告。S12 family与S11 compare独立验收，尚不以本fix证明其完整功能。检查AGENTS未改变边界或核心目录，保持原样。冻结原件不修改；暂存docs末尾规范为单个换行，清单SHA仍表示原件历史值。
