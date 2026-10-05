# S16：GitHub Actions → GHCR → ECS 部署操作指南

本指南适用于当前 SQLChat 源代码方案。镜像由 GitHub Actions 构建，ECS 只拉取镜像并运行服务；本文不代表已在真实 ECS 上完成部署或验证。当前本地五个常驻容器约占 550 MB，不能据此推算服务器峰值内存。

## 1. 固定部署契约

| 项目 | 约定 |
| --- | --- |
| 仓库 | 当前 SQLChat 源码所在 GitHub 仓库；部署前确认 owner `P-Jhao`、仓库名与部署分支 `main` |
| 后端镜像 | `ghcr.io/p-jhao/sqlchat-backend:<完整提交 SHA>` |
| 前端镜像 | `ghcr.io/p-jhao/sqlchat-frontend:<完整提交 SHA>` |
| 平台 | `linux/amd64`，先确认 ECS 为 x86_64 |
| 服务器目录 | `~/sqlchat-deploy`，相对 SSH 部署账户的家目录 |
| Compose | `~/sqlchat-deploy/docker-compose.prod.yml`，不含 `build` |
| 配置 | `~/sqlchat-deploy/.env.production`，权限 `600` |
| 更新入口 | `~/sqlchat-deploy/deploy-on-server.sh <完整提交 SHA>` |
| Compose 项目 | 固定 `sqlchat-prod`，避免更新时创建另一套数据卷 |
| HTTP 入口 | 前端 `127.0.0.1:${SQLCHAT_HTTP_PORT}:80`，默认宿主机端口 `18109` |
| 现有反向代理 | 容器 `promptforge-nginx-1`，外部网络 `promptforge_promptforge` |
| 代理 upstream | 前端在外部网络中的别名 `sqlchat-frontend`，地址 `http://sqlchat-frontend:80` |

API 的 `8109` 只在容器网络中使用；数据库和 RabbitMQ 不开放宿主机端口。公网流量通过现有 Nginx 的 80/443 进入前端，前端再代理 `/api`。默认常驻服务是 PostgreSQL、RabbitMQ、API、Worker 和前端；本机体验模式另加受限的私有 MySQL；迁移与指标初始化属于一次性服务。

本机项目根目录的 `docker-compose.yml` 用于源码构建。云部署使用 `deploy/docker-compose.prod.yml`，不要在 2 GB ECS 上执行源码构建。只运行一个 API 和一个 Worker 容器，不使用 `--scale`。

## 2. 服务器准备与容量检查

先确认仓库 owner、部署分支和 ECS 架构。现有 Nginx 已确认运行在容器 `promptforge-nginx-1`，复用网络 `promptforge_promptforge`；SQLChat 拟用域名为 `db-genius.pjhao.xyz`，现有 Nginx 配置挂载位置仍需核对。检查已有应用的内存、磁盘和端口占用：

```bash
uname -m
free -h
df -h
docker version
docker compose version
docker ps --format 'table {{.Names}}\t{{.Ports}}\t{{.Status}}'
docker stats --no-stream
ss -ltnp
```

默认 `18109` 必须未被占用，否则在 `.env.production` 中选另一个未占用端口。2 GB 内存还要容纳现有应用、系统、迁移、后台任务和模型请求；上线后观察实际峰值，再决定是否调整服务 limits、任务并发或升级规格。不要直接按本地 550 MB 给服务设置内存上限。

安全组与宿主机防火墙允许公网 HTTP 80、HTTPS 443，以及部署账户所用 SSH 端口。不要开放 18109、8109、5432 或 5672。服务器需要能够访问 GHCR、镜像源、模型服务和所配置的 OSS endpoint。

安装并确认 Docker Engine、Compose v2 和 `python3` 可用。部署账户需要 Docker 权限；加入 `docker` 组后重新登录再检查 `docker info`。Docker 组有管理宿主机容器与挂载的权限，应使用专门部署账户保管 SSH 密钥。`python3` 仅运行无第三方依赖的部署配置校验器，不在 ECS 上安装后端 Python 依赖。

在服务器上创建目录：

```bash
mkdir -p ~/sqlchat-deploy
chmod 700 ~/sqlchat-deploy
```

