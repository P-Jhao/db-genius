# 主代理验收：停止生成响应状态

业务仅 useSse.ts 四行净变化：获取 Pinia store 中消息的响应式引用，缺失时显式抛错。取消控制器身份、已收到的 partial、请求 abort 和其他业务模块均保持原行为。没有引入 any；原复制大文件不在此次重写范围，AGENTS.md 边界和目录保持不变。

基线 615ff1f70632a51c61da30359a79d6688f86b49d。最终执行快照为 Windows TEMP/sqlchat-main-stop-400b1105d143436ca0b8adb5cd9e4432；7 个输入 SHA 与 main-freeze.json 相同，README 的验收状态由主代理更新。最小 chat-contract.test.mjs 只含启动隔离、就绪预热和故障诊断，没有并入共享 S13 额外用例或业务。测试仍断言请求数、事件内容、历史回放和跨轮隔离。

主代理命令使用 pnpm --config.verify-deps-before-run=false，避免 pnpm 11 对复用依赖 junction 自动安装/清理。浏览器三项全部通过，0 skipped，72.28 秒；typecheck 通过，生产构建成功。Node 24.12.0，实际 Vite 8.3.1。现有 __dirname 与大 chunk 提示仍存在，未掩盖。依赖和锁文件本轮不改。

首次将验收目录放在 .git 下导致 Vite 默认文件访问保护返回 403，三项均未进入业务断言；已原样保留基础设施失败日志，换到 TEMP 后按相同源码与测试重新执行，没有放宽 Vite 访问保护。另两次前置 pnpm/PowerShell 命令配置失败也未进入测试，不作为产品失败计数。

验收范围为真实浏览器 + mock HTTP SSE；不能据此声称 FastAPI、Celery 或真实模型完整集成通过。T01 截图证据独立维护，历史失败不删除。提交只包含停止修复、必要测试启动器和本阶段记录。
