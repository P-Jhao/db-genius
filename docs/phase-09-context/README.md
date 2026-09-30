# S09 跨轮上下文压缩

范围：F-15、T-03、T-26，基线为已验收 S08 `b305981`。本文件描述 S09 独立副本的最终行为；本轮子代理自测与主代理独立验收分别记录在 `../phase-09-acceptance/README.md`。

手动入口仍是 `POST /api/chat/conversations/{id}/compress`，可选 `targetTokens` 是软目标。响应保留 `conversationId/compressed/beforeTokens/afterTokens/summaryMessageId/message`。摘要失败或为空返回 `compressed=false` 和明确说明，保留原消息与上下文；所有入口先验证归属。

自动压缩默认关闭，已知窗口和最近一次入模 Token 达到窗口 0.8 时，下一轮分类前压缩，保留最近 6 条有效消息。自动摘要在 SSE producer 内复用 S08 ModelStream，因此客户端断开或超时能取消上游，已收到的供应商 usage 纳入本轮幂等记账。自动失败通过既有 `step` 字符串事件显示失败说明并留在历史，随后使用原历史继续；没有新增交互。原 Java AutoCompressService 只记录日志并静默降级，这里依据 spec05“摘要失败时显式报告”修复该差异。中止摘要时保存本轮用户问题和一次 aborted 终态，原历史仍完整。S08 的 300 秒时限保持既有行为。

摘要成功后将旧内容标记 `compressed`，正文保留回放；新摘要为 `type=summary, step=-2`，记录保留消息 ID。入模先用最新摘要、被保留的最近消息及其后新消息；兼容旧 context_summary，不重复带入摘要之前的内容。step/tool/aborted/compressed 不重新入模。写入前核对完整有效历史快照，拒绝覆盖并发新增内容。

Token 压缩前后显示值是本地估算，不冒充供应商计费。真实模型摘要质量和同模型对照仍未验证。
