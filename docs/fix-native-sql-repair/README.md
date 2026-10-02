# 独立 fix：Oracle / SQL Server 安全 SELECT 错误反馈

基线为已接受 native feature a0f17fe；只读 archive 新导出，未覆盖原 8c1c8 freeze、共享工作区或原 Java。前置候选来自 accepted 04dad48 加 immutable native payload，状态当时明确为 feature 待验收；实际实例验证全部在主代理接受 a0f17fe 并释放窗口后执行。

唯一业务改动 app/agent/sql_errors.py。对应独立 policy、受控 HTTP graph、真实目标数据库三份测试及本目录证据。不改 tools、graph、模型参数、native adapter、database_tools、S14、公共依赖或提示词。AGENTS.md 检查：既有能力与目录未变，不修改。此 fix 不是旧 native feature 的重新交付。

## 行为与边界

原生错误先满足已有 statement 与本次 SQL 一致、连接未 invalidated、没有 rollback failure note。只在真正 Select / SetOperation、既有只读 AST、单语句、无序列推进/锁定的分支提供模型修订；DML/DDL 错误不因代码名称就自动重放。普通成功写能力保持原样。

Oracle 要求 python-oracledb DatabaseError、结构化 code 与 full_code 精确一致、非 bool 的正数 offset，白名单 904/907/923/933/936/942/3047。正offset本身不能证明顶层parse失败：真实函数内部错误也可能offset7。offset=0 或 ORA-06512/ORA-04088 函数/trigger 栈拒绝；不能从字符串里找 ORA 编号来允许修复。SQL Server 要求 pymssql ProgrammingError 与整数码102/207/208；官方 pymssql 2.4.2 源码不把156映射为同类，未以“看起来是语法错误”放宽它或未知过程调用码。

Oracle errorCode 从结构化原生错误保留为整数；error 仍按原1000字符边界，sqlState 只在实际存在时返回。既有 PostgreSQL SQLSTATE、MySQL 四码及 SQLite 规则保持；针对旧 PG/MySQL driver 错误对象的失败 INSERT 白名单回归确认原行为。

网络、commit 失联、cancel/timeout、DatabaseWriteOutcomeUnknown、未知码、权限/约束错误及 failed rollback 都走原中止/异常路径，没有后续模型调用。原生 SELECT 不是普遍副作用证明：Oracle 函数可以在内部推进序列后再抛相同缺表代码，所以必须验证顶层解析位置并拒绝调用栈，不能仅按942反馈。

本次没有开放 native 失败 DML 修复；driver 码无法证明 trigger 内同码及非事务序列的真实结果。涉及这种范围的后续扩展须另有无副作用/rollback取证，而非改动公共执行语义。没有通过设置更大行数/无限 timeout/自动 retry 消除错误。

## 验证与失败记录

受控模型只使用本地 HTTP/SSE Provider，目标实例用主代理已准备的 Oracle 23.26.3.0.0 Thin 3.4.2、SQL Server16.0.4295.3 / pymssql2.4.2；没有外部模型调用。测试数据库 fixture 都沿 accepted native，随机对象仅本轮 finally 精确回收，不启停/拉取实例。PG/MySQL legacy policy 用真实 SDK 异常对象而非连接其目标实例；旧 SQLite repair 测试仍是临时本地存储，不称真实 native。

| 证据 | 实际结果 |
|---|---|
| mock.log | 初始候选69 passed /51.34s；原生 driver 对象 policy、受控HTTP修订/不重放、原SQLite repair |
| ruff.log | 初轮失败：owned测试一个 implicit string concat格式问题，仅加括号修正 |
| policy-real.log | fresh a0f17fe 57 policy passed /9 real failed /30.48s：测试混用两套用户/DB ID，未到产品SQL派发；fixture本轮对象均清理 |
| real-revision.log | 对齐 native731/7311 IDs 后8 passed /1 failed /49.54s；Oracle LIMIT 实际为3047而非测试假设933，原未知码未误反馈 |
| real-final-revision.log | 62 passed /3 failed /51.16s；59 policy和3047/936/923实际HTTP修订通过，三个额外测试预期错误见下文 |
| real-final-local.log | 2 passed /1 failed /17.88s：真实函数副作用拒绝、合法semicolon通过；聚合函数错误预期仍错误 |
| real-last-local.log | 最后聚合函数904实际修订1 passed /10.81s |
| ruff-final.log | 失败为新policy SDK imports顺序，修正测试imports；业务未改 |
| ruff-verified.log / mypy-app-verified.log / mypy-owned-strict-verified.log | Ruff全app/tests通过；普通mypy app95模块通过；显式--strict owned sql_errors 1文件通过 |

