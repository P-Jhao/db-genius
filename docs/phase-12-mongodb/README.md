# S12 MongoDB 独立集成

本冻结基于 accepted `9703123f279b669276b3e655b926b63365047e89`。后续 `ecb011f` 仅更新已接受阶段文档；主代理整合时保留该差量。本副本不写共享工作区，不执行 Git 提交、重置或清理。

MongoDB 公开命令限于 `find`、`count`、`distinct`、`aggregate`。写命令以及任何层级的 `$out`、`$merge`、服务端脚本操作均硬拒绝。普通多步骤只读 workflow 使用真实 JSON 命令与 Mongo `result`，不进入 SQLGlot；附件读取不等于导入，不能宣称已写入。关系库写入/导入、S08 取消、S09 查询修正和 S10 工作流证据规则保留。

注册表保留 MySQL/PostgreSQL/MariaDB/TiDB/Doris/StarRocks/OceanBase 七种关系库并新增 MongoDB。统一 Protocol 仅声明公开接口，不纳入关系库私有方法；`QueryResult.data/error/sqlState/errorCode` 保留，Mongo 新增可选 `result`。

证据分层与具体命令见 [CHECKS.md](CHECKS.md) 和 [OPERATIONS.md](OPERATIONS.md)，公共接口见 [INTERFACES.md](INTERFACES.md)。`final-freeze.json` 提供唯一文件清单、字节数、SHA 与只读守卫，`public-diff.patch` 是相对 accepted 基线的代码/测试差量。

历史冻结保持原样：准备 24 文件清单 SHA `759c60639b7f47571ba6e9ed5126ec1e9a319c4c5e6345d4758f0a297ebcf9eb`，元数据 revision 6 文件清单 SHA `9a26ff8879f06069f6f30391b28c429164783ca0bf530cd477189b812eca0138`。本目录是生产 workflow 接入后的独立交付，不再依赖 `mongodb_workflow_preview.py` 或 proposal `adapters/protocol.py`。

已检查工作区和仓库 AGENTS.md；本次仅在已有 adapters/agent/services/tests/docs 内增补内部模块，不改变核心目录或现有功能边界，AGENTS.md 保持不变。S11 graph/tools/database_tools/compare 和已接受参数、partial metadata、游标实现由冻结守卫确认未改。
