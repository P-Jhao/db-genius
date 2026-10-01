# S12 MySQL 协议族独立交接

范围为 F-04 / T-06、T-12–15、T-24、T-37–38 的 MariaDB、TiDB、Doris、StarRocks、OceanBase MySQL 模式。原 Java 五类继承 MySqlAdapter，类型名保持原小写标识。最终副本从 accepted HEAD `5b9c543757cb4e83031226762131f36b6fa6907b` 只读导出，已含主验收的 S10 `13d4595`；adapter 层来自先前 accepted `007a6ea` 的隔离自测副本。未修改共享工作树、index、S10 副本或原 Java，未执行 Git 提交、reset 或清理。

| 类型 | 默认端口 | 会话超时单位 | 元数据路径 | 验证状态 |
|---|---:|---|---|---|
| mariadb | 3306 | max_statement_time，秒 | MySQL 反射 | 模拟通过；专用真实实例自测通过，主复验待执行 |
| tidb | 4000 | max_execution_time，毫秒 | MySQL 反射 | 模拟通过；真实实例环境阻塞 |
| doris | 9030 | query_timeout，秒 | information_schema | 模拟通过；真实实例环境阻塞 |
| starrocks | 9030 | query_timeout，秒 | information_schema；索引明确不完整 | 模拟通过；真实实例环境阻塞 |
| oceanbase | 2881 | ob_query_timeout，微秒 | MySQL 反射 | 模拟通过；真实 MySQL 模式租户环境阻塞 |

五类显式使用 `mysql+pymysql` 和 MySQL SQLGlot 方言。连接口令使用结构化 URL；连接、读、写超时按基类设置。会话超时变量不受支持时显式报错，不能在未设限的状态下派发 SQL。默认结果上限为 100 行，截断、Decimal、NULL、中文和特殊标识符保持基类契约。普通写入提交，失败回滚；拒绝 DROP/TRUNCATE/ALTER DROP、多语句及试用写入。未把其他数据库族、试用业务、部署或模型参数改动带入此阶段。

基线的 `relational.py`、`mysql.py`、`types.py`、`safety.py`、`cancellation.py` 及 S09 Agent 工具、governance、repair 保持逐字不变。没有复制共享工作树中 Oracle schema 改动、混合 registry、DatabaseAdapter 抽象或删除 QueryResult 错误字段的草稿。此副本 registry 只在 accepted 版本上增加五类。

MariaDB 直接实例通过独立控制连接执行 KILL QUERY。其他四类未验证固定路由拓扑，禁止跨未固定代理使用连接 ID 发 KILL；在途取消返回 `cancel_request_sent=False`、`server_termination_confirmed=False` 和显式 cancel_error，已派发写入保持 `write_outcome_unknown=True`。驱动/服务端超时仍生效，但不能据此宣称后台语句已终止或写入已回滚。TiDB 6.4 起 max_execution_time 仅约束 SELECT；StarRocks 3.4 起 INSERT 相关操作使用 insert_timeout。此阶段没有可用实际引擎来验证这些写入超时与路由语义，边界详见 [参数与风险](PARAMETERS.md)。

OLAP 表列注释、完整类型、nullable、主键、可用索引和精确 COUNT(*) 分别读取。列查询失败或空列清单不会报告完整；索引读取失败或残缺字段标记 incomplete；COUNT(*) 失败保留表列并将 rowCount 置 null。StarRocks 官方声明 STATISTICS 为未实现占位视图，因此即使可读表列/行数，也明确标记索引 incomplete，不能把空视图当作无索引的证明。Doris 实际版本系统视图的可用性仍待真实实例核对。

测试命令和最终数值证据见 [操作说明](OPERATIONS.md)、[检查结果](checks.json)；之前 adapter 层的 121 pass / 4 skip 保存在 [旧层检查](adapter-checks-007a6ea.json)，旧层 [真实 MariaDB 自测](real-mariadb-self-check.json) 为 MariaDB 11.4.13 专用 loopback 13307 的四例通过。真实四例覆盖读写独立检查、失败原子回滚、100/3 行上限、元数据注释/索引/类型、禁用语句及试用拒绝、超时服务器退出、在途 KILL 的服务器确认。仅创建随机测试表并精确清理，前后表集合相同，无容器生命周期修改；凭据只在内部子进程环境使用。换基线未改 MariaDB 执行路径，因此没有重复旧真实测试；最终快照的真实主复验待执行。

S10 WorkflowSchema 已在最终 accepted 基线上完成最小集成：新增五类到 MySQL dialect 的映射，并按映射结果沿用 MySQL 列名大小写规则。新增五类 schema.register 与 quoted/numeric workflow 回归：数据库限定名称、内嵌反引号、Decimal 与数值字符串、文本前导零、NULL、错误金额和错误文本标识均有断言。最终两组互不重叠测试为 **122 passed / 16 skipped** 与 **53 passed**，合计 **175 passed / 16 skipped**；16 skip 为未配置真实 Maria 四例与既有 S10 MySQL/PostgreSQL 十二例，不计通过。Ruff/mypy 九个源/测试文件通过。其余 S10 公共文件逐字不变，未复制共享草稿。此证据属于确定性协议/工作流验证，不代表四个缺实例引擎的真实文件导入通过。其余四类真实环境阻塞与 StarRocks 索引不完整保留在最终验收报告。AGENTS.md 已检查：本次未改变核心目录或业务能力边界，保持不变。
