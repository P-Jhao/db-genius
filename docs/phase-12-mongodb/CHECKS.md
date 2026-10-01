# 验证分层

| 层级 | 结果与证据 |
|---|---|
| Mongo 命令/配置/文档/生产 workflow 确定性与 HTTP 模拟 | 前一 integrated 副本 91 passed / 22.57s；不依赖 test-only shim |
| 既有安全、取消、repair、S10 partial/family 确定性 | 前一 integrated 副本 191 passed / 4 skipped / 72.32s；四项是当时未注入真实 SQL workflow repair 目标，此后新 HEAD 桥接复跑 |
| Mongo 实际数据库 | `real-mongo-integrated.json`：20 passed，Mongo8.0.32；含 16 adapter 真实项和 4 生产 HTTP graph + 实际 Mongo 项；模型 HTTP 模拟、系统 SQLite，数据库集合前后相等 |
| 凭据诊断修复 | `diagnostics-checks.json`：34 新项 + 57 相关旧项 = 91 passed / 1.54s；outer/fields/indexes/count/read 的 raw/quote/quote_plus、URI/非 URI、未知 URI 凭据，错误和 partial 保留 |
| 最终静态检查 | 全 app/tests、两个运行 runner 与清单生成脚本 Ruff 通过；app mypy81，Mongo/family 三个私有类型收窄测试及三个脚本共 16 源文件 mypy 通过 |
| 新 accepted 游标 HEAD 关系桥接 | `real-relational-bridge.json`；26 passed / 0 skipped / 148.32s；真实 PG/MySQL/Maria、普通 SQL workflow/schema quoted numeric/repair；系统 SQLite，HTTP 模拟模型 |
| 真实模型效果 | 未测；HTTP 预设响应和实际 Mongo/SQL 查询不证明真实 provider 效果，留 S15 同模型/参数/权限/快照对照 |
| 云服务 | OSS/OCR 无可用配置，真实云环境阻塞；保留已接受 S10 实现与模拟证据，不宣称 T17 真实通过 |

20 项 Mongo 实际证据属于 `3d1c5cc` integrated 副本，最终基线迁移至 `9703123` 保留相同 Mongo command/metadata reader/workflow/test 源码；部分公共文件仅 CRLF/LF 不同，仅 mongodb.py 的可返回错误诊断后来接入脱敏 helper；该差量已单独定向测试，没有伪称旧证据覆盖新 fault-path 字节。`evidence-reuse.json` 记录字节及换行归一化比较和诊断后测试。accepted PG 游标 fix 与 S05 partial、模型参数、S10、family 由守卫确认。

限制：schema 为每集合最多50个样本文档观察与估计行数；driver timeout/cancel 不承诺发送取消 RPC；Mongo 导入/写入明确不支持。Oracle/SQL Server 后续独立阶段，既有 MySQL 协议族的 TiDB/Doris/StarRocks/OceanBase 实际实例仍环境阻塞，不以 Maria 实际验证替代。代码缺陷使用失败/待修复，不标环境阻塞。
