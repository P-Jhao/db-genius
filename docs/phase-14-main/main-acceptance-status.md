# S14 主代理验收记录

记录日期：2026-10-02。状态：部署运行门槛已通过；最终全量后端回归已通过；固定源码的 UI 复验已通过；S15 同模型效果对照仍待完成。此记录不代表完整迁移验收通过。

原 Java 后端的 289 个源文件已再次逐项核对，与只读副本建立时的清单一致。运行 API、Worker 和前端均使用主代理从冻结源码实际构建的镜像，健康修订没有改变这三个镜像。

| 验收项 | 主代理实际结果 | 公开证据 |
|---|---|---|
| 修订后的部署契约 | 4 通过、0 跳过；包含真实 Compose 配置解析 | 主代理 Node 命令输出及健康包冻结清单 |
| 明确的新指标周期 | 初始化器退出 0；清理 API 3、Worker 5 个识别出的数据库文件；两处普通标记文件哈希保持 | main-explicit-epoch-init-receipt.json |
| 完整 stop/init/up | 五个服务健康、迁移与初始化器退出 0；Worker 探针超时 12 秒；三个镜像一致 | main-health-full-start-receipt.json |
| 恢复正常运行配置 | 关闭临时 OTLP 输出后再次启动通过；四个命名卷不变，文件后端为显式 local | main-normal-runtime-start-receipt.json |
| Linux 文件路径与符号链接 | 完整上传模块 14 通过、0 跳过；派生测试镜像不改变生产镜像 | main-linux-upload-symlink-receipt.json |
| 真实追踪和语言复位 | HTTP→发布→Worker→元数据链路、并发 fr/ja 和后续 en 复位通过；setup/call/teardown 均成功 | main-trace-only-03-result.json |
| 原后端只读 | 289 文件一致、0 变化 | main-original-source-readonly-check.json |

此前 8 秒 Worker 探针的完整启动失败和 trace02 调度失败保留为历史证据。修复后的独立复验不改写这些失败记录。单 API/Worker 重启保留指标周期与实际数据持久化的既有证据继续有效。临时追踪接收器已按准确 PID 与测试脚本路径核对后停止；只移除了两处准确的测试标记文件。

S15 UI 在共享工作目录上的 36 张截图通过，但该源码指纹与已验 UI30 不同，不能作为最终冻结版本的通过证据。最终 UI 复验必须绑定 e4a2782b8a6c148083ba68c54bd0f9d8c02e9825ea7f4cefbb7eff61a9f69d6b。

TiDB、Doris、StarRocks、OceanBase 保留实现与协议验收，真实实例未提供。OSS/OCR 保留实现和模拟验收；没有真实服务配置。真实模型矩阵将使用 deepseek-flash 与原版同条件对照；原版文件导入因 OSS 不可用另记环境阻塞，不能计入同条件通过。

最终全量回归第一次运行：1178 通过、2 失败、5 跳过。两项失败均为 test_mysql_family_workflow.py 仍断言 Oracle/SQL Server 未注册，与已实现的 S12 能力冲突。队列不可用独立用例、Ruff 与全应用 strict mypy 均通过，785 个源文件守卫保持。五项跳过分别由独立队列、浏览器、重启持久化和 Linux 路径验收补证；此处不把失败运行登记为通过。证据：health-window-20261002-7f0f699e/run-aca23265460c。

修正过时断言后的主代理完整复跑：1179 通过、0 失败、5 跳过；队列不可用独立运行 1 通过，部署契约 4 通过，Ruff 与全应用 strict mypy（103 源文件）通过，791 个文件守卫保持。五项跳过的独立证据分别为队列专门运行、真实 Chrome/Nginx 5 项部署测试、重启前后 prepare/verify 和 Linux 上传完整模块 14 项。冻结候选 SHA：8f49dff0680400dc084da8aaa2da5596377b3b4db2c0b71d537a520ca50f1709；验收证据 run-98feb6511329，复验日志与 main-backend-full-final-review.json 单独保存。首次失败日志与过长 Windows 预检快照保持原样。

