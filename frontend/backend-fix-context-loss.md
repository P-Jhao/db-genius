# 历史参考（不适用于当前 Python 后端）

此文件来自 DB-Genius Java 阶段。当前实现与验证状态以 sqlchat/docs 和根 README 为准。

# 后端修复：澄清 / 缺库报错后重试丢失上下文

> 目标仓库：`/Users/spcodhu/Code/backend/java/db-genius`
> 涉及模块：`db-genius-agent`（3 个 IntentHandler）
> 前端无需改动。改完需重新构建并部署后端（当前前端连的是远程 `https://db-genius.hlt.cab/api/`）。

---

## 一、问题与根因

**现象**：未选库发起 sql_query → 触发澄清 → 确认意图（仍未选库）→ 报「需要至少选择一个数据库配置」→ 选库后重发「继续」→ AI 丢失上下文。

**根因**：`conversation` 的创建、`conversation` 事件下发、用户消息落库，全部被推迟到 Handler 内部、且在「数据库前置校验」**之后**；而澄清分支根本不进 Handler。导致失败的前几轮请求「零持久化」、前端也拿不到会话 id。下一轮带 `conversationId=null` 进来时会**新建空会话**，`getRecentMessages` 取不到最初那句查询，AI 失忆。

关键位置（修复前）：
- `IntentRouter.java:113-121`：clarify 只发事件就 `complete()`，不建会话。
- `SqlQueryHandler.java:64-67` 先抛缺库错，`:73/:74/:79` 才建会话/发事件/存用户消息。
- 三个 Handler 的 `getOrCreateConversation(...)` 内部都用 `dbConfigIds.stream()`，传 null 会 NPE。

**修复思路**：把「建会话 + 发 `conversation` 事件 + 取历史 + 落库本轮用户消息」**提前到前置校验之前**。这样即使随后校验失败，会话与首条消息已持久化、id 已下发；客户端重试携带该 id 即可复用会话、加载历史。

---

## 二、改动 1：`SqlQueryHandler.java`

路径：`db-genius-agent/src/main/java/com/dbgenius/agent/intent/SqlQueryHandler.java`

在 `handle(...)` 方法内，把下列**整段**：

```java
        List<Long> dbConfigIds = request.getDbConfigIds();
        if (dbConfigIds == null || dbConfigIds.isEmpty()) {
            throw new IllegalArgumentException("SQL 查询需要至少选择一个数据库配置");
        }

        validateDbConfigs(userId, dbConfigIds);
        String dbDoc = buildDbDocContext(userId, dbConfigIds);
        String dialectContext = buildDialectContext(dbConfigIds);

        ConversationVO conversation = getOrCreateConversation(userId, request, dbConfigIds);
        sendEvent(emitter, SseEvent.of(taskId, 0, "conversation", conversation.getId()));

        // 先取历史再保存本轮用户消息，避免把当前消息重复塞进历史
        List<org.springframework.ai.chat.messages.Message> historyMessages =
                toHistoryMessages(conversationService.getRecentMessages(conversation.getId(), HISTORY_SIZE));
        conversationService.saveMessage(conversation.getId(), "user", request.getMessage(), null, "user");
```

替换为：

```java
        List<Long> dbConfigIds = request.getDbConfigIds();

        // 先建会话并下发 conversation 事件、落库本轮用户消息，保证即使后续前置校验失败，
        // 会话与首条消息也已持久化，客户端重试可携带会话 id 复用会话、恢复上下文
        ConversationVO conversation = getOrCreateConversation(userId, request,
                dbConfigIds == null ? List.of() : dbConfigIds);
        sendEvent(emitter, SseEvent.of(taskId, 0, "conversation", conversation.getId()));

        // 先取历史再保存本轮用户消息，避免把当前消息重复塞进历史
        List<org.springframework.ai.chat.messages.Message> historyMessages =
                toHistoryMessages(conversationService.getRecentMessages(conversation.getId(), HISTORY_SIZE));
        conversationService.saveMessage(conversation.getId(), "user", request.getMessage(), null, "user");

        if (dbConfigIds == null || dbConfigIds.isEmpty()) {
            throw new IllegalArgumentException("SQL 查询需要至少选择一个数据库配置");
        }

        validateDbConfigs(userId, dbConfigIds);
        String dbDoc = buildDbDocContext(userId, dbConfigIds);
        String dialectContext = buildDialectContext(dbConfigIds);
```

