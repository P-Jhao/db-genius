# Oracle / SQL Server 主代理验收

主复验基线：04dad4865efc3829ff02b1c3e107a52c39d6cf29；源候选基线62c19bb。候选 freeze SHA256 d76aab499ffa0c539a4e130a338e8bc1575eaf8825dfd87dcf1b7484c515885d，53项原字节与大小均核对。主副本仅叠加这53项，其他110个已接受app文件按换行归一化一致；所有owned Python代码均不超过300行。没有覆盖共享草稿、原Java或更改历史。

主代理独立运行：`NATIVE_EVIDENCE_SUFFIX=root-01 python docs/phase-12-native-adapters/run-final-gate.py`。联合测试 **190 passed / 0 skipped，193.71秒**；全app/tests Ruff通过；普通mypy app通过（95模块）。另显式 `mypy --strict --follow-imports=silent` 覆盖全部12个owned app/桥接模块，通过。

额外全app `--strict` 未通过：既有storage/ocr.py:36 no-any-return、agent/graph.py:64 no-untyped-def及:164 no-any-return，共3处。它们不在本次修改范围；冻结README的“strict mypy app95”用词错误，实际runner是普通mypy。主记录以实际命令和日志为准，此检查失败不计通过，后续独立修复。

目标为真实Oracle23.26.3.0.0、SQLServer16.0.4295.3，以及PG/MySQL/Mongo兼容回归；系统store部分SQLite，模型为本地HTTP协议模拟。Oracle当前用户元数据、精度/LOB/大小写、真实Unicode文件导入和SQLServer dbo/Unicode/DECIMAL/MONEY/写入均通过。API创建到Worker函数直接验证及受控服务读取通过，**不代表真实Rabbit消费或真实模型效果**。

六个公共桥已逐差异审查：注册两族；metadata仅增加可选schemaName；Workflow添加oracle/tsql及文件表头映射；National纯文本支持；Oracle比较使用已归属ready配置的绑定参数目录检查。公共relational/safety/diagnostics、S13、模型/图/压缩与其他数据库保持已接受版本。Oracle NEXTVAL真实字段与序列、DUAL别名、CTE/相关作用域分别取证；主代理先复现合法CTE UNION误拒绝，再独立真实复验修复后四种集合运算及实际序列不推进断言，未放宽公共守卫。

取消实际证据：Oracle只读函数返回ORA-01013确认服务端中断；写取消DPY-4011仅表示请求已发送，服务端确认false、结果未知。SQLServer无公开安全取消，等待driver deadline，未发出/未确认明确。派发后序列副作用及commit未知均不自动重放。Oracle新DDL后的ORA-01466限制保留，fixture等本轮对象服务端DDL年龄不少于5秒，不算产品修复。Synonym缺字段目录证据时拒绝只读，未新增自定义schema。

F-04/T-06/11/12/13/14/15/24/37/38在上述环境边界内接受。十类适配代码现已齐备；TiDB/Doris/StarRocks/OceanBase依用户决定暂以协议验收，真实专用实例仍未验证。原生已知错误反馈修复另为独立fix，不混入本feat；OSS/OCR仍按用户确认模拟验收。最终部署和同Flash效果对照未完成，不宣称完整迁移通过。

AGENTS已检查；既有核心功能/目录不变，无需更新。日志与待提交内容须执行实际运行口令、URL编码和模型Key扫描；运行配置仅保留忽略路径。
