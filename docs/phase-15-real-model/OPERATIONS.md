# S15 对照 runner 操作说明

## 范围与前置条件

入口：`scripts/acceptance/real_model_benchmark.py`。只通过实际原 Java/Python API 提问，不用单次 provider completion 代替 Agent。固定服务商 `https://api.deepseek.com`、模型 `deepseek-flash`、语言 `zh-CN`、角色 `user`；10 类题目在 PostgreSQL/MySQL 各重复 3 次。各题实际 API 连接/工具使用原版与目标版自己的实现。

固定聚合、JOIN、NULL、日期、连续追问、修复、文件、对比、拒绝题目设置相同 `confirmedIntent`，测试相应完整 Agent/工具链；歧义题不设置该参数，走各自实际分类器和澄清流程。连续追问与第二次拒绝复用各自同一实际会话。

主代理管理 Docker 启停。runner 要求原版 loopback 18110、Python loopback 18109，专用目标实例 `sqlchat-migration-test-postgres`/15432 与 `sqlchat-migration-test-mysql`/13306 在线。不重启、不删除容器，不修改部署配置，不连接其他数据库。

系统库 admin 只在内存用于创建随机 `s15_real_<20 hex>` 普通用户。原版凭据从 Git 忽略 `.git/acceptance/s15-java-runtime/admin.env` 读取；Python 凭据从 `.env.s14` 读取。两者的创建用户角色及登录返回角色必须相同。中继 access key 随机生成，实际模型 key 只在进程内部由 dotenv 读取 `backend/.env`；禁止通过命令行、环境转发、日志或报告传递真实 key。

目标数据库口令通过内部 `docker inspect` 读取，不输出 inspect 内容。只创建/删除本轮随机 `s15_<16 hex>_<py|java|pre|test>` 数据库及对应随机角色，每个 fixture 的 `finally` 精确清理并验证该库/角色已消失。应用会话 `finally` 登出并仅删除随机测试用户的配置、文件与历史。

## 复跑工具校准

在仓库根目录运行：

```powershell
& backend/.venv/Scripts/python.exe -m pytest -q backend/tests/real_model_oracle_test.py backend/tests/real_model_relay_test.py backend/tests/real_model_relay_body_test.py backend/tests/real_model_evidence_test.py backend/tests/real_model_answers_test.py
& backend/.venv/Scripts/python.exe -m ruff check backend/tests/real_model_*.py scripts/acceptance/real_model_benchmark.py
& backend/.venv/Scripts/python.exe -m mypy --follow-imports=silent backend/tests/real_model_answers.py backend/tests/real_model_answers_test.py backend/tests/real_model_api.py backend/tests/real_model_cases.py backend/tests/real_model_database.py backend/tests/real_model_evidence.py backend/tests/real_model_evidence_test.py backend/tests/real_model_oracles.py backend/tests/real_model_oracle_test.py backend/tests/real_model_relay.py backend/tests/real_model_relay_body.py backend/tests/real_model_relay_body_test.py backend/tests/real_model_relay_test.py backend/tests/real_model_report.py backend/tests/real_model_runner.py scripts/acceptance/real_model_benchmark.py
& backend/.venv/Scripts/python.exe scripts/acceptance/real_model_benchmark.py --calibrate
```

`--calibrate` 只验证实际普通用户、模型配置、Worker 与两种目标库的等价快照，不发送 chat，不调用实际 provider。该模式的 relay 指向无服务的 loopback 9；若意外发起调用，校准报失败。最终文件写入 `docs/phase-15-real-model/calibration-<UTC>.json`，拒绝覆盖既有证据。

真实 oracle 可显式启用 `SQLCHAT_REAL_TARGET_CHECK=1` 后运行 `real_model_oracle_test.py`；此校准已由主代理复跑，不需要无新疑点重复执行。

## 原版诊断

经主代理授权后运行：

```powershell
& backend/.venv/Scripts/python.exe scripts/acceptance/real_model_benchmark.py --diagnose-java
& backend/.venv/Scripts/python.exe scripts/acceptance/real_model_benchmark.py --diagnose-java --diagnostic-case ambiguity
```

仅执行 PostgreSQL 原版 aggregate 与 ambiguity 各一次，采实际 Agent 和分类请求的生成参数/usage。用途是原版校准及查清迁移参数差异，不满足两个库、三次重复或版本对照要求。记录模式为 `original-diagnostic`，总状态固定为 `diagnostic`；逐题成功/失败另行保留。

## 最终矩阵

必须先完成 S09–S13 集成验收，并由主代理重建 Python 部署镜像。在主代理通知可以最终对照后，将已经验收的完整 image SHA 传给 runner：