从当前项目上传安全模板；本地 PowerShell 示例中的主机和账户均需替换：

```powershell
scp .\deploy\.env.production.example deploy@YOUR_ECS_HOST:sqlchat-deploy/.env.production
```

随后在服务器编辑配置，不能把真实配置提交到 Git：

```bash
chmod 600 ~/sqlchat-deploy/.env.production
nano ~/sqlchat-deploy/.env.production
```

替换所有占位值，至少配置 PostgreSQL 密码、RabbitMQ 密码、管理员初始密码和 `SQLCHAT_ENCRYPT_KEY`。加密密钥必须是 32 个 ASCII 字符，可在可信本地环境用 `python -c "import secrets; print(secrets.token_hex(16))"` 生成。保持该密钥稳定，并与数据库备份一起保管，否则已保存的数据源及模型密钥无法解密。

设置 `SQLCHAT_HTTP_PORT=18109`（或已确认空闲的端口）。模型功能需要 `SQLCHAT_DEFAULT_MODEL_API_KEY`，或登录后配置用户模型。仅上传 Excel 不需要 OCR，保持 `SQLCHAT_OCR_ENABLED=false`。使用 OSS 时，云端必须配置 bucket、endpoint、访问凭据与相应权限；OSS 不会自动回退成本地存储。若明确选择本地存储，设置 `SQLCHAT_STORAGE_BACKEND=local` 并保留 `/app/uploads` 的持久化挂载。

## 3. SSH 与 GitHub 配置

为 GitHub Actions 创建专用 SSH 密钥，将公钥写入部署账户的 `~/.ssh/authorized_keys`，私钥放入 GitHub secret。确认 `.ssh` 权限为 `700`、`authorized_keys` 为 `600`，并从本地实测部署账户可以 SSH 登录和执行 Docker。

从可信终端核验 ECS SSH 主机指纹，再保存对应 known_hosts 条目。`ssh-keyscan` 只能采集密钥，不能独立证明其可信；应与云控制台或已可信连接中取得的指纹核对。非标准端口的 known_hosts 条目应使用 `[host]:port` 格式，不关闭主机密钥检查。

在 GitHub 仓库 Settings → Secrets and variables → Actions 中添加：

| 类型 | 名称 | 值 |
| --- | --- | --- |
| Secret | `SQLCHAT_ECS_HOST` | ECS 公网 IP 或 SSH 域名 |
| Secret | `SQLCHAT_ECS_USER` | 具有 Docker 权限的部署账户 |
| Secret | `SQLCHAT_ECS_SSH_PRIVATE_KEY` | 专用 SSH 私钥完整内容 |
| Secret | `SQLCHAT_ECS_KNOWN_HOSTS` | 已核验的 SSH known_hosts 条目 |
| Variable | `SQLCHAT_ECS_SSH_PORT` | 非标准 SSH 端口；不设置则使用 `22` |

服务器 `.env.production` 不上传 GitHub，也不放入前端构建参数。workflow 使用 GitHub token 推送 GHCR，并处理服务器拉取私有 package 时所需的 registry 登录；上述 SSH 配置不包含模型或 OSS 密钥。

首次运行前，确认仓库 Actions 已启用、workflow 有 `packages: write` 权限。若同名 GHCR package 已存在，在 package 设置中允许该仓库 Actions 访问；首次创建后也检查两个 package 的仓库关联及权限。若 owner 改变，必须同步更新 Compose 中的镜像路径与 workflow，不能只改 GitHub 仓库名称。

## 4. 首次发布

1. 完成服务器配置、SSH、GitHub secrets 和端口检查。
2. 将部署代码推送到确认的 `main` 分支，或在 Actions 页面手动运行对应部署 workflow。
3. Actions 在 runner 中使用 Buildx 构建 `linux/amd64` 的前后端镜像，以完整提交 SHA 推送 GHCR；然后经 SSH 上传部署文件并调用服务器脚本。
4. 查看 Actions 构建和部署日志，再在服务器检查容器健康与入口。

服务器常用命令：

