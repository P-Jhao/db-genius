# S09 前端压缩事件与回放

本阶段只切入上下文相关变更：SseStepCard 对 context_compact 做契约校验，按 phase/tier/message 和可选 Token/affectedUnits 展示；七语言加入对应字段文案。非法结构显式抛错。已有压缩 API、用量栏、类型和聊天 store 保持 S08 基线；上传契约、其他 SSE 对象对齐及试用留在后续阶段。

ConversationsPage 仅新增 assistant compressed 原文回放分支，旧答案与 step=-2 新摘要同时可见；不会再次发起聊天 POST。

`node --test tests/s09-context.test.mjs` 实际浏览器验证七语言、start/end 字段、非法压缩对象、原文和新摘要回放、无重复 POST。测试明确设置 VITE_API_BASE_URL=/api；对 .git/acceptance 下的副本，临时 Vite 配置仅放行 frontend，仍拒绝 .env、私钥及 npm 配置文件，结束后删除。产品 vite.config.ts 未改。

pnpm 冻结安装和生产构建结果、浏览器结果见 `../phase-09-acceptance/README.md`。Vite 现有 __dirname 和大 chunk 提示继续存在。浏览器使用模拟 API/SSE，不等同于真实后端或模型效果验收。
