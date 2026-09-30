# S09 主代理验收

2026-10-01，基于冻结清单独立复验；阶段提交 `0bd3fc8`。实际 PostgreSQL/MySQL 凭据仅在子进程环境；模型使用受控 HTTP 流。

- Ruff app/tests 全通过；mypy app 56 个源模块通过。
- pytest tests：143 passed、3 skipped，97.96 秒。三个跳过项为已有 Worker/Broker 专用条件，不能计为通过；S14 真实 Worker 消费和控制另有 2 项主代理证据。
- pnpm build（含 vue-tsc）通过；S09 七语言压缩显示、历史回放及禁止重复 POST 浏览器测试 1 passed，4.88 秒。
- 核对原提示词、工具覆盖上限及原字符/行集语义，自动摘要失败保存提示与原历史，制品任务/用户/TTL边界，取消传播与usage幂等。
- 发现 doTerminate 可绕过 SQL 实际执行检查后交回子代理修复；受控HTTP回归证明零成功语句/真实工具失败不能伪报完成。

真实模型压缩质量和最终同模型对照尚待 S15；后续完整功能继续按 S10–S15。暂存来自冻结副本，保留共享工作区其他阶段改动，不覆盖原 db-genius。
