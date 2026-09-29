# 系统基础契约与阶段交接

提交：S01 `1fb2676`；S02 `a4414d0`。

## S01 工程基础

- 对应 F-02/F-03/F-05、C-01 至 C-05、C-08/C-09。
- FastAPI 统一前缀 `/api`，成功响应为 `{code:200,message:"success",data:...}`。
- `BusinessError(code: int, message: str, status_code=200)`：普通业务失败使用 HTTP 200 与整数业务码；认证会话失效使用 HTTP 401。`message` 可以是原 `messages*.properties` 中的错误键，由 `Accept-Language` 解析七语言；字面量保持原文。
- `app.schemas` 负责请求与公共 VO 的 camelCase 映射。DTO 不暴露数据库口令、模型 API Key 或对象存储键。原数据库类型缺省为 `mysql`。
- 仅已实现的 health/auth 路由装配到 `main.py`；新路由需由所有者显式注册，不使用空壳成功接口。
- 默认总会话 86400 秒、活跃 3600 秒、SQL 30 秒/100 行，Agent 步数 10/20/15，分别对应 SQL、workflow、compare。
- Python 依赖由 `uv.lock` 锁定。容器监听 8109，安装使用 `uv sync --frozen --no-dev`；开发使用 `uv sync --frozen --extra dev`。

## S02 系统库与认证

- Alembic `0001_initial` 创建 `app` schema、原七张业务表和 `auth_session`。认证会话只存 token SHA-256 摘要；记录总期限与最近活跃时间。
- 独立步骤执行 `uv run --frozen alembic upgrade head`，再执行 `uv run --frozen python -m app.services.bootstrap`。API 启动不自动建表或运行迁移。
- 原管理员习惯为 `admin/admin123`；生产部署必须设置 `SQLCHAT_BOOTSTRAP_PASSWORD` 并更换测试/默认凭据。已经存在的管理员不会被覆盖。
- `app.core.auth.current_user` 支持裸 `Authorization` token 或 Bearer。资源服务可用 `require_owned(session, Model, id, user_id, error_key)` 做统一归属校验。
- `app.core.security.encrypt/decrypt` 使用 32 字节 AES-GCM 密钥及原 12 字节 IV + 密文 + tag 的 Base64 格式；缺失或长度错误显式失败。

## 验证记录

- `uv lock` 成功，解析 134 个包；`uv sync --frozen --extra dev` 成功。
- 独立 PostgreSQL 16 测试容器：`alembic upgrade head` 成功，`alembic check` 无新增操作；`bootstrap` 成功。
- `pytest -q tests/test_core_contracts.py tests/test_core_auth.py`：9 passed，覆盖原默认、DTO、翻译、密文格式、登录/错误/禁用/退出、总期限/活跃期限、跨用户资源 ID。
- `ruff check` 与 `mypy` 的适用模块通过，其他 Agent 模块由其所有者单独验收。
- 未连接旧生产库，未验证旧生产数据迁移；模型配置、数据源 API、后台任务属于后续阶段。
