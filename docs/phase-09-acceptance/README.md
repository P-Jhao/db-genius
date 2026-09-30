# S09 独立阶段验收交接

状态：主代理独立复验通过，阶段已提交 `0bd3fc8`；具体结果见 main-review.md。日期：2026-10-01。基线：S08 b305981。快照：sqlchat/.git/acceptance/s09-integration-c61bfe1b949f480ba4b427373ba430cc。仅修改该副本，未暂存、提交、重置或覆盖共享工作区。

范围：F-15、T-26–T-28；保留原提示词、S07 SQL/简单问答图、S08 中止及幂等用量，默认模型仍 deepseek-flash。未接入文件工作流、结构对比、其他数据库、试用、DSML、观测或部署，后续阶段继续实现完整规格。

## 子代理实际验证

- Ruff：python -m ruff check app tests，全部通过。
- mypy：python -m mypy app，56 个源文件通过。
- 完整 pytest：143 项通过，3 项跳过，95.87 秒；包含真实 PostgreSQL/MySQL 既有适配器、聊天闭环和 TCP 取消回归。
- 上下文/聊天定向：57 项通过（44.37 秒）；之后新增两项受控 HTTP doTerminate 回归，与运行治理/聊天图/取消组合 32 项通过（27.22 秒）。
- pnpm install --frozen-lockfile：通过；pnpm build：通过（包含 vue-tsc -b）。
- node --test tests/s09-context.test.mjs：1 项浏览器通过（6.64 秒）。

完整后端使用既有 sqlchat-migration-test-postgres/MySQL 隔离实例。真实凭据仅从 docker inspect 读到子进程环境，未打印或落盘；模型是本地 HTTP 协议模拟。3 个跳过项为现有 Celery live-worker 两项和不可达 broker 专用一项，未注入其专用环境，单列为环境阻塞；S05/S14 的主代理独立 Worker 验收不由本报告替代。

## 主代理复验命令

使用 sqlchat/backend/.venv/Scripts/python.exe 的绝对路径，在副本 backend 运行 Ruff、mypy、pytest。完整 pytest 需在内存设置 SQLCHAT_TEST_DATABASE_URL 与 PG/MySQL TEST 环境变量（既有独立实例），不落盘凭据。定向清单包括 test_context_compress、test_context_cancel、test_runtime_governance、test_output_guard_contract、test_sql_termination、test_prompts、test_chat_graph、test_chat_api、test_chat_abort、test_chat_abort_api。

在副本 frontend：pnpm install --frozen-lockfile；pnpm build；node --test tests/s09-context.test.mjs。浏览器测试自行配置 /api 和临时副本服务规则。

## 尚未验证

真实模型压缩质量/同模型对照、真实大结果分页体验尚未验证；当前 HTTP 模拟、真实数据库和浏览器模拟不能互相替代。OSS/OCR、其他数据库、产品整体七语言、部署和观测属于后续阶段。本次检查 AGENTS.md，仅因 prompts 目录新增修改目录条目。

文件及 SHA256 冻结清单见 files.tsv；主代理接入时应按清单复制，并把共享工作区后续业务模块中的 S09 区块显式合并，不能覆盖 S10/S11/S13/S14 代码。主代理已记录实际复验结果与提交号，并由新 index 创建 S10 副本。files.tsv 保留原冻结副本的字节摘要，后续文档补录以当前记录为准。