904 实际offset7、942 offset17，类型 oracledb.exceptions.DatabaseError；207/208/102 类型 pymssql.exceptions.ProgrammingError。真实错误连接出现 rollback event、没有回滚失败 note，受控 HTTP 的下一次请求带 success=false / errorCode，模型换为正确 SELECT 后实际得到 Ada；最终目标行仍只一条。Oracle LIMIT实际3047/offset43、尾逗号936/offset13、字符串alias923/offset15也真实完成修订。907/933只完成官方定义和driver协议模拟，当前23.26.3样例返回其它码，不宣称已真实覆盖旧版本这两个码。

额外失败均如实保留：GROUP_CONCAT样例实际904（函数未找到），不是预设907或3047；句末semicolon本实例实际合法成功，已改为正常成功对照，不给伪失败；函数内部先推进序列再缺表实际942/offset7并含ORA-06512栈，原offset0测试假设错误。调用栈拒绝条件已使该真实例只有一次模型请求、序列推进一次，无错误反馈重放。14个当前真实用例均最终通过，覆盖记录跨上述局部复验，不称一次全套14pass。

真实普通 INSERT 成功提交后注入结果丢失，两族目标数据库都实际只有一次副作用、仅一次模型请求。Oracle seq."NEXTVAL" 实际推进后在结果读取注入942，native wrapper 转为未知写中止，序列 last_number=2，模型没有再调用。故障注入证明应用处理真实结果丢失，不冒称真实网络断线。另真实函数内部先推进序列再动态查询缺表的负例用于区分调用失败和顶层 parse 错误。

## 检查范围与复验

Ruff 范围 app/tests；全 app 使用 `mypy app`（普通配置），owned 使用 `mypy --strict app/agent/sql_errors.py`。旧 native README 曾把 `mypy app`误标 strict；主代理已纠正验收记录，本报告不沿用。全 app 显式 --strict 的旧3处 graph/OCR 边界不属于本 fix，保留根代理失败记录，后续独立类型修复，不在此改动。

命令见 run-mock-checks.py 与 run-native-checks.py。日志拒绝覆盖；主代理在新的隔离副本设置唯一REPAIR_EVIDENCE_SUFFIX，再调用 run-native-checks.py --all-real，一次执行三份owned tests、Ruff、普通app mypy和owned显式strict。--static-only仅运行三个静态检查。runner内部加载ignored runtime路径，结果先用accepted diagnostics清理后输出/写日志。不能把两个mypy命令范围混称。

files.tsv/freeze.json 给出本 fix payload SHA256，preserved.tsv 对 accepted 所有未修改文件做字节守卫，repair.diff 只有 sql_errors 最小改动。旧候选与失败日志保留。主集成如果已有 S14 的 database_tools观测wrapper，只移本 fix owned文件；不覆盖任何 whole native 或公共模块。

## Primary 依据

- [python-oracledb Error 对象](https://python-oracledb.readthedocs.io/en/v3.4.2/api_manual/module.html#exceptions)：异常args的结构化code/full_code/offset。
- [pymssql2.4.2 源码](https://github.com/pymssql/pymssql/blob/v2.4.2/src/pymssql/_pymssql.pyx)：ProgrammingError映射102/207/208等，commit/rollback分别处理。
- [Oracle904](https://docs.oracle.com/en/error-help/db/ora-00904/)、[942](https://docs.oracle.com/en/error-help/db/ora-00942/)、[907](https://docs.oracle.com/en/error-help/db/ora-00907/)、[923](https://docs.oracle.com/en/error-help/db/ora-00923/)、[936](https://docs.oracle.com/en/error-help/db/ora-00936/)：字段、对象或SQL语法问题。
- [Oracle933](https://docs.oracle.com/en/error-help/db/ora-00933/)、[3047](https://docs.oracle.com/en/error-help/db/ora-03047/)：顶层错误语法及函数内部动态SQL都可能引发相同码，需要结构化位置/调用栈判定。
- [SQL Server207](https://learn.microsoft.com/en-us/sql/relational-databases/errors-events/mssqlserver-207-database-engine-error?view=sql-server-ver16)、[208](https://learn.microsoft.com/en-us/sql/relational-databases/errors-events/mssqlserver-208-database-engine-error?view=sql-server-ver16)：列/对象解析错误。此类说明不能单独证明DML副作用已撤销。
