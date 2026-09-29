# S00 迁移草稿审计

状态：2026-09-29，只读审计完成；本提交保存未完成草稿，不代表功能验收通过。

依据：工作区 `spec/` 的产品、接口、Agent、验收和执行规格；原 `db-genius` 只读。

## 前端逐项处置

- **保留**：`frontend/src` 的 104 个原源码文件和 `public` 的 40 个原静态资源均已复制；Vue 3/Vite/Arco 结构、pnpm 锁文件、Markdown 的 DOMPurify 清理、聊天 SSE 的 HTTP 状态和 Content-Type 检查。
- **修正**：`src/api/chat.ts` 的流结束/错误回调，`src/composables/useSse.ts` 的正常 EOF 收敛，`src/stores/chat.ts` 的终态与事件类型，`src/types/index.ts` 的事件联合类型和实际 VO 契约。
- **修正**：`DbConfigPage.vue`、`ModelConfigPage.vue`、`MessageBubble.vue` 中从原项目复制的 `any` 类型；`vite.config.ts`、`nginx.conf`、README 的后端端口与 `/api` 代理配置。
- **修正**：前端 Docker 构建上下文须排除本地 `.env`；销售联系及不适用于新部署方的旧域名/备案/合作文案逐项核实。保留原视觉和通用品牌素材，不做无关重设计。
- **验证**：`pnpm build` 已通过；尚无端到端用例或后端联调。构建发出 `__dirname` 兼容性和主 bundle 体积提示，后续按实际风险处理。
- **历史文件**：`backend-fix-context-loss.md` 为原项目历史参考，不作为 Python 版当前实现证明。

## 后端逐文件处置

| 文件 | 处置 | 已知问题/可复用内容 |
|---|---|---|
| `app/core/config.py` | 修正 | 可保留 BaseSettings；会话、SQL 超时、行数、各 Agent 步数与原默认不符 |
| `app/core/database.py` | 修正 | 保留 Base/session 和系统库 app schema；bootstrap 引用不存在；改由 Alembic 管迁移 |
| `app/core/errors.py` | 重写 | `BusinessError` 要求整数码，但 Agent 草稿传字符串码；本地化/HTTP 包装未对齐 |
| `app/core/security.py` | 修正 | bcrypt、token 摘要、AES-GCM 布局可保留；旧密文兼容和异常路径需测试 |
| `app/models/entities.py` | 修正并拆分 | 七张原业务表基本覆盖；整型容量、会话活跃期限、验证版本、可空字段未对齐 |
| `app/models/__init__.py` | 保留并维护 | 导出实体，随模型拆分调整 |
| `app/main.py` | 重写装配 | 引入缺失的 `app.api` 六个模块，当前无法导入启动 |
| `pyproject.toml` | 修正 | 依赖职责基本齐；缺 uv.lock 与已验证的版本组合 |
| `backend/Dockerfile` | 修正 | 8000 端口与 8109 规格冲突；缺可复现锁安装和 Worker 配套 |
| `app/agent/types.py` | 保留并修正 | 有输入/用量雏形；GraphState、终态、幂等与验证不足 |
| `app/agent/model.py` | 部分保留、协议重做 | SSE 框架可用；URL、分片工具调用、usage、错误/取消未充分处理 |
| `app/agent/streaming.py` | 保留思路并修正 | 增量聚合可用；取消/终态/用量和 reasoning 配对需补 |
| `app/agent/prompts.py` | 重写 | 当前简化英文提示丢失原中英文业务规则和工具约束 |
| `app/agent/tools.py` | 保留权限方向并重做 | 选择资源集合思路可用；工具名/参数、结构化截断、制品边界不兼容 |
| `app/services/chat_store.py` | 保留基础并修正 | 有归属检查/序列化；会话创建、上下文筛选、压缩、中止及用量需对齐 |

## 尚缺能力

缺 API 路由、schema DTO、业务服务、目标库适配器、Celery 任务、Alembic、真实 LangGraph 状态图、SSE 端点、分类器、上下文压缩、循环保护、后端测试、后端锁文件、Compose、前端端到端测试。任何一项不能因为存在依赖声明而视作已实现。

## 固定契约与后续门槛

- `app/main.py`、数据库模型、`pyproject.toml` 归系统/数据库子代理所有；Agent 子代理拥有 `app/agent`、聊天 API/服务；前端/交付子代理拥有 `frontend` 和部署文档。
- REST 对外使用 `/api`、camelCase 和 `{code,message,data}`；聊天保持 POST SSE。业务码为整数，语言文案在 API 边界解析。权限在 API 和工具层复核。
- 原会话总/活跃期限 86400/3600 秒；SQL 超时 30 秒、结果最多 100 行；SQL/工作流/对比步数 10/20/15。不能沿用草稿的 30 天/60 秒/1000 行/单一 20 步。
- 原前端改动以兼容、缺陷和销售移除为界。S01 必须先修正 Docker 密钥上下文和端口，再尝试构建镜像。
- S01 验收：前后端可安装/导入/构建，契约测试通过；S02 起使用真实 PostgreSQL，S04 使用真实 MySQL/PostgreSQL。外部模型和 OSS/OCR 的模拟/真实验证分列。

草稿基线提交为 `d985074`，仅提供恢复点；后续通过每个小阶段的测试后再用独立中文规范提交标记完成。
