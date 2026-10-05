# SQLChat

SQLChat 是一个 DB-Genius 风格的 Text2SQL 项目，使用 Vue 前端和 Python/FastAPI 后端，由 LangChain 与 LangGraph 承担模型查询流程。

## 本地部署

需要安装 Docker Desktop（包含 Docker Compose），并在 PowerShell 中进入 `sqlchat` 目录。

复制环境配置模板：

```powershell
Copy-Item .env.example .env
```

编辑 `.env`，为 `POSTGRES_PASSWORD` 和 `RABBITMQ_DEFAULT_PASS` 分别设置不同的随机密码，并将 `SQLCHAT_BOOTSTRAP_PASSWORD` 改为初始管理员密码。可以在 PowerShell 中运行以下命令生成密码（重复运行以获得不同值）：

```powershell
$rng = [Security.Cryptography.RandomNumberGenerator]::Create(); $bytes = New-Object byte[] 24; $rng.GetBytes($bytes); [Convert]::ToBase64String($bytes).Replace('+','-').Replace('/','_')
```

将 `SQLCHAT_ENCRYPT_KEY` 替换为恰好 32 个 UTF-8 字节的随机值；下面的命令会生成 32 个十六进制字符：

```powershell
$rng = [Security.Cryptography.RandomNumberGenerator]::Create(); $bytes = New-Object byte[] 16; $rng.GetBytes($bytes); [BitConverter]::ToString($bytes).Replace('-','').ToLowerInvariant()
```

本地使用建议将 `SQLCHAT_STORAGE_BACKEND` 设为 `local`。如需使用模型功能，可按所用服务配置 `SQLCHAT_DEFAULT_MODEL_API_KEY`。本地 Compose 启动不会提供外部模型 API 或 OSS 服务。

启动 SQLChat：

```powershell
docker compose --env-file .env up -d --build
```

Compose 会自动运行数据库迁移服务，然后启动 API、Worker 和前端。默认访问地址为 <http://localhost:8109/admin/chat>。登录用户名和密码分别取自 `.env` 中的 `SQLCHAT_BOOTSTRAP_USERNAME` 与 `SQLCHAT_BOOTSTRAP_PASSWORD`；模板默认用户名为 `admin`，密码应由部署者设置。

停止服务并保留命名卷中的数据：

```powershell
docker compose --env-file .env down
```

## 试用博客演示库（MySQL v2）

内置十表博客演示库使用虚构数据，仅 readonly 账号具有 SELECT / SHOW VIEW 权限。根 Compose 通过 `trial-demo` profile 启用，默认不启动演示库。在私有 `.env` 配置 `SQLCHAT_TRIAL_ENABLED=true`、`SQLCHAT_TRIAL_BUILTIN_HOST=sqlchat-demo-mysql`、端口 `3306`、`SQLCHAT_TRIAL_BUILTIN_DB_NAME=sqlchat_blog_demo`、非 root 用户与独立口令，并设置 `COMPOSE_PROFILES=trial-demo`，确保以后普通根 Compose 启动也包含演示服务；或每次明确传 `--profile trial-demo`。演示库不公开宿主机端口。

已有本地演示环境先审阅 `deploy/trial-mysql/upgrade-local-env.py`，默认仅列出拟修改的白名单键，`--apply` 才写私有 `.env`，不会打印口令。旧 standalone 如与网络别名冲突，先核对精确容器后停止并断开其网络，保留旧容器和卷。旧用户自建数据源不自动更新，后续请选择内置演示源。

```powershell
docker compose --env-file .env --profile trial-demo up -d --build
```

本地与生产均挂载新逻辑卷 `trial_mysql_blog_v2_data`（实际卷名带 project 前缀），旧卷保留。MySQL 初始化仅在空卷运行；修改 seed/init 不会让既有卷重新执行。已有 builtin 的连接目标变化时递增版本、清除旧 schema 并后台重验，无变化不刷新。服务器部署会同步 schema、seed 和健康检查全部资产。详情与只读验收入口见 [C 实施验收](docs/chat-schema-repair/C-实施验收.md)。
