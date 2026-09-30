# 默认模型切换交接

用户于 2026-09-30 明确指定默认模型改为 `deepseek-flash`，地址继续使用 `https://api.deepseek.com`。系统无用户配置时的回退模型、内建 DeepSeek 供应商的新配置默认值同时更新；已有内建供应商记录在初始化时幂等同步，用户自行保存的模型配置和密钥保持不变。

`deepseek-flash` 上下文窗口精确登记为 1,048,576 Token，依据 [DeepSeek 官方模型列表契约](https://api-docs.deepseek.com/api/list-models/)。其他原有模型和供应商继续可选，无密钥时仍明确报模型未配置。

临时密钥仅保存在 Git 忽略的 `backend/.env`。主代理实际模型列表请求返回 HTTP 200，并使用项目 CompatibleChatModel 完成一次真实流式回答与 usage 校验。此证据不等同于完整 Text2SQL 效果验收；真实工具链和原版同模型对照另行验证。

代码与测试范围：`app/core/config.py` 的默认模型名一行、`services/model_config.py`、`services/model_config_info.py`、`tests/test_model_config.py`。阶段提交不包含正在开发的 S14 观测配置。

主代理从明确暂存的版本导出独立副本，Ruff 通过，mypy 应用 50 个模块通过，真实 PostgreSQL 模型配置与本地协议专项 `tests/test_model_config.py` 为 5 passed（14.24 秒），覆盖新库回退、旧内建供应商同步、非内建配置保留、默认窗口、脱敏和无密钥错误。副本不含 S09–S14 未提交实现或本地真实密钥。

根目录及 SQLChat AGENTS.md 已检查，本次默认配置变更不改变功能边界或核心目录，不作修改。
