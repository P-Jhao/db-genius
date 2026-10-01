# S13 frontend Stop 修复冻结

## 当前状态

Stop 指示器残留已定位到 Pinia 响应式引用：`addAssistantMessage()` 返回的对象不是组件读取的 reactive proxy。取消时改用 `chatStore.messages` 中相同 ID 的消息引用，因此 `streaming = false` 会触发界面更新。若 store 未加入该消息，显式抛错。

改动保留已收到的 partial answer，立即清除消息的 streaming 标记并释放 composer；`AbortController.abort()` 仍负责取消在途请求。EOF、error 和替换旧流都继续核验 controller 身份，过期回调不能覆盖新流状态。

本修复已通过主代理独立复验，准备以单独 fix 提交接受。主代理在 accepted 615ff1f 的 fresh 快照叠加精确冻结文件，浏览器测试 3/3、pnpm typecheck、pnpm build 均通过。本修复不包含 ChatPage、FileUploader、trial store、locale、类型、模型或后端业务改动。T01 使用含本地 Stop 修复的 clean 候选做截图证据；mixed S13 仅作后续比较，不能混进 Stop 最小变更。

## 冻结输入

干净隔离快照：`C:\Users\22126\AppData\Local\Temp\sqlchat-useSse-clean-5b9c543-cba600a5cc064394bd9a6542f95ddf53`。基线 `5b9c543757cb4e83031226762131f36b6fa6907b`，主代理确认其前端与 accepted `3d1c5cc` 等价。Stop 候选 `src` fingerprint：`ac8a434e76bd5657b62bb375113323cc073b7bc6e9e2297444db90d7bbde0883`。

共享工作树的 Stop 专属输入 SHA-256：

| 文件 | SHA-256 |
|---|---|
| `frontend/src/composables/useSse.ts` | `510beb750c8c4d9fac07cd7ccc9945864bb37d56430a0b19fd6817bc7bedef7f` |
| `frontend/tests/sse-stop.test.mjs` | `16c4f3be65a4074ce47add9902659f32ae51eb1519194060dca46da3fc41ee83` |
| `frontend/tests/fixtures/sse-stop-test-helper.mjs` | `20bc66296fb9c41e4c0b14d37037580e7989c32092d1f661086116ca42fa329c` |
| `frontend/tests/sse-eof.test.mjs` | `f239217a70e09733b77fe5b2201e89b7874901641fac6a2fe7f0b8ac0634f9c7` |
| `frontend/tests/fixtures/sse-test-vite.config.mjs` | `018dbd67ac27db692b680204854e0f079cec9df9c0b6ca84c5a79bf74da3a936` |

`frontend/tests/chat-contract.test.mjs` 现有额外历史回放用例来自共享工作树其他阶段。本轮仅调整测试启动器的独立 Vite cache、mock API URL 和路由预热；该完整文件不应不加审查地并入 Stop 最小提交。当前文件 SHA-256：`2d64afccfff778096f109517fc578482e73c19b15a338fa95b5e8d2bd1e1ba39`。

## 验收证据

干净隔离快照中通过的命令（在 `frontend` 目录）：

```powershell
node --test --test-concurrency=1 tests/chat-contract.test.mjs tests/sse-eof.test.mjs tests/sse-stop.test.mjs
node node_modules/vue-tsc/bin/vue-tsc.js -b
node node_modules/vite/bin/vite.js build
```

记录结果：浏览器测试 3/3 通过；`vue-tsc` typecheck 通过；Vite production build 成功。build 只显示已有的 Vite config `__dirname` 迁移提示和大 chunk 提示。此次只动前端与测试，不涉及 Python，因此不跑 Ruff。

按项目的 pnpm 工作流可使用等价命令重跑：

```powershell
pnpm exec node --test --test-concurrency=1 tests/chat-contract.test.mjs tests/sse-eof.test.mjs tests/sse-stop.test.mjs
pnpm run typecheck
pnpm run build
```

Stop 浏览器契约用阻塞中的 mock `/api/chat` POST 等待用户 Stop：先写入 partial answer，再观察 reactive `streaming` 变为 false、`store.isStreaming` 为 false、partial 内容保留，并确认同一 POST 收到精确 `net::ERR_ABORTED`。SSE EOF 测试断言 EOF 不重试写请求、历史内容正常重放且旧流不能污染新轮次。chat-contract 保留事件渲染及历史回放断言。

冷启动偶发 EOF 失败来自 Vite dependency optimizer 在 `window.sseEofTest` 创建后触发主页面 reload。测试现为每次启动用唯一 `cacheDir`，等依赖 metadata 达到所需入口后才发起 EOF 场景，并记录主 frame 导航和 Vite 输出；没有扩大网络错误豁免，也没有用固定 sleep 替代就绪条件。

失败前的 T01 证据仍保留：原共享工作树运行 `3ac2d5bb-0c37-4f6f-a961-8da47119c2f0` 候选截图 `sqlchat/.git/acceptance/s15-ui-3ac2d5bb-0c37-4f6f-a961-8da47119c2f0/candidate/chat-stopped-terminal-failure.png`，SHA-256 `0b92ff6f752669da1eb5659f2fde282d309c0eaaa24c4b550a5a38c2f5705b9b`；clean 隔离前修复失败 run `ce51dff9-6e9c-4db4-b109-3cfe9bdbb9e7` 的失败图也保留。它们显示 Stop 已移除而 streaming indicator 仍存在；不把按钮恢复等同于完整终态。

T01 clean/mixed 的全部 36 张 PNG、targeted recapture、每张截图 SHA-256 和历史失败说明见 [S15 冻结记录](../phase-15-ui/README.md) 与 [matrix manifest](../phase-15-ui/matrix-manifest.json)。这些都使用 mock HTTP API，不代表 FastAPI、模型服务或 Celery 的真实集成验收。主代理复验和范围审查详见 main-review.md；S13 其他产品改动仍待单独验收。
