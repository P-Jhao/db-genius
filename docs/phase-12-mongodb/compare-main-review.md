# 主代理验收：真实 MongoDB 结构对比补充

基线 615ff1f70632a51c61da30359a79d6688f86b49d 上仅叠加一个测试和阶段文档，业务未改。输入 freeze SHA aac517ef3ec09621ffa95234fd77f62b28a6b0843e7f90f27e1bba62e351c544；4 个 payload 全部逐项校验。后续 780becf 是前端修复，637be1d 只变更关系库诊断，不涉及 Mongo 对比业务。

主代理 Ruff 两个新文件通过，owned strict mypy 两文件通过（follow-imports=silent 保留导入类型检查，将未修改历史模块排除出新增 strict 范围）。第一次从项目根启动 mypy 缺 app 路径，第二次错误地扩大 imported strict 门槛；这两次静态配置问题原样记录在 compare-main-checks.txt，修正工作目录及 owned 范围后成功，产品和测试内容未修改。

真实专用 MongoDB 8.0.32:17017 复跑 4 passed / 0 skipped / 12.07 秒。覆盖生产 get_schema、execute_comparison_read、schema_diff、RunTools 和 LangGraph：pre/test方向、采样50条导致不完整确定性报告、四种只读命令、$out/$merge含嵌套拒绝、跨用户404、反向比较拒绝、不得生成可直接执行的可靠迁移SQL。fixture 两个随机数据库逐项比对集合内容，测试后精确清理，数据库列表保持不变，不改变容器生命周期。

目标库真实，系统持久化用临时 SQLite，模型是受控 HTTP 模拟；没有宣称真实模型效果、Mongo认证目标或 Mongo 写入工作流通过。原 child real-compare-mongo.json 保留，主代理独立证据见 compare-main-real.json。AGENTS.md 的目录/功能范围无变化，保持不变。
