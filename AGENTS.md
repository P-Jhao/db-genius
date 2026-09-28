# SQLChat

## 功能边界
复用 DB-Genius 的 Vue 3 界面，Python/FastAPI 提供兼容 API；LangChain 与 LangGraph 实现模型、工具与会话流程。包含登录、数据源、模型、文件、对话、结构比较与试用模式；不包含销售联系功能。

## 目录
- frontend：Vue 3 / Vite / TypeScript / Arco Design 原界面与 API 客户端。
- backend/app/api：兼容原 Java 接口的 HTTP / SSE 路由。
- backend/app/core、models、services：配置、鉴权、持久化及领域服务。
- backend/app/agent：LangChain 模型和 LangGraph 工作流。
- backend/app/tasks：Celery 后台任务。
- docs：架构、运行和阶段交接文档。
- docker-compose.yml：PostgreSQL、RabbitMQ、API、Worker、前端部署。

## 开发约束
前端使用 pnpm；新增 Vue 功能使用 Composition API、script setup 和明确 TypeScript 类型，禁止 any。新增模块原则上不超过 300 行；历史复制的大组件逐步按业务边界拆分。开发优先交给子代理，明确禁止子代理继续派生。错误显式抛出；不得写入真实密钥。每次修改检查本文件，仅功能边界或核心目录变化时更新，细节写 docs。
