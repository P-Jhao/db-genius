# 模型调用参数对齐修复

业务基线：accepted S10 `13d459564a808bc7b9f5f096f833fcadc15dd633`，包含已验收 SQL 诊断修复 `a83368f`。本次独立修复在 HEAD 导出的隔离副本中完成，不包含 S11 比较能力。此前基于 `007a6ea` 的 103 项预验证不替代本次 S10 基线回归。

原版真实 wire 对照确认普通 Agent、工具后续与摘要明确发送 `temperature=0.7`；IntentClassifier 不发送采样参数或 `response_format`，发送 `thinking={"type":"disabled"}`。Python 此前普通调用缺少 temperature，分类请求额外强制 JSON 响应模式且未关闭 thinking，影响效果对照。

| 调用目的 | temperature | thinking | response_format / top_p / max_tokens |
| --- | --- | --- | --- |
| 意图分类 | 不发送 | `{"type":"disabled"}` | 不发送 |
| 普通问答、SQL Agent、工具后续 | `0.7` | 不发送 | 不发送 |
| 最终摘要、步骤摘要、手动和自动上下文压缩 | `0.7` | 不发送 | 不发送 |

`ModelStream.call` 使用专门的 `classification` 标志选择参数；分类入口保留原提示词及 `Classification.model_validate_json` 校验。分类模型返回非法 JSON、缺失字段、非法 intent 或越界 confidence 仍失败。取消、工具 JSON 校验和实际 usage 累计逻辑未改动。

手动上下文压缩直接调用模型，因此显式传入共享 `DEFAULT_TEMPERATURE`。底层 `CompatibleChatModel` 和 relay 无改动，不设置全局采样或 thinking 默认值。S10 工作流、附件授权与完整性验证保留在新基线；对基线导出 ZIP 逐文件核对，仅三个已有业务文件发生变化。

## 文件与验证

- 业务变更仅 `backend/app/agent/streaming.py`、`backend/app/agent/graph.py`、`backend/app/services/context_compress.py`。
- 新增 `backend/tests/test_model_parameters.py`，204 行、12 项。使用真实本地 HTTP/SSE 服务捕获最终 POST JSON，覆盖分类、问答、SQL 工具回传、终止后摘要、步骤摘要、手动/自动压缩、原模型传输无全局默认值、usage、HTTP 错误和取消。
- `run-checks.ps1` 可复跑 Ruff、严格 `mypy app` 和协议/graph/context/SQL repair/abort/workflow 回归。真实 PG/MySQL 测试读取专用容器配置到进程环境，禁止输出凭据，不启动或清理容器。
- `ruff.txt`、`mypy.txt`、`pytest.txt` 记录本次集成副本实际结果；`files.tsv` 给出本次独立变更和交付证据的 SHA256、字节数，不包含原基线文件或导出 ZIP。

2026-10-01 集成副本实际结果：Ruff `app tests` 全通过；严格 `mypy app`（无 `--ignore-missing-imports`）74 个模块通过；相关 22 个测试文件 **161 passed in 316.16s**，无跳过。包含真实 PG/MySQL 的上传导入、200/207 行完整性、MySQL 反引号、PG 大小写标识符、NULL/文本/Decimal、DDL 后 schema 刷新、普通与文本附件工作流、数据库语句修复及 TCP 断连中止。

## 适用范围与风险

本次验证真实 HTTP 协议及调用分支；商用模型输出效果需 S15 使用实际服务继续对照。供应商若拒绝 `thinking` 参数，请求会显式失败，不移除参数后自动重试。本次无新依赖、配置、API 或数据库迁移；AGENTS.md 已检查，功能边界和核心目录不变，因此保持原样。