> 方法后续（`ChatModelSession session = ...` 及建 Agent 部分）保持不变。

---

## 三、改动 2：`WorkflowHandler.java`

路径：`db-genius-agent/src/main/java/com/dbgenius/agent/intent/WorkflowHandler.java`

在 `handle(...)` 方法内，把开头的校验 + 建库上下文段：

```java
        List<Long> dbConfigIds = request.getDbConfigIds();
        if (dbConfigIds == null || dbConfigIds.isEmpty()) {
            throw new IllegalArgumentException("工作流需要至少选择一个数据库配置");
        }

        validateDbConfigs(userId, dbConfigIds);
        String dbDoc = buildDbDocContext(userId, dbConfigIds);
```

替换为：

```java
        List<Long> dbConfigIds = request.getDbConfigIds();

        // 先建会话并下发 conversation 事件、落库本轮用户消息，保证即使后续前置校验失败，
        // 会话与首条消息也已持久化，客户端重试可携带会话 id 复用会话、恢复上下文
        ConversationVO conversation = getOrCreateConversation(userId, request,
                dbConfigIds == null ? List.of() : dbConfigIds);
        sendEvent(emitter, SseEvent.of(taskId, 0, "conversation", conversation.getId()));

        // 先取历史再保存本轮用户消息，避免把当前消息重复塞进历史
        List<org.springframework.ai.chat.messages.Message> historyMessages =
                toHistoryMessages(conversationService.getRecentMessages(conversation.getId(), HISTORY_SIZE));
        conversationService.saveMessage(conversation.getId(), "user", request.getMessage(), null, "user");

        if (dbConfigIds == null || dbConfigIds.isEmpty()) {
            throw new IllegalArgumentException("工作流需要至少选择一个数据库配置");
        }

        validateDbConfigs(userId, dbConfigIds);
        String dbDoc = buildDbDocContext(userId, dbConfigIds);
```

同时**删除**后面文件处理块之后的这段（已上移，避免重复）：

```java
        ConversationVO conversation = getOrCreateConversation(userId, request, dbConfigIds);
        sendEvent(emitter, SseEvent.of(taskId, 0, "conversation", conversation.getId()));

        // 先取历史再保存本轮用户消息，避免把当前消息重复塞进历史
        List<org.springframework.ai.chat.messages.Message> historyMessages =
                toHistoryMessages(conversationService.getRecentMessages(conversation.getId(), HISTORY_SIZE));
        conversationService.saveMessage(conversation.getId(), "user", request.getMessage(), null, "user");
```

> 中间的 `hasFiles / enhancedMessage / toolContext` 文件处理块保持原位不变；其后 `ChatModelSession session = ...` 及建 Agent 部分不变。

---

## 四、改动 3：`CompareHandler.java`

路径：`db-genius-agent/src/main/java/com/dbgenius/agent/intent/CompareHandler.java`

在 `handle(...)` 方法内，把开头的 pre/test 校验 + 取文档 + 建会话段：

```java
        Long preDbConfigId = request.getPreDbConfigId();
        Long testDbConfigId = request.getTestDbConfigId();
        if (preDbConfigId == null || testDbConfigId == null) {
            throw new IllegalArgumentException("数据库对比需要同时提供 preDbConfigId 和 testDbConfigId");
        }

        dbConfigService.validateConfigForChat(userId, preDbConfigId);
        dbConfigService.validateConfigForChat(userId, testDbConfigId);

        DbConfig preConfig = dbConfigService.getById(preDbConfigId);
        DbConfig testConfig = dbConfigService.getById(testDbConfigId);

        String preDbDoc = preConfig != null && preConfig.getDocContent() != null
                ? preConfig.getDocContent() : "Documentation not available";
        String testDbDoc = testConfig != null && testConfig.getDocContent() != null
                ? testConfig.getDocContent() : "Documentation not available";

        List<Long> configIds = List.of(preDbConfigId, testDbConfigId);
        ConversationVO conversation = getOrCreateConversation(userId, request, configIds);
        sendEvent(emitter, SseEvent.of(taskId, 0, "conversation", conversation.getId()));

        String message = request.getMessage() != null ? request.getMessage()
                : "Please compare the pre and test databases and generate deployment SQL.";

        // 先取历史再保存本轮用户消息，避免把当前消息重复塞进历史
        List<org.springframework.ai.chat.messages.Message> historyMessages =
                toHistoryMessages(conversationService.getRecentMessages(conversation.getId(), HISTORY_SIZE));
        conversationService.saveMessage(conversation.getId(), "user", message, null, "user");
```

