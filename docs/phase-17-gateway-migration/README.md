# Phase 17：独立 Gateway 迁移

## 目标结构

独立 Gateway 项目负责公网 80/443 和域名转发。SQLChat 只将 frontend 接入外部 Docker 网络 `gateway_proxy`，并注册网络别名 `sqlchat-frontend`；Gateway 通过 `sqlchat-frontend:80` 转发 `db-genius.pjhao.xyz`。SQLChat 后端、数据库和 RabbitMQ 不加入 Gateway 网络。

旧的 `promptforge_promptforge` 网络不再是 SQLChat 生产 Compose 的依赖。

## 部署顺序

1. 先部署独立 Gateway。Gateway 部署脚本会在网络不存在时创建 `gateway_proxy`，并管理公网入口。确认 Gateway 已占用 80/443，且用于 `db-genius.pjhao.xyz` 的 TLS 证书有效。
2. 部署 PromptForge 的新 Compose，使其 backend/frontend 加入 `gateway_proxy` 并提供 Gateway 所需的网络别名。
3. 再运行 SQLChat 仓库的 GitHub Actions 部署。SQLChat 部署脚本会先检查 `gateway_proxy`；若网络不可用，会在停止 SQLChat 应用服务前退出。

Gateway 切换公网入口后、应用加入 `gateway_proxy` 前，相关域名可能暂时无法访问；应用部署完成后再检查实际路由。

## 数据与当前状态

这次网络切换不修改 SQLChat 的数据库、RabbitMQ、上传文件或指标卷定义，不迁移或删除现有数据卷。后续部署继续使用 Compose 中原有卷名。

编写本说明时只更新了本地配置和文档，尚未访问或修改云服务器。云服务器迁移是否完成，以 Gateway、PromptForge 和 SQLChat 的部署流程依次成功并检查线上路由为准。
