# S12 Oracle / SQL Server 独立适配器

冻结集成基线：accepted 62c19bb7096e397e53008ff2e235286d396e18a3；来自只读 Git archive。含 S13 backend cfaffd7、S13 frontend、Mongo、七关系库、S11、S10、模型参数、615ff1f password repr=False 和 637be1d 元数据诊断清理。原 0b7df28 副本及失败证据保留，未覆盖共享工作区或原 Java。

范围为六个 native 模块、registry/types/Workflow 三文件接线及 database_tools Oracle 最小桥接。types 仅新增可选 schemaName；Protocol、QueryResult、Mongo 推断字段不变。本副本不改 relational.py/mysql_family_metadata.py、公共 safety/diagnostics、graph/model/streaming/context_compress、S11 compare/tools、存储、部署或 S14。AGENTS.md 检查：既有数据源及适配器边界和核心目录不变，保持原样。新增业务模块均少于 300 行。

## 原语义与实现

Oracle `dbName` 保持 service name，不作为 SID 或 schema。python-oracledb 使用默认 Thin 模式；已进入 Thick 模式时显式拒绝。结构化 URL 与驱动关键字参数保留特殊字符口令；连接成功后、SQLAlchemy 初始化查询前设置 call_timeout。元数据先读取服务端 SESSION_USER，再开启只读事务，按当前用户反射。每次 metadata scope 独立，不修改共享 adapter 实例。恢复 inspector 正规化的实际标识符，保持 unquoted UPPER、quoted lower/mixed 的区别；返回可选 `schemaName` 供工作流使用，databaseName 仍为服务名。

SQL Server 保持 `dbo` 元数据范围、pymssql/FreeTDS、UTF-8、datetime2、要求加密，与原 JDBC encrypt/trustServerCertificate 语义对应。结构化 URL 不拼接密码或 databaseName。驱动 timeout/login_timeout 有进程级效果，适配器拥有的连接使用一个模块锁覆盖完整会话；排队超时发生在目标 SQL 派发之前，排队取消也不建立连接。每个进程独立串行，不允许绕过本适配器在同一进程并发修改 DB-Lib timeout。

普通模式沿用 accepted SQL AST 的允许写入和 DROP/TRUNCATE/ALTER DROP 等禁止项。两族补充原生 sequence advancement、FOR UPDATE/UPDLOCK/XLOCK 的只读判定，试用和比较拒绝这些副作用。SQL Server 没有物理 READ ONLY transaction，pymssql read_only 仅路由意图；Oracle 另设置 SET TRANSACTION READ ONLY。SHOW/DESC 客户端命令及当前安全解析未支持的 EXPLAIN 显式拒绝。原两族 JDBC executeStatement 并无 SHOW/DESC 客户端扩展；本次不把其他方言命令送给新驱动。普通允许写 SQL 的实际执行和附件导入保留。

Oracle 真实驱动证实 seq.NEXTVAL 和 seq."NEXTVAL" 都推进序列，seq."nextval" 则报 ORA-00904 且不推进。FROM DUAL seq 的同名 alias 不能证明普通字段，真实执行仍推进；拥有真实 NEXTVAL 列的表 alias seq 返回字段值且不推进。native_reads 按 Oracle 引号大小写与当前 SELECT/外层相关作用域解析，支持派生表/CTE 的明确字段和星号投影，不用无关嵌套 alias 授权。

需要物理字段证据时，OracleReadCatalog 用同一已归属、ready 的服务配置查询 CURRENT_SCHEMA，再以 owner/table_name/column_name 绑定参数查询 ALL_TAB_COLUMNS。每次检查连接独占、查询有 call_timeout、同一字段缓存；缺字段或目录失败拒绝只读，不猜测。服务层 comparison 桥接仅 Oracle 使用 is_read_only_for_config；其他适配器原判定不变。direct adapter trial 执行同一规则。普通模式继续允许序列推进，并按真实派发状态报告失败后的未知副作用。真实扩展测试捕获 20 次字段目录查询及绑定参数，重复字段在单次检查只查一次。

## 结果与写入证据

Decimal 保留驱动给出的精度/scale 字符串（MONEY 实际 1.2500），日期输出 ISO，Unicode 原样、二进制 Base64，Oracle LOB 在结果关闭前读取；不把未知类型静默转字符串。fetchmany(max_rows+1) 保持默认100上限与 truncated。

Oracle execute 保留原生列键，metadata 仍使用 inspector 的反射规则。SQLAlchemy 2.1.1 的 RowMapping 在 driver_column_names=True 下仍可能保留正规化别名而混淆 ID/id 的值；仅本次独占 Engine 的 execute 路径关闭 requires_name_normalize，不改全局方言、元数据连接或其他数据库。三类 quoted/unquoted 查询和附件证据必须真实验证。

工作流按服务 schema 选择 oracle/tsql，Oracle 未引号名上折、引号名保留；SQL Server 默认 namespace=dbo。仅文件源表头按实际已写列映射，真实返回行键不改、不合并大小写列。National N'文本' 只按纯字符串 literal 取证，不允许计算函数伪装来源数据。

