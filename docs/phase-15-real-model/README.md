# S15 真实模型对照

当前状态：helpers 和正式产品修复已完成；API/fixture 校准、受控回归与定向 runner 门禁均有通过证据。首轮和第二轮完整真实模型对照已完成采集，但两轮机器报告均为 `incomplete`；第二轮含 120 行、60 组配对和 138 个 turn，仍保留失败、待人工复核、参数不可比和原版 OSS 阻塞。修复后另有两个 Python-only 定向效果专项：分类 18 行/21 turns 为 review-required（6 passed、12 review-required、0 failed），受影响效果 36 行/36 turns 为 failed（1 failed、35 review-required）。它们不是新的配对全矩阵，不能据此宣布完整迁移或真实模型验收通过。详见[第二轮结果复核](SECOND-RUN-REVIEW.md)及[首轮结果复核](FIRST-RUN-REVIEW.md)。S12 真实数据库、S14 部署及受控模型回归不替代真实 provider 效果证据。

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

## 2026-10-03 Compare preflight 代码门禁更新

代码提交 `9c077413105a9ec3236416f21b83b4fae18753bb` 经主代理评审为窄范围 `controlled-regression-accepted-real-model-pending`。38 模块初轮启用真实 PostgreSQL/MySQL/MongoDB 目标，结果为 329 passed、1 个旧测试措辞断言 failed、0 skipped；两处测试措辞修正后另跑 3 模块，23 passed、0 failed、0 skipped。没有全量 38 模块的修正后复跑证据，不能把两范围相加。最终 Ruff 全量 `app`/`tests` 通过，strict mypy 106 个生产文件通过，复测前生产源码哈希稳定。详情见[受控修复审查](../phase-15-classification-report-fix/main-preflight-fix-review.json)。

这不是新的真实 provider 运行：`realModelCalls` 为 false 指受控代码门禁没有模型调用。主代理其后另行完成 compare 候选定向部署并运行两个新的真实模型专项。V4 快照不包含这些后续回执；V5 已在独立记录中绑定终态运行和根代理 57-turn 答案复核。首轮/第二轮完整真实模型矩阵仍保留原 incomplete 状态；旧 57-turn finding 也保留为历史证据，不覆盖这次新 proposal 的 review。完整迁移与最终答案仍未接受。

## 修复候选与定向效果结果

已接受产品修复基线为 `3b97ad1bc5c332070d624b037ff6162fd6ad2b7d`：完成意图可执行性/澄清边界、比较风险说明与证据不足处理，并在直接回答和总结交付路径共享 compare report 规则。该固定基线的历史受控回归为 23 个模块 199 passed、0 failed、0 skipped，Ruff 全量 app/tests 通过，strict mypy 105 个 app 源文件通过，128 个路径哈希稳定；这项回归不覆盖后续新增的 compare 编排候选。[主代理复核](../phase-15-classification-report-fix/main-fix-review.json)记录该证据没有真实模型调用。

正式 runner 以 `bb589d48b91dc96cc3c0039105056019be5ccad0` 为固定源 HEAD。离线 41 项通过、2 项 opt-in 项由独立 PostgreSQL/MySQL oracle 另行补跑并通过（2 passed、0 failed、0 skipped）；Ruff 11 路径、strict mypy 8 个 helper 源文件通过。runner、部署后端 140 个路径及固定辅助源码守卫稳定，证据见[runner 回执](../phase-15-classification-report-fix/main-runner-review.json)。目标 API/Worker/前端镜像的定向部署、readiness 与健康检查通过，见[runtime 回执](../phase-15-classification-report-fix/main-runtime-review.json)。这些门禁证明实现和运行环境基线，不证明模型回答效果。

修复后真实模型专项仅运行 Python-only 分类 18 行/21 turns 与显式受影响效果 36 行/36 turns。主代理独立复核绑定 57 个 turn 的定位符、状态和答案 SHA，确认 1 项任务失败、7 项答案事实问题及 1 项准备 metadata 措辞问题；该部分答案复核不构成整体接受。结果和证据见[第二轮结果复核](SECOND-RUN-REVIEW.md)、[定向专项记录](../phase-15-classification-report-fix/TARGETED-RUN-REVIEW.md)及[当前答案复核记录](../phase-15-classification-report-fix/main-current-answer-findings.json)。专项原始证据与该历史记录已随提交 `db409e9` 固定。原版 Java 的历史失败、OSS 6 行环境阻塞、真实 OSS/OCR 未配置，以及 TiDB/Doris/StarRocks/OceanBase 仅协议/模拟覆盖边界均保持不变；不据此改写配对状态或数据库矩阵。

## 2026-10-03 V5 fresh provider review

新的一轮分类 run `classification-20261003092425Z` 为 18 rows/21 turns（6 passed、12 review-required、0 failed，69 model calls）；新一轮受影响效果 run `affected-python-20261003092425Z` 为 36 rows/36 turns（36 review-required、0 failed，120 model calls）。两个 run 均终态 `review-required`、runtime fingerprint 稳定，且不是新的 Java/Python 配对矩阵。二者与上方 `20261003044921Z` 历史专项是不同运行，原始 JSON/JSONL 分别保留。

根代理另对新两项运行的 57 个 turn 独立审阅：29 supported、13 factual-claim-failure、1 task-failure 和 14 wording-only turns。措辞 turn 不计失败；接受的 finding 共 15 条（14 条失败、1 条措辞）。所有 locator、答案 SHA、raw 状态与 189 次 provider usage 已绑定复核，六项 compare 分页均还原完整结果且无 migration SQL 执行。最终答案与完整迁移未接受，failure finding 保持待修复。运行、部署及人工 review receipt 与 SHA 见[新一轮复核总记](../phase-15-classification-report-fix/FRESH-PREFLIGHT-REVIEW-20261003.md)。
