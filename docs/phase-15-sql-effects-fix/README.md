# SQL 效果复测前的局部修正

本轮修正两个真实模型验收问题，保持原问题集、oracle 与原提示词资源不变。

## 禁用 SQL 的零执行结论

SQL 图在零成功语句时继续给出确定性结论。用户明确要求执行 `DROP`、`TRUNCATE` 或 `ALTER ... DROP`，且本轮没有尝试执行语句时，运行时用现有 SQL 安全检查确认命令形态，再按请求语言给出安全拒绝。没有执行动词时，只有整条消息是完整的禁用 SQL 命令才进入此分支。讨论命令含义、风险或结构报告，以及只在查询字符串和注释中提到命令，均不触发拒绝判断。

其他零成功情况仍报告未完成；已有语句错误保留在摘要中。模型的 `doTerminate` 原因不作为成功执行证据。拒绝文案只说明规则禁止及本轮没有执行语句，不声称执行层曾实际拦截，也不声称事务回滚。适配器中的禁止 SQL 检查保持原状。

## 指定输出列

SQL `prepare` 在原提示词、schema 和用户请求之外追加运行时系统约束：用户明确指定输出列或别名时，最终查询结果按该投影返回；JOIN、分组和排序所需的键可以用于对应子句，但不额外进入结果列；辅助验证查询不替代最终指定投影。这是模型行为约束，不是确定性 SQL 重写或结果列拦截。真实模型对五个 Python JOIN 失败场景的改善仍待复测。

## 结构对比报告交付

完整结构对比进入最终总结时，运行时系统消息要求最终答案自包含已验证差异；若声称提供迁移 SQL 或代码，必须在最终答案中实际给出，供人工审查。只有工具确认成功的动作可用完成时态。对比工具和中性 diff 算法未变，迁移 SQL 仍不能通过工具执行。

`decide` 的模型正文使用 `event=None`，因此正文不会作为可见回答事件发送。`doTerminate` 的 reason 会作为工具 `step` 事件出现，但不能替代最终 `summary`；验收证据提取最终 `summary` 为答案。因此此前“报告已输出”的 reason 不能证明报告正文已经交付。本轮只加强最终总结指令；真实模型能否完整交付 SQL 报告仍待效果复测。

## 本地验证

- `backend/.venv/Scripts/python.exe -m pytest tests/test_sql_termination.py -q`：44 passed。测试经过真实 LangGraph 图和受控 HTTP 模型，覆盖七语言拒绝与未完成、语句错误、直接 SQL、讨论性反例、只读 `DROP` 文本查询及输出列系统消息。
- `backend/.venv/Scripts/python.exe -m pytest tests/test_compare_report_delivery.py tests/test_compare_graph.py -q`：8 passed。最终模型请求收到自包含报告指令，最终答案包含可见差异和测试 SQL；迁移语句未调用执行工具。
- 静态检查和相关回归由主代理复跑；真实模型、数据库效果与 Docker 由主代理统一验收。

本轮未改变功能边界或核心目录，因此根目录 `AGENTS.md` 保持不变。

## 主代理回归、运行镜像与第二轮状态

主代理复核记录见 [main-fix-review.json](main-fix-review.json)：以候选提交 `49bdaffc2400bf4d9b0de0e56b67314f518b9ec9` 验证 44 个受影响测试模块，共 524 passed、0 failed、0 skipped；Ruff 对 app 与相关测试通过，strict mypy 对 app 的 104 个源文件通过。该回归使用受控模型/真实数据库 fixture，不包含真实模型调用。

复核后的 Compose 运行回执见 [main-runtime-review.json](main-runtime-review.json)：API、Worker 各检查 139 个镜像源码路径且均无差异，服务健康、代理 readiness 为 200，metrics-init 退出码为 0，命名卷保留，受保护服务身份无变化。第二轮真实模型矩阵已完成采集，共 120 行、60 组配对、138 个 turn；机器报告状态为 incomplete，见[第二轮结果复核](../phase-15-real-model/SECOND-RUN-REVIEW.md)。524 项回归使用受控模型与真实数据库 fixture，镜像健康回执只证明部署状态；两者都不代表真实 provider 效果验收通过。