Oracle 使用公开 Connection.cancel；只有 ORA-01013 才标记服务端已确认中断。DPY-4024/DPI-1067/DPI-1080 只证明驱动超时/连接状态，不能冒充服务端确认。call_timeout 是单次 round trip，现有 watchdog 补整个执行阶段截止。SQL Server 无公开安全 in-flight cancel，取消请求失败要等驱动返回，明确 cancel_request_sent=False/server_termination_confirmed=False；不能把 cancel_error 当成已取消。派发后的写/序列推进中断、连接失败或 commit 未确认均报告结果未知，不自动重放。

## 真实环境与证据

- Oracle 23.26.3.0.0 / python-oracledb Thin 3.4.2：service FREEPDB1、实际 SESSION_USER SQLCHAT_FIXTURE，当前用户元数据、UPPER/quoted lower/quoted mixed 表字段、PK/索引/注释、NUMBER 精度、LOB、100 上限、普通写和序列、试用禁项、真实超时及取消。
- SQL Server 16.0.4295.3 / pymssql 2.4.2：Unicode、DECIMAL(38,12)、MONEY 原生 scale、二进制/日期、dbo 元数据/注释/PK/索引、100 上限、普通写/试用禁项、行锁 timeout/read cancel/write unknown。SQLAlchemy 2.1.1、SQLGlot 29.0.1，使用 accepted 锁定环境。
- 两族 API 创建→worker 验证→owned 控制读取、跨用户拒绝；真实存储文件→本地 HTTP 模型协议模拟→LangGraph→真实目标库→查询验证。Oracle 三种大小写 CSV、SQL Server N'Unicode' CSV 都完成。HTTP 模拟证明分支与请求协议，未作为真实模型效果证据。
- 测试系统库用临时 SQLite，目标 SQL 使用真实数据库；每轮 SQL Server 创建随机隔离 database，Oracle仅当前用户随机表/序列/函数，finally 精确回收本轮对象。未启停容器。

最新基线单一联合 gate：184 passed / 2 failed / 0 skipped / 171.63s（final-native-s13.log）。两失败均旧 native API 测试队列替身未接受 S13 的 locale headers；仅修 owned 替身并断言 zh-TW header。此 gate 中 native 实际 SQL、文件工作流、取消及 PG/MySQL/Mongo 原关键 workflow、comparison/model 参数已通过。

随后主代理实际复现 UNION/UNION ALL 上 WITH-CTE 普通 NEXTVAL 字段误拒绝。仅修 native_reads 的祖先作用域查找，让 SetOperation 上的 WITH 可见；参数化及真实 direct trial/comparison 验证 UNION ALL/UNION/INTERSECT/MINUS 四种集合操作，不读取无关目录、不推进序列。包含同名序列的 CTE 继续拒绝。受影响集合与 API 两项定向复验：73 passed / 0 skipped / 16.36s（final-native-s13-revision.log）；没有重复联合 gate 已通过的完整集合。Ruff app/tests 全通过；strict mypy app 95 source files 通过，见 ruff.log/mypy.log。

本阶段对应 F-04、T-06/T-11/T-12/T-13/T-14/T-15/T-24/T-37/T-38。

已有证据逐轮保留，不能把失败日志当通过：

| 日志 | 结果与意义 |
|---|---|
| native-current-real.log | 旧 Mongo 集成副本 89 passed / 0 skipped / 76.81s，包含两族实际执行、文件、取消 |
| final-bridge.log | 0b7df28 首轮 103 passed / 2 failed / 213.86s；两次新 DDL 后只读读取 ORA-01466 |
| oracle-boundary-and-quoted-revision.log | 失败两项及 quoted 判定的修订集合 50 passed / 11.66s |
| oracle-catalog-expanded.log | 目录、CTE/子查询/alias 及真实序列扩展 83 passed / 9.55s；捕获 20 次实际目录查询 |
| oracle-sequence-probe.json | 随机序列推进和普通字段对照的直接 driver 观察 |

Oracle 首轮还暴露了 ID/id 主键识别碰撞、NUMBER 类型字符串丢精度及取消确认断言错误，历史失败分别保留于 oracle-real.log、oracle-real-revision.log、oracle-cancel-probe.log、oracle-types-and-workflow.log。修复为恢复反射实际名称后匹配 PK/索引、按方言编译类型、按真实 ORA-01013 认定取消确认；没有更改业务值来迎合断言。API 首轮 queued args 测试预期类型错误和 MONEY scale 测试预期错误仅修断言，原失败日志保留。

## 原生边界与后续项

