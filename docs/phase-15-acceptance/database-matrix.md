# Ten-Database Acceptance Matrix

状态截点：2026-10-02。实现源码见[正式 SQLChat 仓库根](../../)；本页的源码及 `S:docs/...` 阶段文档引用均相对于该仓库根。接受的阶段范围基线见[phase-15-acceptance 文档目录](../phase-15-acceptance/)。详细后端审计属于本地可恢复 artifact，位于 `../../.git/acceptance/s15-backend-final-audit-aed4e0402ef04aae97ca8e5396b8a7ac/`；不是已提交文档。状态词沿用工作区外部的[验收规范](../../../spec/07-测试与验收规范.md)。`真实目标实例`列只记实际连接目标数据库得到的证据；协议/模拟通过不折算成真实环境通过。

| dbType | 实现路径（相对 S） | 实现/协议 | 真实目标实例 | 已证明范围与限制 | 证据路径 |
|---|---|---|---|---|---|
| mysql | `backend/app/adapters/mysql.py`; `backend/app/adapters/registry.py` | 真实环境通过 | 真实环境通过：MySQL 8.0.46 | 查询、普通写、元数据、100 行、取消/未知写与本地导入；不自动重放未确认写。 | `S:docs/phase-04-first-databases/`; `S:docs/phase-08-chat-abort/README.md`; `S:docs/phase-10-file-workflow/main-review.md` |
| postgresql | `backend/app/adapters/postgresql.py`; `backend/app/adapters/registry.py` | 真实环境通过 | 真实环境通过：PostgreSQL 16.14 | 查询游标、读写/取消、schema 隔离、后台任务与比较。 | `S:docs/phase-04-first-databases/`; `S:docs/phase-05-pg-read-cursors/`; `S:docs/phase-11-comparison/main-review.md` |
| mongodb | `backend/app/adapters/mongodb.py`; `backend/app/adapters/mongodb_metadata.py` | 真实环境通过 | 真实环境通过：MongoDB 8.0.32（无认证） | find/count/distinct/aggregate、采样/截断与真实结构比较；认证服务为协议证据，结构按观察推断。 | `S:docs/phase-12-mongodb/main-review.md` |
| mariadb | `backend/app/adapters/mysql_family.py`; `backend/app/adapters/mysql_family_metadata.py` | 真实环境通过 | 真实环境通过：MariaDB 11.4.13 | 默认端口/超时、KILL QUERY、写/回滚、元数据和截断；仅证实 MariaDB 目标实例。 | `S:docs/phase-12-mysql-family/README.md`; `S:docs/phase-15-acceptance/数据库验收矩阵.md` |
| tidb | `backend/app/adapters/mysql_family.py`; `backend/app/adapters/mysql_family_metadata.py` | 模拟通过 | 环境阻塞：暂无真实实例 | 默认 4000 与毫秒超时参数实现；实际写超时/代理路由取消未证实。 | `S:docs/phase-12-mysql-family/README.md`; `S:docs/phase-15-acceptance/数据库验收矩阵.md` |
| doris | `backend/app/adapters/mysql_family.py`; `backend/app/adapters/mysql_family_metadata.py` | 模拟通过 | 环境阻塞：暂无真实实例 | 默认 9030、秒级 query timeout 与元数据路径有协议覆盖；实际视图和写行为未证实。 | `S:docs/phase-12-mysql-family/README.md`; `S:docs/phase-15-acceptance/数据库验收矩阵.md` |
| starrocks | `backend/app/adapters/mysql_family.py`; `backend/app/adapters/mysql_family_metadata.py` | 模拟通过 | 环境阻塞：暂无真实实例 | 默认 9030 与 timeout 协议覆盖；索引视图明确不完整，实际 INSERT 超时未证实。 | `S:docs/phase-12-mysql-family/README.md`; `S:docs/phase-15-acceptance/数据库验收矩阵.md` |
| oceanbase | `backend/app/adapters/mysql_family.py`; `backend/app/adapters/mysql_family_metadata.py` | 模拟通过（MySQL 模式） | 环境阻塞：暂无真实租户 | MySQL 模式默认 2881 与微秒 timeout 协议覆盖；不宣称 Oracle 模式或真实跨代理 KILL 结果。 | `S:docs/phase-12-mysql-family/README.md`; `S:docs/phase-15-acceptance/数据库验收矩阵.md` |
| oracle | `backend/app/adapters/oracle.py`; `backend/app/adapters/oracle_metadata.py`; `backend/app/adapters/oracle_read_catalog.py` | 真实环境通过 | 真实环境通过：Oracle 23.26.3.0.0 / Thin 3.4.2 | Service 名、schema/引号大小写、LOB/数值精度、CSV、目录查询与 ORA-01466 边界。 | `S:docs/phase-12-native-adapters/main-review.md`; `S:docs/phase-15-acceptance/数据库验收矩阵.md` |
| sqlserver | `backend/app/adapters/sqlserver.py`; `backend/app/adapters/native_relational.py` | 真实环境通过 | 真实环境通过：SQL Server 16.0.4295.3 / pymssql 2.4.2 | dbo、Unicode/DECIMAL/MONEY、CSV；驱动全局 timeout 串行，无公开安全取消时如实报告未知结果。 | `S:docs/phase-12-native-adapters/main-review.md`; `S:docs/phase-15-acceptance/数据库验收矩阵.md` |

## 解读边界

- 总体十类适配器实现保留；Oracle/SQL Server 被接受的真实实例覆盖已由 S12 本地集成通过。S15 首次完整回归的两项失败来自遗留的“不得注册 Oracle/SQL Server”断言；仅测试断言修订后最终全量回归 1179 通过、0 失败。修订不改变适配器实现。见首次运行 `../../.git/acceptance/s15-backend-final-audit-aed4e0402ef04aae97ca8e5396b8a7ac/health-window-20261002-7f0f699e/run-aca23265460c/pytest-complete.log`、最终运行 `../../.git/acceptance/s15-backend-final-audit-aed4e0402ef04aae97ca8e5396b8a7ac/health-window-20261002-7f0f699e/run-98feb6511329/results.json`、[公开最终审查](../phase-14-main/main-backend-full-final-review.json) 与 `../../.git/acceptance/s15-backend-final-audit-aed4e0402ef04aae97ca8e5396b8a7ac/test-registration-revision-20261002-01/docs/phase-15-backend-final-audit/test-registration-revision/README.md`。
- 用户已确认 TiDB、Doris、StarRocks、OceanBase 暂无实例，按协议完成暂行验收，保留未验证标注；后续真实实例可沿现有 fixtures 分族补验。
- 受控 HTTP 模型只用于确定性集成/协议测试，不证明 SQL 准确率。真实模型固定问题集尚未运行；原 Java 的 6 条 OSS 文件用例环境阻塞，Python 的 6 条 local 文件用例单列，不能作为匹配模型对照。2026-10-03 固定源码 mock-API UI 门禁通过不构成真实模型效果或数据库覆盖证据，真实模型基准仍待运行；见[最终 UI 回执](../phase-15-ui/main-ui-final-review.json)。
- OSS/OCR 不是数据库类型，但同样没有真实服务配置；其真实云服务验收仍为环境阻塞，不因数据库矩阵有六个真实实例而解除。
