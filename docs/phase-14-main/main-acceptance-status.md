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