```bash
cd ~/sqlchat-deploy
export SQLCHAT_IMAGE_TAG=FULL_40_CHARACTER_COMMIT_SHA
dc() { docker compose -p sqlchat-prod --env-file .env.production -f docker-compose.prod.yml "$@"; }
dc ps -a
dc logs --tail=100 migrate metrics-init api worker
curl --fail http://127.0.0.1:18109/api/health/ready
curl --fail --output /dev/null http://127.0.0.1:18109/
docker stats --no-stream
```

将 `FULL_40_CHARACTER_COMMIT_SHA` 替换为 Actions 本次发布的完整提交 SHA；手工 Compose 命令也需要该镜像标签。若配置了其他端口，替换 `curl` 中的 `18109`。`migrate` 与 `metrics-init` 正常状态是退出码 `0`，不应按常驻容器要求其持续运行。确认 API readiness、Worker health 和前端正常之后，再放通域名入口。

管理员尚未创建时，在服务器执行幂等初始化：

```bash
dc exec -T api python deploy/connection_env.py python -m app.services.bootstrap
```

通过页面使用配置的管理员账户登录，再检查模型配置与一次 Excel 上传/解析。健康检查只能确认运行依赖，不能代替真实模型、OSS 或业务操作验收。

## 5. 子域名、Nginx 和 HTTPS

当前拟用域名为 `db-genius.pjhao.xyz`。在 `pjhao.xyz` 的 DNS 控制台创建 A 记录，主机记录（host）为 `db-genius`，值为部署时 ECS 控制台显示的当前公网 IP。此前截图显示 `47.97.98.39`，部署前必须重新核对，不能直接把截图中的地址视为当前地址。完成 DNS、Nginx 配置及证书设置并验证之前，不宣称该域名已可线上访问。

生产 Compose 将前端加入已存在的外部网络 `promptforge_promptforge`，并设置网络别名 `sqlchat-frontend`；现有代理容器 `promptforge-nginx-1` 通过 `http://sqlchat-frontend:80` 访问前端。部署脚本会在停止 SQLChat 服务之前检查该网络存在，检查失败则退出；不要创建同名空网络绕过检查。

用户服务器已核实的证书配置如下：现有 Let's Encrypt lineage 为 `promptforge.pjhao.xyz`，SAN 当前仅包含该域名；续期使用 webroot `/opt/promptforge/deploy/nginx/www`，宿主机 `certbot.timer` 为 active。已有 deploy hook `/etc/letsencrypt/renewal-hooks/deploy/promptforge-deploy.sh` 将 lineage 的 fullchain/privkey 复制到 `/opt/promptforge/deploy/nginx/certs/{fullchain,privkey}.pem`，再执行 `docker compose up -d --no-build --force-recreate nginx`。

Nginx 配置应修改 PromptForge 源仓库中的 `https.conf`，并通过该仓库的 Actions 重新构建部署，不直接编辑运行中容器。需要复核挂载和当前域名时，可运行以下只读命令，分享输出前可遮蔽域名：

```bash
docker inspect --format '{{range .Mounts}}{{println .Source "->" .Destination}}{{end}}' promptforge-nginx-1
docker exec promptforge-nginx-1 nginx -T 2>/dev/null | grep -E 'server_name|listen'
```

先在现有 HTTP server 的 `server_name` 中保留旧域名并加入新域名：`server_name promptforge.pjhao.xyz db-genius.pjhao.xyz;`，保留原有 `/.well-known/acme-challenge/` 的 webroot 服务位置，其余 HTTP 请求按现有方案跳转 HTTPS。该 HTTP 配置通过 PromptForge Actions 部署且两个域名 80 端口可达后，再扩展证书。

确认新域名 A 记录指向部署时 ECS 当前公网 IP，并确保旧域名仍正确解析；两域名均须通过公网 80 访问对应 webroot。然后在服务器执行：

```bash
sudo certbot certonly --webroot \
  --webroot-path /opt/promptforge/deploy/nginx/www \
  --cert-name promptforge.pjhao.xyz --expand \
  -d promptforge.pjhao.xyz -d db-genius.pjhao.xyz
```

