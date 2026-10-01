# 参数、证据与风险

查询上限默认 100 行，timeout_seconds 默认 30 秒，连接超时为 min(timeout_seconds, 10)，读写驱动超时均为 timeout_seconds。协议测试验证五类会话参数为：MariaDB 30、TiDB 30000、Doris/StarRocks 30、OceanBase 30000000。设置使用固定适配器变量名及正整数，不由 SQL 输入拼接变量名。

- MariaDB max_statement_time 使用秒，覆盖除存储过程外的查询，计时检查并非立即中断；不可作为唯一资源限额。[官方超时说明](https://mariadb.com/docs/server/ha-and-performance/optimization-and-tuning/query-optimizations/aborting-statements)
- TiDB max_execution_time 使用毫秒，从 6.4 起仅约束 SELECT。写入网络/驱动超时不能证明服务端写入停止。[官方系统变量](https://docs.pingcap.com/tidb/stable/system-variables/#max_execution_time)
- Doris query_timeout 为查询时限，系统视图、DML/事务能力和各版本超时范围必须独立验证；MariaDB 的成功不能证明 Doris 通过。[官方变量说明](https://apache.googlesource.com/doris/+/2a2e4854562030c0061e70013be5f5ac673a3048/docs/en/docs/advanced/variables.md)
- StarRocks query_timeout 使用秒，从 3.4 起不约束 INSERT 相关操作。insert_timeout 的版本范围和实际写入超时需真实验证；此阶段维持显式结果未知与不安全 KILL 拒绝，未宣称服务器写入时限通过。[官方系统变量](https://docs.starrocks.io/docs/sql-reference/System_variable/#query_timeout)
- OceanBase ob_query_timeout 使用微秒，本适配器仅用于 MySQL 模式租户。[官方查询超时](https://en.oceanbase.com/docs/common-oceanbase-database-10000000000829719)

StarRocks 的 information_schema.STATISTICS 是未实现占位视图。当前代码不把空返回当作完整索引证据，按契约返回 incomplete/errorMessage，保留可读表列与行数。尚无实际版本支持的完整索引提取证明。COLUMNS 提供 COLUMN_TYPE、COLUMN_KEY、nullable 和注释，仍需要实际实例核验。[官方系统视图列表](https://docs.starrocks.io/docs/sql-reference/information_schema/)、[索引视图](https://docs.starrocks.io/docs/sql-reference/information_schema/statistics/)、[列视图](https://docs.starrocks.io/docs/sql-reference/information_schema/columns/)

Doris 当前路径尝试 STATISTICS，读取失败明确不完整。官方 SHOW INDEX 只覆盖内部表部分索引种类、外部 catalog 还有额外限制；未在缺少真实实例时引入另一个可能不完整的假成功路径。[官方 SHOW INDEX](https://doris.apache.org/docs/4.x/sql-manual/sql-statements/table-and-view/index/SHOW-INDEX/)

四类代理引擎没有固定 FE/节点/租户连接路由的可用实例，不能安全由另一连接盲发 KILL QUERY。回归分别验证读/写已派发取消：不发送 KILL、不提交、回滚尝试、显式取消失败，读结果未知为 false，写结果未知为 true。S08 基类的提交失败、连接丢失、取消竞态规则以及 S09 禁止未知写入自动重试保持不变。

官方文档核验日期：2026-10-01。文档说明不替代真实引擎测试。当前四类真实状态均为“环境阻塞”；StarRocks 索引能力限制明确列为功能边界，不归因为环境故障。S10 workflow 的五类 dialect/列名规则已经在 accepted S10 后完成集成，其协议回归不替代真实引擎导入验证。
