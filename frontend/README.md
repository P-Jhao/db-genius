# SQLChat 前端

从本地 DB-Genius Vue 3 前端复用，保留七语言官网和管理界面，去除销售联系宣传。使用 pnpm。

```sh
pnpm install --frozen-lockfile
pnpm dev
pnpm typecheck
pnpm build
```

默认 /api 经 Vite 转发至 http://127.0.0.1:8000；生产 Nginx 转发至 api:8000。环境模板见 .env.example。后端和完整部署说明见 ../README.md。

历史 scripts/shots 与 SEO 资源仍保留原项目品牌及域名，用于追溯原界面；上线到新域名前需要配置相应 SEO 信息。backend-fix-context-loss.md 是复制的原 Java 阶段历史说明，不作为当前 Python 实现依据。
