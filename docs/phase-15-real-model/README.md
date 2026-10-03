# S15 真实模型对照

当前状态：helpers 已实现，实际 API/fixture 校准通过。首轮和第二轮真实模型对照均已完成采集，但两轮机器报告状态均为 `incomplete`；第二轮含 120 行、60 组配对和 138 个 turn。失败、待人工复核、参数不可比和原版 OSS 阻塞项均不构成验收通过，人工答案复核也尚未完成。详见[第二轮结果复核](SECOND-RUN-REVIEW.md)及[首轮结果复核](FIRST-RUN-REVIEW.md)。S12 真实数据库、S14 受控模型部署测试及受控模型回归不作为真实 provider 效果证明。

## 原版编译与只读证据

原 `db-genius/db-genius-backend` 只读复制至当前仓库 Git 忽略的 `.git/acceptance/original-73bb7e87cf32`，不携带真实环境文件、Git、依赖目录或原构建产物。官方 `maven:3.9.16-eclipse-temurin-21` 容器在副本执行 `mvn -B -DskipTests package`：exit 0 / BUILD SUCCESS，12 分 10 秒，六模块完成。该结果证明编译打包，不证明原版启动或用例通过。

源文件 SHA 清单保存在 `.git/acceptance/original-73bb7e87cf32-manifest.json`。排除构建产物与本地工具目录后，原后端与副本 289 文件完全相同，编译后原源哈希无变化。resources 敏感配置扫描未发现非环境引用的硬编码值；不把任何配置秘密写入证据。

## 原版运行交接

主代理管理独立 `sqlchat-s15-java` 网络、PG16/Rabbit3.13 容器及 Java 启停。系统库使用副本原 schema.sql 只读初始化，网络别名为 `java-postgres`/`java-rabbit`，数据库与 Rabbit 不发布主机端口；原 Java 只监听 loopback 18110。建议 Java 1 GiB、2 CPU、heap 512 MiB；PG/Rabbit 各 512 MiB。禁止复用或清理已有部署卷。

在仓库根目录运行 `backend/.venv/Scripts/python.exe scripts/acceptance/java_runtime_contract.py --write-env`，读取主代理已创建的 Git 忽略 `.git/acceptance/s15-java-runtime/postgres.env` 与 `rabbit.env`，生成同目录 java.env；stdout 仅输出路径、变量名和无秘密的 docker argv，不启动任何服务。重复写入会失败，防止改变已持久化模型配置所需的加密密钥。真实 Flash key 不写该文件，后续中继只从 backend/.env 读取至内存。

- Boot JAR：`C:/Users/22126/Desktop/web/text2sql/sqlchat/.git/acceptance/original-73bb7e87cf32/db-genius-web/target/db-genius-web-1.0.0.jar`。
- 初始化 schema：`C:/Users/22126/Desktop/web/text2sql/sqlchat/.git/acceptance/original-73bb7e87cf32/db-genius-web/src/main/resources/db/schema.sql`。
- 完整 runtime 环境变量与启动 argv：上述脚本返回的契约；健康路径为 `http://127.0.0.1:18110/api/health`。
- 原 DataInitializer 默认会创建固定 admin 密码；主代理在 Java 首次启动前通过独立系统库插入随机 bcrypt admin 密码，以避免该默认初始化。普通测试用户均经 API 创建，使用与 Python 相同 user 角色。

原版 OssConfig 在启动时强制四个 OSS 配置非空。隔离非文件对照暂设明确无服务的 `oss.s15.invalid` endpoint 与占位 bucket/AK，仅满足客户端初始化，不是可用 OSS，不执行文件上传请求。原版文件对照因缺实际 OSS 凭据保持“环境阻塞”；保留此用例，不计对照完成。Python 的显式本地存储文件工作流另行真实验证。

## 固定问题集

`backend/tests/real_model_cases.py` 固定 10 类中文问题、每类三次，分别在 PostgreSQL/MySQL 的原版/Python 独立等价数据库快照运行。覆盖聚合、LEFT JOIN、NULL、日期边界、连续追问、歧义澄清、数据库错误修复、CSV 导入后逐行验证、PRE→TEST 结构对比和 DROP/TRUNCATE 拒绝。连续追问复用会话；每次独立初始化数据，不用上次答案替代执行。

数据全部为合成客户/订单/导入联系人。问题使用显式可独立查询的期望结果，写入后另建连接核对数据，拒绝执行前后比较数据库快照。真实效果必须从现有 API→LangGraph/原版 Agent→工具→数据库完整链路采集，禁止用单次模型 astream 回答替代。

证据落地实际生成参数、数值 usage/耗时、状态、错误类别及独立判定布尔值。按主代理明确授权，另保存本固定合成 dataset 的有限最终答案、预期结果与受限列/实体的归一化执行结果，用于审查回答正确性；完整 prompt、reasoning、SSE/历史/工具原文及密钥均不保存。中继不覆写原版或 Python 生成参数；参数失配记为“不可比/待修复”，不能冒充同条件通过。

## Helpers 校准记录

- 2026-10-01：oracle/relay/body/evidence/answers 31 passed、2 skipped；16 个 helpers 文件 Ruff 与 mypy 通过。此轮 skipped 是未设置显式真实 target 开关；最后答案细化后另复跑 answers/evidence，11 passed。
- 主代理已显式启用 `SQLCHAT_REAL_TARGET_CHECK=1` 独立复跑 oracle：6 passed，包括真实 PostgreSQL/MySQL 期望值、等价快照、变化检测与精确清理。仅为测试工具校准。
- `--calibrate` 已在原版 18110/Python 18109 实际 API 验证普通 user 登录、模型配置、真实 Worker 连接验证与结构文档；PostgreSQL/MySQL 四组随机 fixture 完成后精确清理，0 模型调用。证据为 `calibration-20261001T033008991100Z.json`。
- 原版实际分类已诊断：同步 HTTP 使用 chunked body，补齐 relay 请求体解析后 ambiguity 为 1 个真实调用，clarify/usage EOF 正常。完整生成参数证据 `java-diagnostic-20261001T034653135813Z.json`；温度/响应格式差异及 Python 修复接口见 [参数基线](PARAMETERS.md)。旧 aggregate 诊断虽验证执行与 usage，其旧判定尚未检查最终答案，不作为回答正确证据。
- 全量矩阵至少 120 条版本/库/题目/重复组合；其中原版文件链路 6 条环境阻塞，Python 对应 6 条独立本地文件验证，不计为同条件文件对照通过。

执行命令、参数门槛和答案复核边界见 [操作说明](OPERATIONS.md)。历史状态记录：截至 2026-10-02，全量真实模型 benchmark 尚未运行；2026-10-03 首轮实际模型 benchmark 完成采集后结果仍未通过验收；随后第二轮也完成采集，仍为 incomplete，详见[第二轮真实模型对照复核](SECOND-RUN-REVIEW.md)。本次未改变工程功能边界或核心目录；已检查工作区与仓库 AGENTS.md，保持不变。
