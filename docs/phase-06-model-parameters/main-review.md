# 模型参数修复主代理验收

状态：独立修复已验收并提交 a8e6a3a；最终同模型效果仍待 S15 集成镜像。

业务基线为 S10 13d4595。源副本 model-parameters-integration-3fcb807d9d2e44cd817a0ddd6eb12c69 清单 SHA256 307aa831ee779e8d375001b6350d347e9358ba9879328db6d9e8544ee1d778a3；9 个文件逐项匹配。主代理从新已验收 index 导出 main-parameters-71b98da9b3c0420295123dc3ed4251b1，仅复制该集合；已有业务 diff 只含 streaming、graph 分类 flag、context_compress 手动摘要调用。原提示词、底层传输、relay、S10导入/存储和SQL repair没有变化。

主代理独立执行 run-checks.ps1：Ruff app/tests 通过；strict mypy app 74 源模块通过；22 文件 **161 passed，无跳过，354.54 秒**。含 HTTP payload 分类关闭 thinking/省略响应格式与采样、普通问答/工具后续/步骤及最终摘要/手自动压缩 temperature 0.7、usage、协议错误、分类非法 JSON、各中止阶段及真实 PG/MySQL 工作流/200-207行截断/标识符/DDL/SQL修复。测试 provider 为本地真实 HTTP 服务模拟，与商业模型效果分开。

主代理另用实际 deepseek-flash 做一次无数据库副作用的直接分类 smoke：接口接受分类参数，返回严格 Classification JSON，sql_query/confidence 0.65/needsClarification true；供应商 usage 527 prompt +87 completion =614、callCount1。仅数值记录 main-provider-smoke.json，没有 prompt/reasoning/key。这一次不是应用API闭环，也不是原版对照，不能替代S15固定矩阵。

对照依据为原Java实际wire：普通 Agent/tool/summary明确temperature0.7，分类thinking disabled且省略temperature/top_p/max_tokens/response_format。未在relay覆写参数；不支持供应商参数时显式失败，不剥参重试。已核查AGENTS，未改变功能边界或核心目录，不修改。

提交前仅规范验收脚本末尾空行；files.tsv 继续记录子代理冻结原件的历史 SHA。原件不变，业务与测试不变。