固定源码 UI 的截图时序修订后，主代理独立完整复跑退出 0：18 场景、36 张截图、0 页面错误、0 交互断言失败。人工检查确认历史抽屉与两条消息位于视口内，会话列表显示完整，历史回放有用户消息与最终摘要，试用空态与受限控件正确。drawer/list 差异为 0%，普通聊天 0.11% 为已有 Upload Excel → Upload file 文案修复造成的控件位移，trial 0.10% 为已有上传隐藏规则。数据库类型选择框差异 3.97% 与用户明确授权一致。生产源码指纹保持 e4a2782b8a6c148083ba68c54bd0f9d8c02e9825ea7f4cefbb7eff61a9f69d6b，依赖与原差异阈值未修改；本次只修订两个测试文件。最终 root 回执为 docs/phase-15-ui/main-ui-final-review.json，run790a2c1d-c727-41c4-ba07-5884c6793334；原 44.44% 失败记录仍保留。此证据使用 mock API，不能代替真实模型效果对照。

## 2026-10-03 正式组装与提交交接

正式工作树从冻结基线 `cbe4815f1aa7ac7c266040f69f9231f8487bafbd` 完成 835 个目标文件组装并通过 root review：835/835 目标匹配，273 个后端路径与接受基线一致且 0 处不匹配，前端源码指纹为 `e4a2782b8a6c148083ba68c54bd0f9d8c02e9825ea7f4cefbb7eff61a9f69d6b`，配置私有值匹配数为 0。组装写入 717 个文件、118 个未变，隔离 2 个 draft，并保留无关文件。正式审查记录见[组装审查](../phase-15-acceptance/main-assembly-review.json)。

## 2026-10-03 Compare preflight 定向部署与新一轮效果复核

在受控提交 `9c077413105a9ec3236416f21b83b4fae18753bb` 后，主代理将新的 API/Worker 镜像定向部署；四个命名卷、受保护容器和前端镜像保持不变。应用健康通过；迁移版本检查与指标 epoch 初始化分别通过；141 个源码映射路径检查通过且 0 处不匹配。部署回执见[运行快照](../phase-15-classification-report-fix/compare-preflight-runtime-after-review.json)、[镜像绑定](../phase-15-classification-report-fix/compare-preflight-compose-accepted-images.json)和[源码映射复核](../phase-15-classification-report-fix/compare-preflight-host-source-map.json)。该定向部署没有重跑 clean-start、整栈启停、T-33 或 T-34 门禁；这些范围仍分别由既有 S14 回执支撑。

随后两项独立 Python-only 真实 provider 运行均到达终态，但机器状态均为 `review-required`：分类 18 行/21 turns，6 passed、12 review-required、0 failed；受影响效果 36 行/36 turns，36 review-required、0 failed。主代理对这 57 个 turn 的独立答案复核确认 13 个事实错误 turn、1 个未交付 turn，共 14 个 failure finding；另有 14 个措辞 turn 不计失败，含措辞的 finding 共 15 条。29 个 turn 被判为 supported。最终答案与完整迁移均未获接受；待修复 finding 仍开放。机器运行摘要、逐项证据及人工复核边界见[新一轮复核记录](../phase-15-classification-report-fix/FRESH-PREFLIGHT-REVIEW-20261003.md)。本补记不改写此前矩阵、旧 run 原件或 S14/S15 部署门槛，也不代表完整迁移通过。

本次交付分为四个提交：`a55adb29eacebdb6881dc8bdf8a85e276e68286e`（修正十种数据库工作流注册验收断言）、`710e048c3c5981fbfd002c0440a6a4b19880df99`（S14 部署与跨进程监控）、`f2cbd4f47747fae0a9beb2f24dad7bbbc38bed0d`（原界面 UI fixture 与截图稳定性验收）、`c4ec379c9e23b0db135b7f85f094d47e40ea81da`（迁移验收与正式组装证据文档）。

真实模型对照已运行完毕，但**验收状态仍为 incomplete**：`deepseek-flash` 共 120 行、60 组配对；Python 结果为 11 失败、43 待人工复核、6 通过，Java 为 42 失败、12 通过、6 组文件导入环境阻塞。54 组非文件配对均标记参数一致，参数失配为 0；6 组 `file_import` 的 Java OSS 条件不可用，Python local 文件结果不能替代匹配对照。结果见[真实模型基准记录](../phase-15-real-model/benchmark-20261002T220250206579Z.json)。因此正式组装与代码交付已完成，完整迁移验收仍须等待失败项调查和人工复核，不能登记为通过。