`--cert-name` 指定现有 lineage，`--expand` 要求保留全部旧域名并加入新域名，因此命令同时列出两个 `-d`；参见 [Certbot 官方证书扩展说明](https://eff-certbot.readthedocs.io/en/stable/using.html#re-creating-and-updating-existing-certificates)。此命令获取证书，不会替你生成 Nginx server 配置。

扩展后检查 lineage SAN 与挂载证书副本 SAN，并确认 fullchain 副本一致；私钥由已有 deploy hook 负责复制，以下命令不读取私钥：

```bash
sudo openssl x509 -in /etc/letsencrypt/live/promptforge.pjhao.xyz/fullchain.pem -noout -ext subjectAltName
sudo openssl x509 -in /opt/promptforge/deploy/nginx/certs/fullchain.pem -noout -ext subjectAltName
sudo cmp /etc/letsencrypt/live/promptforge.pjhao.xyz/fullchain.pem /opt/promptforge/deploy/nginx/certs/fullchain.pem
```

若扩展成功而既有 hook 未自动执行、副本未更新，手动运行已有 hook，再重复以上验证：

```bash
sudo env RENEWED_LINEAGE=/etc/letsencrypt/live/promptforge.pjhao.xyz \
  RENEWED_DOMAINS='promptforge.pjhao.xyz db-genius.pjhao.xyz' \
  bash /etc/letsencrypt/renewal-hooks/deploy/promptforge-deploy.sh
```

hook 会重建现有 Nginx，PromptForge 与 SQLChat 的入口都会短暂中断，应安排合适操作窗口。复用现有 lineage 与 timer，不新增一套证书复制或续期任务。

在 PromptForge `https.conf` 中保留原有 PromptForge 443 server，新增如下 SQLChat 443 server。已确认宿主机证书目录挂载到 `/etc/nginx/certs`；新 server 复用现有容器内证书路径：

```nginx
server {
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name db-genius.pjhao.xyz;
    ssl_certificate /etc/nginx/certs/fullchain.pem;
    ssl_certificate_key /etc/nginx/certs/privkey.pem;
    client_max_body_size 21m;
    resolver 127.0.0.11 valid=10s;

    location / {
        set $sqlchat_upstream sqlchat-frontend;
        proxy_pass http://$sqlchat_upstream:80;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;
        proxy_request_buffering off;
        proxy_cache off;
        proxy_connect_timeout 10s;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }
}
```

首次启动 SQLChat 前端后，确认它与代理都在 `promptforge_promptforge` 网络中，别名 `sqlchat-frontend` 才能通过容器内 Docker DNS 解析。示例用 `127.0.0.11` 动态解析 upstream，DNS 缓存有效期为 10 秒；前端容器更新重建、IP 变化后，代理会重新解析该别名。初次服务尚未就绪或 DNS 缓存刷新期间，请求可能短暂返回 502；SSE 的禁用缓冲与长超时参数保留。

完整配置通过 PromptForge Actions 重新构建部署。部署后执行 `docker exec promptforge-nginx-1 nginx -t`，并通过 `https://db-genius.pjhao.xyz` 检查证书域名、登录、文件上传和 SSE 响应；同时确认旧域名仍可用。任何 DNS、证书或配置步骤未完成时，均不能宣称新域名已上线。

代理容器内的 `127.0.0.1` 指向代理自身，因此不要把 upstream 写成 `127.0.0.1:18109`。宿主机 loopback 端口继续用于本机检查，生产域名使用上述共享网络和别名。网络成员关系已落在生产 Compose 中，前端重建后仍会重新加入；不要依赖临时 `docker network connect`。

## 6. 后续更新与备份

已初始化的现有实例升级时，保持 `POSTGRES_PASSWORD`、`RABBITMQ_DEFAULT_PASS` 和 `SQLCHAT_ENCRYPT_KEY` 三者不变。修改 env 中的数据库或 RabbitMQ 密码不会自动轮换持久化实例中已有账号的密码，可能导致 API/Worker 连接失败；改变加密密钥会使既有数据源和模型等加密数据无法解密。需要变更凭据时，应执行明确的数据库或服务侧密码轮换，同步应用配置，并验证连接及业务功能；加密密钥轮换还需要明确的数据重加密方案，不能通过编辑 env 完成。

更新前先将 PostgreSQL 备份保存到部署目录之外，并另存加密密钥。以下命令沿用上文 `dc` 函数：

```bash
mkdir -p ~/sqlchat-backups
chmod 700 ~/sqlchat-backups
umask 077
backup_file="$HOME/sqlchat-backups/sqlchat-$(date -u +%Y%m%dT%H%M%SZ).dump"
dc exec -T postgres sh -c 'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$backup_file"
test -s "$backup_file"
dc exec -T postgres pg_restore --list < "$backup_file" > /dev/null
```

目录检查只说明备份可读取；应定期在隔离数据库演练恢复。若要求严格一致的发布恢复点，先暂停业务写入与后台任务再备份。备份 `.env.production` 时必须保密；至少保存原始 `SQLCHAT_ENCRYPT_KEY`，不要把密钥写入公共日志。

部署脚本保存的 env 快照只是当时的配置文件，不证明其中密码与持久化数据库、RabbitMQ 的真实账号密码一致，也不证明其中密钥能够解密该份数据库备份。只有快照配置与恢复实例当前真实凭据及该备份所用加密密钥匹配时，才能作为恢复配置使用；升级前应确认这种匹配关系，并通过恢复演练验证，不能把文件快照成功当作凭据轮换或恢复成功。

固定项目名对应 `sqlchat-prod_postgres_data`、`sqlchat-prod_rabbitmq_data`、`sqlchat-prod_uploads_data` 和 `sqlchat-prod_metrics_multiprocess_data` 四个卷。除数据库导出外，还应安排 RabbitMQ 和本地上传卷的备份；需要一致性时停服务后按卷备份方案操作。使用 OSS 则单独配置 bucket 备份/版本策略。指标卷不替代业务备份。

推送新提交后由 Actions 发布对应 SHA。脚本先拉取镜像，更新时停止 API/Worker 并移除已完成的 `metrics-init` 容器，然后无构建启动服务、运行迁移和新指标周期，检查 readiness。更新有短暂不可用窗口，四个持久化卷继续保留。

需要在服务器手动重试时，先确认目标 SHA 的两个镜像已推送且当前 registry 登录可拉取私有 package：

```bash
cd ~/sqlchat-deploy
bash ./deploy-on-server.sh FULL_40_CHARACTER_COMMIT_SHA
```

自动部署结束后的 registry 凭据是否仍可用取决于 workflow 的清理与 token 生命周期；不能把一次成功登录视为长期授权。手动拉取可用具有 `read:packages` 的凭据通过 `docker login ghcr.io --password-stdin`，不把 token 写在命令行。

不要执行 `docker compose down -v`、`down --volumes` 或 `docker system prune`。临时停机用 `dc stop`。镜像 SHA 回退不自动回退数据库 schema；迁移不兼容时应停止受影响服务，并按原版本及匹配备份恢复，避免直接在新 schema 上启动旧镜像。

## 7. 排查顺序

```bash
cd ~/sqlchat-deploy
export SQLCHAT_IMAGE_TAG=FULL_40_CHARACTER_COMMIT_SHA
dc() { docker compose -p sqlchat-prod --env-file .env.production -f docker-compose.prod.yml "$@"; }
dc config --quiet
dc ps -a
dc logs --tail=150 postgres rabbitmq migrate metrics-init api worker frontend
curl --fail http://127.0.0.1:18109/api/health/ready
free -h
df -h
docker stats --no-stream
```

- SSH 失败：核对四个 secrets、端口变量、authorized_keys、主机指纹和安全组；不关闭 known_hosts 校验。
- GHCR pull denied：核对镜像 SHA 是否已发布、package 是否关联仓库及允许 Actions 访问、registry token 是否有效。
- 启动失败：先看 PostgreSQL/RabbitMQ 健康，再看迁移退出码；不要通过删除数据卷解决。
- `metrics-init` 报锁占用：确认 API 和 Worker 都已停止，再由部署脚本重试；运行中的进程不允许清空指标文件。
- API readiness 503：检查数据库与 broker；模型/OSS 失败需另查业务日志与配置。
- 域名 502 而 loopback 正常：核对 Nginx 所在位置、upstream、网络、配置加载和 HTTPS server。
- Excel 上传失败：核对 OSS 或 local 配置、外层 21 MiB 上传限制、Worker 状态；Excel-only 不需要开启 OCR。
- 容器异常退出：结合内存、磁盘与日志检查 OOM/容量问题，再调整资源；不推测本地内存数字等于 ECS 峰值。

收集排查材料时避免分享完整 `.env.production`、Compose 展开的环境变量、私钥或含凭据的日志。通过真实服务器首发、模型调用和文件链路检查后，再记录该服务器的部署验收结果。

## 8. 在同一台 ECS 启用轻量体验数据库

本机体验库使用 MySQL 8.4，提供虚构的电商数据：6 位客户、6 件商品、10 笔订单和 15 条订单明细，四张表带字段说明和外键。可以尝试“按城市统计成交订单总金额，排除取消订单”“销量最高的商品有哪些”“杭州客户最近的订单有哪些”。日期固定为 2025 年 4–6 月，避免把“最近一个月没有订单”误判为数据库故障。

数据库仅加入 SQLChat 的 `backend` Docker 网络，服务名为 `trial-mysql`，不映射宿主机端口；API 和 Worker 均可连接。`sqlchat_demo` 应用账号只有对应示例库的 `SELECT, SHOW VIEW` 权限，不能插入、修改、删除、建表。root 凭据只传给 MySQL 容器，不传给 API/Worker，root 限定 localhost。OCR 可保持关闭，本地文件存储或现有 OSS 配置继续使用。

**本次约束：256 MiB 数据库内存硬上限、memory+swap 同额（数据库不使用 swap）、0.5 CPU；InnoDB buffer pool 32 MiB、日志 buffer 8 MiB、12 个连接、4 MiB 临时表，关闭 Performance Schema 和 binlog，并跳过时区表导入。** 256 MiB 是容器限制，不是已验证的 MySQL 峰值或可用保证。本机 Docker 引擎未运行，尚未冷启动实测此上限；真实 ECS 启动与查询必须观察健康状态和 OOM。用户提供的服务器可用内存约 410 MiB，数据库打满限制后只余约 154 MiB，其他应用并发峰值仍可能使宿主机内存不足。此配置仅用于低流量小数据演示；swap 不能替代足够的物理内存。初始化行为依据 [Docker 官方 MySQL entrypoint](https://github.com/docker-library/mysql/blob/master/8.4/docker-entrypoint.sh)，真实数据库运行仍需验证。

在 ECS 生成两份独立密码，每次复制结果仅到服务器 env，不分享终端中的密码输出：

```bash
openssl rand -hex 24
openssl rand -hex 24
nano ~/sqlchat-deploy/.env.production
```

保留已有 PostgreSQL、RabbitMQ、加密密钥、管理员和模型配置，只添加/替换以下项目（将两个占位值分别换成上面两次生成的结果）：

```dotenv
SQLCHAT_TRIAL_ENABLED=true
SQLCHAT_TRIAL_MYSQL_ROOT_PASSWORD=REPLACE_WITH_FIRST_HEX_PASSWORD
SQLCHAT_TRIAL_BUILTIN_DB_NAME=db-genius
SQLCHAT_TRIAL_BUILTIN_HOST=trial-mysql
SQLCHAT_TRIAL_BUILTIN_PORT=3306
SQLCHAT_TRIAL_BUILTIN_USERNAME=sqlchat_demo
SQLCHAT_TRIAL_BUILTIN_PASSWORD=REPLACE_WITH_SECOND_HEX_PASSWORD
```

部署文件必须包含本次新增的 `trial-mode.py`、`docker-compose.trial.yml` 和 `trial-mysql/{10-demo.sh,demo.sql}`。将这版改动提交并推送 `main` 后，Actions 自动传输全部文件并重新部署；也可手动运行包含这些文件的最新版本 workflow。仅重新运行旧提交 workflow 不会添加 MySQL。服务器无需安装 MySQL 或编译依赖，无需修改 Nginx、证书或开放 3306。

部署脚本通过 Compose 解析后的 JSON 严格验证 `SQLCHAT_TRIAL_ENABLED=true/false`，不执行或 source `.env.production`。`true` 且 host 为 `trial-mysql` 时启用 `trial-demo` profile，并加载健康依赖覆盖文件：**先在当前应用仍运行时启动受限 MySQL，确认只读账号可查到 10 笔订单，再进入停应用的维护窗口并更新 API/Worker**。MySQL 启动/健康失败时退出，旧 frontend/API/Worker 未被部署脚本停止；若本次首次新建的 demo 失败，会停止它释放内存并保留卷。已有 demo 失败不由此前置步骤停止，应检查原状态。迁移、指标、应用健康门禁继续生效；首次安装管理员 bootstrap 后再次幂等初始化内置数据源，避免 API 首次启动时管理员尚不存在而跳过。此后 Worker 执行连接验证和元数据提取；页面应显示内置数据库且验证成功。若已有 builtin 数据源，现有初始化器会保留它，编辑 env 不会自动改掉数据库中保存的旧内置连接，需先检查既有配置而非删除数据卷。

服务失败时部署脚本会退出并保留所有卷；不要反复提高上限或删除卷。先检查 MySQL 状态/OOM 与日志，再决定缩减并发或扩容。首次数据初始化中断可能留下非空且不完整的数据目录，官方初始化脚本不会在非空卷重新执行；保留原卷并诊断，不能用重复部署冒充已恢复。

部署后的只读检查：

```bash
cd ~/sqlchat-deploy
export SQLCHAT_IMAGE_TAG="$(cat .deployed-image-tag)"
dct() { docker compose -p sqlchat-prod --env-file .env.production -f docker-compose.prod.yml -f docker-compose.trial.yml --profile trial-demo "$@"; }
dct ps -a
dct logs --tail=80 trial-mysql
dct exec -T trial-mysql sh -c 'MYSQL_PWD="$TRIAL_PASSWORD" mysql -h 127.0.0.1 -u "$TRIAL_USERNAME" -D "$TRIAL_DATABASE" -e "SELECT COUNT(*) FROM orders; SHOW GRANTS;"'
free -h
docker stats --no-stream
docker inspect --format '{{.State.OOMKilled}} {{.HostConfig.Memory}} {{.HostConfig.MemorySwap}}' sqlchat-prod-trial-mysql-1
```

订单数应为 10，授权应限于示例库的 SELECT/SHOW VIEW（另有全局 USAGE，仅表示账号存在，不授予读写权限），MySQL 健康且 `OOMKilled=false`。进一步从网页提问并检查真实查询结果。观察多用户查询和文件任务时的峰值；频繁重启、OOM 或宿主机持续 swap 时暂停演示库并处理容量。若 .deployed-image-tag 因部署失败尚不存在，手工指定本次 Action 的完整 SHA 后诊断。

数据卷为 `sqlchat-prod_trial_mysql_data`，种子与账号只在首次空卷初始化时创建。以后修改 SQL 文件、数据库名、用户名或 env 密码不会自动重新导入/改密，升级应保留配置；需要变更账号或数据时执行明确的数据库迁移/凭据轮换，再更新 env。不要用 `down -v`、`docker volume rm` 或 `prune` 清理它。

可将示例库备份到私有目录（沿用上面的 `dct`）：

```bash
mkdir -p ~/sqlchat-backups
chmod 700 ~/sqlchat-backups
umask 077
dct exec -T trial-mysql sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysqldump -u root --single-transaction --databases "$TRIAL_DATABASE"' \
  > "$HOME/sqlchat-backups/trial-mysql-$(date -u +%Y%m%dT%H%M%SZ).sql"
```

数据库导出不包括应用账号；恢复时另行保管原始服务器 env、恢复账号与只读授权，或者离线备份整个 MySQL 卷。备份成功应通过隔离环境恢复演练验证。

关闭体验模式时将 `SQLCHAT_TRIAL_ENABLED=false` 并重新部署。脚本会停止 demo MySQL 容器（不删除卷），不会让 profile 容器继续常驻耗内存；再次打开会复用原卷。也可将体验连接改成完整的外部 MySQL 参数，脚本不启动本机 MySQL。手动停止/回退体验库时，应同步关闭体验模式并重建 API/Worker，否则页面仍会引用已停止的数据库。
