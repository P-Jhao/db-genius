# S09 运行内上下文和工具输出治理

范围：F-15、T-27、T-28。以 S08 `b305981` 为基线；文件/对比图、其他数据库、试用、DSML 和观测在后续阶段接入。本轮子代理实际结果见 `../phase-09-acceptance/README.md`，不以旧草稿自测替代主代理验收。

工具结果先按实际工具名选择字符上限，默认 4000；`SQLCHAT_TOOL_OUTPUT_PER_TOOL_MAX_CHARACTERS` 为明确 `dict[str, int]` 配置，支持 `executeSql=8000,readFile=6000` 或 JSON。非法/重复 pair、非法工具名或非正上限显式报错。短结果保持原文，包括短于字符上限的 100 行 JSON。超字符上限才识别 `data/result/rows/values` 数组，裁剪时最多保留 50 行（`SQLCHAT_TOOL_OUTPUT_MAX_ROWS`）；保持原结构、成功/错误和源 truncated/incomplete/totalRows 信号。其他结构使用合法 JSON 预览，不按文本换行数强制裁剪。相比原 Java 可溢出其上限的预览，当前响应严格受所选字符上限约束。

裁剪只用于入模。SSE `step` 与历史保存完整原工具结果，继续保持原 ToolOutputGuard 的过程展示行为。制品登记的是实际工具原文，按 user/task/ID 检查，默认每任务 20 个、TTL 1800 秒。readToolOutput 分页同样受工具字符上限约束，并返回 nextOffset。容量、过期、无权访问、页码错误或不足以容纳元数据的配置明确失败。API 的 finally 清理制品，独立 Graph 调用也在 finally 清理，重复清理幂等。解析器未读的文件数据不会因分页被恢复。

已知窗口达到 0.6 时，遮蔽最近 3 步以前的工具观察；小结果在遮蔽前也登记全文制品，已有 artifactId 则复用。达到 0.8 时，用当前语言的原 step-condenser 模板摘要最近 4 步以前的过程。start/end context_compact 保持原对象契约、七语言展示文案和本地 Token 估算；摘要为空或失败显式失败。默认不丢弃 stale reasoning。窗口未知不猜测容量。

相同工具名和规范化参数第 3 次提示换策略，第 5 次执行前停止；原 SQL 10 步上限保留。循环/步数停止的权威摘要强制标识未完成。模型只调用 doTerminate、或 SQL 全部失败后终止时，确定性摘要明确没有成功执行数据库语句并保留实际错误，不能让模型自由宣称完成。

图职责拆为 graph.py（分类/路由）与 graph_sql.py（SQL 节点），真实 LangGraph 和 S08 取消/记账仍保留。