首轮模型结果的缺陷分类、人工复核边界、独立清理计数和原版源文件完整性见[首轮结果复核](../phase-15-real-model/FIRST-RUN-REVIEW.md)。

## 2026-10-03 修复后定向真实效果状态

已接受产品修复基线 `3b97ad1bc5c332070d624b037ff6162fd6ad2b7d` 的历史受控回归为 23 个测试模块 199 passed、0 failed、0 skipped，Ruff 全量 app/tests 与 strict mypy 105 个 app 源文件通过，128 个路径哈希稳定。该回归绑定此固定产品修复基线，不作为后续 compare 编排候选的回归证据。正式 runner 以 `bb589d48b91dc96cc3c0039105056019be5ccad0` 为运行源 HEAD，离线门禁 41 passed、2 skipped；opt-in PostgreSQL/MySQL oracle 另跑 2 passed、0 failed、0 skipped。Ruff 11 路径和 strict mypy 8 个 helper 源文件通过，部署后端 140 个路径及受保护源码守卫稳定。

主代理已在既有栈部署接受镜像并复核健康与 readiness。随后两个独立 Python-only 真实 provider 专项在同一源 HEAD、稳定 runtime 上结束：分类 18 rows/21 turns 状态 review-required（6 passed、12 review-required、0 failed）；受影响效果 36 rows/36 turns 状态 failed（1 failed、35 review-required；PostgreSQL compare 第 3 次重复未取得结构差异结果）。两组并行运行，不能作性能 baseline 或新 Java/Python 全矩阵配对结论。主代理复核绑定了 57 个 turn 的定位符、状态和答案 SHA，确认 1 项任务失败、7 项答案事实问题及 1 项准备 metadata 措辞问题；该复核不代表最终答案整体验收。完整迁移未通过，原版 Java 历史失败和 6 项 OSS 文件环境阻塞保持不变。

证据见[修复后定向运行记录](../phase-15-classification-report-fix/TARGETED-RUN-REVIEW.md)、[当前答案复核记录](../phase-15-classification-report-fix/main-current-answer-findings.json)、[受控修复审查](../phase-15-classification-report-fix/main-fix-review.json)、[runner 离线审查](../phase-15-classification-report-fix/main-runner-review.json) 与 [runtime 审查](../phase-15-classification-report-fix/main-runtime-review.json)。原始定向 JSON/JSONL 与结果记录已随提交 `db409e9` 固定。

## 2026-10-03 Compare preflight 受控修复门禁

代码提交 `9c077413105a9ec3236416f21b83b4fae18753bb`（`fix: 保障结构对比执行与报告证据边界`）经主代理评审，状态为 `controlled-regression-accepted-real-model-pending`。初轮真实 PostgreSQL/MySQL/MongoDB 目标已启用的 38 模块受控回归为 329 passed、1 failed、0 skipped；唯一失败是旧分类断言仍期望旧共享证据规则文案，不是把初轮写成全绿。原失败日志保留在[初轮 pytest 日志](../phase-15-classification-report-fix/pytest-compare-preflight-initial.log)。只调整两处测试措辞后，主代理复跑 3 个分类/路由模块为 23 passed、0 failed、0 skipped，且生产源码与初轮一致；这是有意缩小的复查范围，两个数字不得相加成单轮 352 passed，也没有证据称修正后的 38 模块全量重跑通过。

最终 Ruff 全量 `app`/`tests` 通过，strict mypy 106 个生产文件通过。审查绑定的提交共 19 个文件（4 个生产源码文件和 15 个测试文件）；原 Java 289 个文件只读核对 0 变化，两个 AGENTS 文件未改。主代理的审查和结果/日志哈希见[受控修复审查](../phase-15-classification-report-fix/main-preflight-fix-review.json)，修正措辞后的 3 模块日志见[复测日志](../phase-15-classification-report-fix/pytest-compare-preflight-assertion-recheck.log)。

这只接受了窄范围受控实现与回归门禁，门禁本身不是部署或真实 provider 运行。准备 V4 文档时主代理另行报告已完成定向部署，两个新的真实模型专项刚启动且当时尚无终态；其后续状态不属于本节受控门禁证据，见候选交接说明。历史 120 行/60 组模型矩阵仍为 incomplete；57 turn 答案复核中的 1 项任务失败、7 项答案事实问题和 1 项准备 metadata 措辞记录保持不变。完整迁移和最终答案均未接受。