替换为：

```java
        Long preDbConfigId = request.getPreDbConfigId();
        Long testDbConfigId = request.getTestDbConfigId();

        String message = request.getMessage() != null ? request.getMessage()
                : "Please compare the pre and test databases and generate deployment SQL.";

        // 先建会话并下发 conversation 事件、落库本轮用户消息，保证即使后续前置校验失败，
        // 会话与首条消息也已持久化，客户端重试可携带会话 id 复用会话、恢复上下文
        List<Long> configIds = (preDbConfigId != null && testDbConfigId != null)
                ? List.of(preDbConfigId, testDbConfigId) : List.of();
        ConversationVO conversation = getOrCreateConversation(userId, request, configIds);
        sendEvent(emitter, SseEvent.of(taskId, 0, "conversation", conversation.getId()));

        // 先取历史再保存本轮用户消息，避免把当前消息重复塞进历史
        List<org.springframework.ai.chat.messages.Message> historyMessages =
                toHistoryMessages(conversationService.getRecentMessages(conversation.getId(), HISTORY_SIZE));
        conversationService.saveMessage(conversation.getId(), "user", message, null, "user");

        if (preDbConfigId == null || testDbConfigId == null) {
            throw new IllegalArgumentException("数据库对比需要同时提供 preDbConfigId 和 testDbConfigId");
        }

        dbConfigService.validateConfigForChat(userId, preDbConfigId);
        dbConfigService.validateConfigForChat(userId, testDbConfigId);

        DbConfig preConfig = dbConfigService.getById(preDbConfigId);
        DbConfig testConfig = dbConfigService.getById(testDbConfigId);

        String preDbDoc = preConfig != null && preConfig.getDocContent() != null
                ? preConfig.getDocContent() : "Documentation not available";
        String testDbDoc = testConfig != null && testConfig.getDocContent() != null
                ? testConfig.getDocContent() : "Documentation not available";
```

> 其后 `ChatModelSession session = ...` 及建 Agent 部分保持不变。

---

## 五、为什么这样改是安全的

- **`getOrCreateConversation` 复用逻辑不变**：当 `request.conversationId` 有效且归属当前用户时直接复用，`dbConfigIds` 参数仅用于「新建」时拼 `dbConfigIds` 字符串。传空列表时新建会话的 `dbConfigIds` 为空串，无副作用。
- **历史/本轮消息顺序不变**：仍是「先 `getRecentMessages` 取历史，再 `saveMessage` 本轮用户消息」，不会把当前消息重复塞进历史。
- **`SimpleChatHandler` 无需改**：它没有数据库前置校验，现有「先建会话后落库」顺序本就正确。
- **`IntentRouter` clarify 分支无需改**：用户确认意图后仍会进入对应 Handler，由 Handler 建会话即可覆盖；保持最小改动。

---

## 六、验证

1. 编译：`mvn -q -pl db-genius-agent -am compile`（或整库 `mvn -q compile`）。
2. 复现三步流程（需构建并部署/本地运行后端）：
   - 第 2 轮缺库报错后：确认已下发 `conversation` 事件、DB 中该会话已有 `type=user` 的原始消息；
   - 第 3 轮选库重发：请求携带同一 `conversationId`，`getRecentMessages` 能取到原始查询，AI 不再失忆。
3. 回归：一次选对库的正常 `sql_query / workflow / db_compare` 流程不受影响（仅执行顺序提前，落库内容不变）。

---

## 七、可选增强（前端，非本次必需）

缺库报错后，用户需手动选库并重新输入。可在输入区错误提示旁加「重试」按钮，直接以 `lastUserMessage` + 当前已选库重发（复用 `ChatPage.vue` 的 `buildRequest`）。后端修复后「继续」这类措辞也能靠历史恢复上下文，故此项仅为体验优化。