```powershell
& backend/.venv/Scripts/python.exe scripts/acceptance/real_model_benchmark.py --benchmark --accepted-python-image 'sha256:<主代理验收过的完整64位镜像hash>'
```

镜像参数必须与实际 `sqlchat-s14-test-api-1` 的 image SHA 完全一致。报告记录两版本 image、启动时间、当前 commit、原版只读源清单哈希。旧共享草稿镜像的结果不能作为最终交付效果证据。

每题两版本使用新独立 fixture；执行前验证相同源快照，结构对比目标也须等价。每个重复交替版本执行顺序。每题结束追加数值 `.jsonl`，全部结束写 `.json`；中途异常仅输出错误类别并保留已产生的部分证据，绝不自动重发可能有写入副作用的请求。`--output` 仅接受 `docs/phase-15-real-model` 下尚不存在的 `.json` 路径。

## 判定与证据边界

- 查询按预期列名映射，逐列比较，显式 ORDER BY 按顺序检查；无序集合保留重复次数，NULL 与文本/布尔不同，小数使用 `1e-9` 绝对容差。回答中出现预期数字不算执行正确。
- 每个 oracle 还使用新独立连接查询目标数据库；文件导入逐行验证真实已提交数据。读取题/拒绝题前后比较完整数据库指纹；文件题仅排除预期可变的 imported_contacts，其余表必须不变。
- 修复题必须观察 gross_amount 的真实不存在列错误，并在之后得到正确执行结果。结构比较核实 pre/test 方向、精确增删表/字段、12→14 的金额精度变化，且两个库都不能发生迁移写入。
- 所有 SSE 在内存检查终态，连续会话核实真实历史顺序与最终全文。原 Java 澄清分支的 EOF 在 clarify/usage 后关闭，没有会话；作为既定兼容终态记录，不编造 done。
- relay 同时支持固定 Content-Length 与标准 chunked 请求体，拒绝两者并存或不完整 framing；读取 HTTP entity body 后透明转发，不改 JSON。请求诊断仅记录 method、固定 endpoint path、body 长度、相关 header 是否存在及 HTTP 状态，不记录 header 值或 body。响应以 `iter_raw` 原始 bytes 转发；旁路解析先拼接完整 frame，再解码 UTF-8、合并多行 data，聚合 delta/usage/DONE；证据解析错误不会改写响应或截断实际流。未知编码、缺完整 frame、缺 provider DONE 单独记错误类别。
- 实际参数不覆写；两版本每轮 generation controls profile 必须相同。失配状态是 `not-comparable`、类别 `GenerationParameterMismatch`，属于迁移待修复，不能写成外部环境阻塞。未明确证明官方默认等效时，省略值与显式值也算失配。
- 最终答案单独校验：纯 JSON 或纯 Markdown 表格按同一独立 oracle 判定列、顺序、NULL、小数和实体/金额关系；格式明确却数据错误记失败。自由文本、有附加自然语言断言或不识别的结构，均记 `review-required`/`GroundedAnswerReviewRequired`，不能因工具正确或文本包含数字而通过。结构对比的自由报告也要人工审阅；明确拒绝及歧义澄清使用专项约束判定。主代理可从本合成案例 `answerReview.finalAnswer/expectedResults/executedResults/parsedResults` 复核；不由 runner 自动把待审变成通过。
- 最终答案最多保存 8192 字符，先剔除真实 provider/relay key、登录 token、目标口令与固定问题原文，再裁剪；检测思考/DSML 泄入终答时整段不保存并待审。执行结果只保留 oracle 指定列、数值、NULL 和本固定案例已知实体；任意额外列名/未知文本不落地。此例外仅限本合成 dataset，不授权保存其他业务数据、完整 prompt、reasoning 或原始 SSE/历史/工具结果。
- usage 只累计供应商返回的非负整数；有调用缺 usage 则总量保持 null，保留已知调用数；已知 usage 须与应用 SSE 记账及调用数准确一致。汇总另列已知 token 总额与未知 usage 调用数，不能用已知部分伪称完整消耗。
- 原版 OSS endpoint 为 `.invalid`，只用于启动初始化；文件原版 6 条保持 `OriginalOssUnavailable` 环境阻塞，不请求假服务。Python 本地存储 6 条单独记 `local-file-only`，不得算同条件通过。最终总报告因此必须保留 `incomplete`，直到真实同条件文件环境和相应验证补齐。

覆盖 T-11、T-13、T-15、T-18、T-20、T-25、T-29、T-31 的 S15 效果部分；权限、安全、部署、特殊数据库完整矩阵仍由各阶段既有验收证据支撑。helpers 的本地模拟测试只证明测试工具自身，不证明真实模型效果。
