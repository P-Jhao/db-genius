# 原版实际生成参数基线

状态：已采原版诊断，待业务 Agent 对齐和主代理重建 Python 后做最终对照。relay 全程不改请求参数，不以未证明的服务商默认值替代实际证据。

| 分支 | 原版实际 controls | 证据 |
|---|---|---|
| SQL Agent 工具规划/总结 | 8 次请求均显式 `temperature=0.7` | `java-diagnostic-20261001T033044918326Z.json` 中 aggregate；该历史文件只支持执行/参数/usage 校准，未用最终答案新门槛 |
| 歧义分类 | 温度/top_p/max_tokens/max_completion_tokens/frequency_penalty/presence_penalty/seed/reasoning_effort/response_format 均省略；`thinking={type:disabled}`；非流式 | `java-diagnostic-20261001T034653135813Z.json` 中 ambiguity，1 次真实 provider 调用；usage 863/57/920 与应用一致 |

原版 IntentClassifier 从 `userModelConfigService.getActiveConfig(userId)` 取普通用户配置，通过 ChatClient `.options(extraBody thinking disabled).call().entity(...)` 分类。其 HTTP 客户端发送标准 chunked body：relay 实际记录 `POST /v1/chat/completions`、bodyBytes 3547、Content-Length 不存在、Transfer-Encoding 存在、HTTP 200。原先 relay 强制 Content-Length 造成分类未到 provider，这是测试工具缺陷；不能据此改原版 bootstrap key 或声称原配置无效。原版源码与 JAR 未修改。

Python 诊断时的源码差异：`CompatibleChatModel` payload 省略 temperature；`ModelStream.call(json_mode=True)` 传 `response_format={type:json_object}`，没有原版分类 `thinking disabled`。建议业务 Agent 在模型/调用边界明确区分 Agent 默认温度与分类 controls：Agent/tool/summary 显式 0.7，分类按原版省略温度、逐调用关闭 thinking，并按原规则处理 response_format。不能在统一模型 payload 对所有调用强行写 0.7。

SQL、workflow、compare 在原版使用同一 ToolCallAgent/ReasoningChatModel 热路径；最终仍以实际各题采到的 controls 为准。上表不证明其他题已运行，也不证明 Python 修复已验收。

当前 relay 白名单记录 model、temperature、top_p、max_tokens、max_completion_tokens、frequency_penalty、presence_penalty、seed、thinking、reasoning_effort、response_format。数值必须有限；thinking 只收 enabled/disabled；response_format 只记录类型，json_schema 仅另收结构哈希，不记录 schema 文本。两个版本每轮的 controls profile 必须完全一致，否则 pair 状态为 `not-comparable`，错误为 `GenerationParameterMismatch`。不一致归入迁移待修复，不写成外部环境阻塞。