Oracle 新建/变更表后强制 READ ONLY 事务可能报 ORA-01466；原失败可复现，产品未重试、未去掉只读事务。真实稳定 fixture 查询服务端 USER_OBJECTS.last_ddl_time 与 SYSDATE，确认本轮对象至少 5 秒 DDL 年龄后读取；这只避免测试落入已知边界，不声称消除 Oracle 原生限制。受影响为 trial/comparison 强制只读查询及只读元数据行数读取；后者保留 incomplete/rowCount=None。普通模式实际 SQL 执行及 workflow post-write SELECT 不强制只读，三类文件导入已实际完成。

Oracle 真实 write cancel 返回 DPY-4011：请求已发送、服务端确认 false、写入结果未知。独立只读 sleep 函数真实返回 ORA-01013：服务端确认 true、写入未知 false。SQL Server 缺少公开安全取消 API，取消失败等待驱动超时，明确报告未发送/未获服务端确认。账号权限仍控制任意用户函数等数据库原生能力；没有宣称 AST 可以替代只读账号。

Oracle 特殊 NEXTVAL 引用需要可见的物理字段目录证据；不解析 synonym 到其他对象，缺证据时明确拒绝试用/比较。本次不新增自定义 schema 配置。两族原生安全可修复错误白名单为后续独立 fix，本 feature 不改 sql_errors/tools，不宣称已完成原生错误反馈修复。外部 OSS/OCR 环境阻塞沿 S10 已接受报告；本次真实文件使用显式本地存储。

凭据只从 ignored runtime 文件或内部 docker inspect 读取，不输出或经 argv 传递。fixture repr 固定脱敏，run-checks.py 在输出/写日志前统一清理 secret 及 URI userinfo，已存在证据拒绝覆盖。accepted DbConnectionConfig repr=False 已继承；asdict 仍保留原值，仅限受控持久化。最早直接 pytest 的失败 fixture repr 曾暴露开发实例口令，已向主代理记录并由其安排轮换；保留日志均经清理，无口令写入源码或冻结清单。

## 复验命令与交接

使用已有锁定 venv Python，不安装依赖或启停实例。PowerShell：

```powershell
& 'C:/Users/22126/Desktop/web/text2sql/sqlchat/backend/.venv/Scripts/python.exe' '<snapshot>/docs/phase-12-native-adapters/run-final-gate.py'
```

runner 私下准备 PG/MySQL/Mongo fixture 环境以及 Oracle/SQL Server ignored runtime 路径，串行执行全部 native owned 测试和旧 PG/MySQL/Mongo workflow 标识符/更正、模型参数、comparison 读取；随后 Ruff app/tests、strict mypy app。实际 pytest 文件清单见 run-final-gate.py；定向修订命令同样调用 run-revision-gate.py。主代理在独立副本复验时设 NATIVE_EVIDENCE_SUFFIX 为本次唯一标记，例如 root-01；三个新日志均添加该后缀，已有证据绝不覆盖。冻结源副本不再运行写日志的脚本。

files.tsv/freeze.json 列出 owned payload SHA256，preserved.tsv 校验最新 accepted 所有未改文件；public-bridges.diff 供逐方法 review。BASE.txt、baseline-files.json、owned-paths.json 固定导出来源与范围，AGENTS、公共 relational/mysql_family_metadata/diagnostics/safety、S13 和 graph/model/streaming 均必须与 accepted 字节一致。交付后保持 freeze 不变，等待主代理独立验收。

## 官方依据

- [python-oracledb 3.4 Thin 功能矩阵](https://python-oracledb.readthedocs.io/en/v3.4.0/user_guide/appendix_a.html)：默认 Thin，无 Oracle Client，数据库12.1+；类型能力与版本仍需逐实例验证。
- [Oracle Connection API](https://python-oracledb.readthedocs.io/en/v3.4.2/api_manual/connection.html)：cancel、call_timeout 单次round-trip语义与 DPI 超时状态。
- [Oracle SET TRANSACTION](https://docs.oracle.com/en/database/oracle/oracle-database/26/sqlrf/SET-TRANSACTION.html)：只读事务必须在首个事务语句设置，DDL隐式提交，不能宣称取消会撤销DDL。
- [SQLAlchemy 2.1 Oracle](https://docs.sqlalchemy.org/en/21/dialects/oracle.html)：服务名 URL、NUMBER/LOB、名字正规化与 driver_column_names。
- [pymssql Connection API](https://pymssql.readthedocs.io/en/stable/ref/pymssql.html)：timeout/login_timeout全局效果、threadsafety、加密、datetime2、read_only意图；没有公开Connection.cancel。
- [SQLAlchemy SQL Server](https://docs.sqlalchemy.org/en/20/dialects/mssql.html)：pymssql/FreeTDS 方言。
- [SQL Server sequence](https://learn.microsoft.com/en-us/sql/relational-databases/sequence-numbers/sequence-numbers?view=sql-server-ver15)：NEXT VALUE FOR 分配序列值，不能作为纯只读取证。
- [Oracle ORA-01466](https://docs.oracle.com/en/error-help/db/ora-01466/)：表定义晚于只读事务快照时读取失败；本实现不自动重放用户 SQL。
