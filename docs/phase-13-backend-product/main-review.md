主代理独立验收以 ed7594bd09b8be3dcdfcde89435fee34e2b55f01 为基线，37 个子代理冻结文件的 SHA/bytes 一致；冻结 manifest SHA 为 0177ba4229cab015040cf403e6ee3f9878e87bf2a6eb0569d825932595541944。其余 101 个 accepted app 文件按换行规范化后与 HEAD 一致。保留 repr/C09 脱敏、S11 只读、Mongo、取消、模型参数及 STOP。

主代理复跑 Ruff、app mypy 89 文件、owned strict mypy 22 文件均通过；15 文件协议/试用/语言/兼容桥 142 passed、0 skipped；补充 DSML/取消 26 passed、0 skipped。独立真实 PostgreSQL/MySQL 服务与 LangGraph 试用副作用测试 4 passed、0 skipped，11.28s。外部模型是本地实际 HTTP 模拟；系统 store 是 SQLite；两个目标数据库是真实实例。上述分组不是完整产品或外部 Celery 验收。

审查 main.py 仅注册 trial；队列业务参数仍 id/version、locale 显式 header、ContextVar finally reset；DSML 仅在暴露工具的协议上下文恢复，有效 structured JSON 优先，歧义明确失败；原主意图与可选 simple 澄清选项保持原 Java 规则。公共 SQL/数据库/文件工作流无本次业务改动。所有本次 owned Python 文件 <=300 行。historical public-diff.patch SHA 69410861bff6b92848ae86beea872dd41e20a78e106c9b07212d8116fbdfa6d5，其 diff context 原有空白保留，不改写历史证据；补丁已对 accepted HEAD 校验适用。

真实 Flash 效果、前端浏览器、真实 worker locale、Nginx 和部署分别留对应验收。真实 OSS/OCR 环境未配置。AGENTS 已检查，现有业务能力范围和核心目录边界未变化，保持不变。主代理只提交精确 payload/阶段证据，未用共享旧草稿覆盖 accepted 实现。
