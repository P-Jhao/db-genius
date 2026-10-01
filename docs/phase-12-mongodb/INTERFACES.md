# 接口与兼容边界

`DatabaseAdapter` 包含 `db_type`、配置验证、连接测试、只读判断、元数据、文档和执行公开方法。现有关系库执行错误字段和安全规则不变。Mongo 成功返回 `success=true`、`result`、`rowCount`、`truncated`：find/aggregate 为文档数组，count 为非负整数，distinct 为 `{"values": [...]}`。不伪造关系库 `data`。

仅明确的服务端只读查询错误码 `2/9/14/168` 返回 `success=false/error/errorCode`，由既有工具治理限制修正次数和相同查询重试；认证/授权、连接、未知 driver 错误仍失败，超时/取消仍终止。JSON 写命令/聚合写阶段不能通过错误诊断修正入口放行。`adapters/diagnostics.py` 仅标准库与连接类型依赖，Mongo 可返回的 metadata/query 诊断共用它：删除本配置密码原文、URL quote/quote_plus 与 URI 用户名/密码，保留错误文本和组件位置。关系库错误清理不在本冻结范围。

Mongo 支持用户名/密码同时非空或同时空；半对显式拒绝。create/update 双空转换为匿名且清除旧密文，已认证配置 update 空密码不能猜测保留旧密码。关系库 update 空密码沿用原保留规则。Java 服务双空/空白加密为空；原 Vue 编辑不回填密码却要求凭据的 API/UI 差异已记录，不改前端。db_config.py 只新增 create/update 的凭据 helper 调用；accepted generate_doc 先连接测试、允许合法 partial 的路径保持。

Mongo 元数据的 `schemaInferred=true` 和 `sampleSize=50` 意义是**每个集合最多 50 个样本文档**，不是实际读取数或数据库文档总数。类型采用首见 BSON 类型，rowCount 为估计；样本不是完整正式 schema，compare 需要人工复核。空库仍生成该提示。采样本身不设 incomplete；字段、索引、计数或集合读取失败才设置 incomplete 并保留可靠项。索引 name/key/列名显式验证；未知或非法计数为 None，合法零为 0。

find/aggregate 最大返回 100 文档，distinct 返回值最大 100；maxTimeMS 与 driver socket deadline 生效。没有发送 Mongo 取消 RPC：取消在执行前、完成后或 driver 异常时观察，`cancel_request_sent=false`。ExecutionTimeout 才报告 server termination confirmed；NetworkTimeout 为未知，不能声称立即杀停，读操作 write outcome unknown 为 false。

WorkflowSchema 针对 Mongo 注册独立证据类；workflow_rows 调用 JSON 命令校验；workflow.py 只加 Mongo 前后执行与状态检查，不改原 SQL/附件证明。S11 可用 `adapter.is_read_only` 做其授权后的 compare 读取守卫；S11 安全报告需把 inferred schema 保持人工复核，本冻结不改 S11 文件。
