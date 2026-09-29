# S03 模型配置交接

状态：后端实现与真实 PostgreSQL HTTP 测试通过；前端人工交互、真实模型服务尚未验收。提交：`b3f1e16`。

## 需求与实现

| 需求 | 实现与证据 |
|---|---|
| F-05 / T-07 | 四个内置 Provider 幂等初始化；Provider 列表需登录；当前用户配置增删改查、首条自动默认、默认切换及默认删除限制。`tests/test_model_config.py` 通过真实 PostgreSQL 和 HTTP API 验证。 |
| F-05 / T-08 | 生效配置顺序为用户默认启用、最新启用、系统默认；无系统 Key 显式报错。`resolve_active_model()` 返回含 `SecretStr` 的运行时配置，系统回退不落库；公共 VO 不含 Key。 |
| F-05 / T-09 | 已知模型按原注册表返回 `registry` 窗口；未知模型探测模型列表后仍返回 `not_found` 和 `null`，不推断窗口。支持基础 URL、`/v1` 和完整 `/chat/completions` 端点。已保存配置用解密后的 Key 请求本地 HTTP 服务验证。 |
| F-16 / T-30 | 试用模式拒绝配置写入、默认切换和两类窗口查询；读取 Provider 与配置仍可用。 |
| C-01–C-03 / T-36 | 路径保持 `/api/model-config`，响应包装为 `{code,message,data}`，公开字段为 camelCase。 |

API 路由位于 `backend/app/api/model_config.py`；服务位于 `backend/app/services/model_config.py` 和 `model_config_info.py`。应用启动时初始化 Provider，数据库迁移未完成时启动会显式失败。用户配置密钥使用 S02 AES 加密，运行时通过 `resolve_active_model(session, user_id)` 统一取得解密后的 `SecretStr`；不得把运行时对象直接序列化到 HTTP 响应或日志。编辑时未指定窗口遵循原项目的“已知注册表优先，否则沿用旧值”；独立查询未知模型始终返回 `null`。

## 验证

- 独立 Docker PostgreSQL 容器 `sqlchat-migration-test-postgres`，端口 `127.0.0.1:15432`，凭据从容器配置临时注入进程环境；没有写入仓库。
- `uv run pytest -q tests/test_model_config.py tests/test_core_auth.py tests/test_core_contracts.py`：12 passed。覆盖登录后 HTTP、跨用户访问、密钥加密与脱敏、空 Key 编辑、默认限制、试用限制、系统回退及本地 HTTP 窗口探测。
- `uv run pytest -q`：56 passed、3 skipped。跳过项为尚无对应外部服务的已有测试。
- S03 文件及对应测试的 `uv run ruff check ...`、`uv run mypy ...` 通过。全仓库 Ruff/mypy 尚有其他模块遗留错误，由各模块负责人处理。
- 真实外部模型没有可用密钥，未验证供应商实际 `/models` 响应或推理效果；本地 HTTP 模拟只验证请求路径、Authorization 及未知窗口语义。

`AGENTS.md` 已检查：本阶段只实现原定模型配置功能，未改变功能边界或核心目录，因此保持不变。
