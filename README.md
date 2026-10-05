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
