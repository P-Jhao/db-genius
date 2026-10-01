# S15 对照工具主代理复验

状态：测试工具子阶段通过，提交 `77abe26`；完整真实模型效果验收尚未运行。本记录不将工具测试、UI mock 或原版单次诊断计为迁移效果通过。

冻结清单 `helpers-freeze-20261001T035308684796Z.json` SHA256 为 `89cfd9d43981f7b1ecd90d293a0e96abf6b339ee4f9e4c1320c45a24f93ebe6b`，主代理逐项校验 27 个文件哈希。该清单描述子代理交付的原始 bytes；Git 换行规范化与后续交接文档不改变该历史含义。

主代理使用既有 Python 3.12 runtime，显式展开 real_model_*.py 文件列表，Ruff 全通过；mypy --follow-imports=silent 对 17 个 helper/CLI 源文件通过。设置进程内 `SQLCHAT_REAL_TARGET_CHECK=1`，oracle/relay/body/evidence/answers 五个文件 **33 passed，26.25 秒，无跳过**。包括实际专用 PostgreSQL/MySQL 的独立查询判定、列映射、顺序、重复、NULL、小数、变化与精确清理，以及受控 HTTP 流、chunked entity framing、认证、透明参数转发、错误、usage 和最终答案 gate；后者为测试工具模拟校准。

再次独立运行 `scripts/acceptance/real_model_benchmark.py --calibrate`：原 Java 18110/Python 18109、普通 user、两类实际目标库、后台 Worker 连接及结构文档四组均通过，等价快照通过，模型调用数为 0。证据 `calibration-20261001T040204978110Z.json`。随机数据及用户按 fixture 精确清理；未打印或保存密码、密钥、token。

最终 benchmark 要求已验收集成后重建的 Python image SHA 与实际 image 一致，当前旧共享草稿镜像不能作为最终候选。普通 Agent 温度 0.7 与分类禁 thinking/省略采样及 response_format 的迁移差异单独交回开发子代理；relay 不覆写请求。自由文本答案必须人工审查，工具结果正确不自动意味着回答正确。原版 OSS 文件环境缺失保留环境阻塞，Python local 文件独立验证不能算同条件通过。旧聚合诊断未覆盖最终答案 gate，明确仅保留历史诊断含义。

已检查工作区与 SQLChat AGENTS.md；没有功能边界或核心目录变化，本子阶段不修改。
