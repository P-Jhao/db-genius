# Mongo 与 S11 比对真实集成增补

源组合为已审 main-mongo-1790852339433 的只读复制；其业务随后已接受为 `5c9c2cdb22c920f595dd5c8485a013c650a4fff1`，最新 a56734b 仅阶段文档。本增补只交新增 test_compare_mongodb_integration.py 和四个本 revision 文档/运行文件，不改 S11、Mongo 或 C09 业务。

实际专用匿名 Mongo8.0.32、loopback17017，系统 store 临时 SQLite；生产 get_schema/execute_comparison_read/schema_diff/RunTools/LangGraph 路径，模型是受控 HTTP 模拟。**4 passed / 0 skipped / 13.44s**，Ruff 与新增测试/runner strict mypy 通过，详见 real-compare-mongo.json。

每例两个独立 s12_mongo_compare_pre/test_<uuid> 合成库：pre 的 retired、test 的 orders 与 items.email 差异，真实 count/find/distinct/aggregate 结果，方向 pre→test；字段只在第56个文档出现时不在50个样本内，报告必须保留 schemaInferred/sampleSize，图停止并给观察限制和无可直接执行SQL的报告，不能消费虚假“完整 schema/执行 ALTER”总结。sampleSize 指每集合最多50个样本文档，不是实际总文档数。

公开 insert、$out、$merge 和嵌套聚合写被403拒绝；实际工具 schema/read/compare 越权404，图反向和工具访问其他归属配置拒绝。compare 在工具访问时校验归属；未调用工具的模型文本不代表读取成功。每例最终比较集合名与逐文档快照无变化，精确清理仅自身两随机库；runner 验证数据库集合前后相等，无容器生命周期操作、无公开写能力增加。

复验：在隔离副本根目录运行共享 backend/.venv/Scripts/python.exe docs/phase-12-mongodb/verify_compare_mongo.py；runner 内部读取专用环境但不输出凭据。冻结清单 compare-revision-freeze.json 自身另计，只按其中新增文件整合。旧 Mongo38/S11/C09 冻结不改；原 Java、共享工作区、Git索引/提交/重置未修改。已检查 AGENTS.md，无核心目录变化，保持不变。该结果不代表真实 provider/model 效果。
