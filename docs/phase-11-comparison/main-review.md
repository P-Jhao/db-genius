# 结构对比主代理验收

需求依据：F-10、C-05/C-08 与 T-18/T-19/T-27/T-31。基于 accepted ecb011f 独立导出，逐项校验22文件冻结SHA与9703123基线441个保留文件。ecb011f仅修改两份验收回执，保持当前回执文档，不覆盖为子代理旧副本。

主代理审查确认既有业务只修改 graph_sql.py、tools.py、database_tools.py，新增 compare、compare_locale 和 schema_diff。比较方向固定pre为当前/test为期望；同一owned-ready连接与适配器判定和执行受控只读语句，普通SQL路径继续使用原策略。中性diff保持原新增/删除/字段类型/nullable语义；preSchema/testSchema复用本次各一份真实读取，不再次取证或编造字段。

主代理复跑全app/tests Ruff、严格mypy79模块，18关键测试文件 **134 passed、0 skipped，272.72秒**。涵盖实际PG/MySQL独立库方向/字段事实/跨引擎/真实读取故障、方言读命令、物理只读阻止nextval、副作用语句拒绝、SQL诊断修正，以及HTTP/SSE/历史/中止/用量和已有工作流回归。主日志见main-checks.txt。子代理完整集合521 passed、6 skipped、614.36秒是另一证据，两组部分重叠，不相加。

对比报告绑定本任务权威工具结果；缺少比较、partial、跨引擎或采样推断时给出明确限制。输出裁剪后，只有匹配本制品全文的连续分页覆盖才能解除truncated；分页不能替换本次权威结构。报告包含新增表真实字段type/nullable/PK与新增非空列，可用元数据边界仍如实保留。

主代理复现中文details_limited把未读取的截断制品称为步骤中的“完整报告”。新独立revision仅替换zh-CN/zh-TW两条提示，并新增真实diff经4000字符裁剪后的限制用例。逐项校验3文件SHA、463个原版守卫及两条精确替换；主代理Ruff/相关mypy2模块与locale/evidence **29 passed、0 skipped，18.73秒**，保持partial、跨方言、前20和截断限制。日志见phase-11-comparison-revision/main-checks.txt。原freeze与revision均未改写。

本阶段没有真实模型调用；图/HTTP模型为受控供应商模拟，不能证明真实模型报告效果。Mongo JSON/推断接口目前是受控模拟，需要Mongo公共接入后的真实组合验证。6项完整集合skip详见README：真实效果专项入口2、liveCelery2、负向broker1、Windows目录symlink权限1；云OSS/OCR按用户最新指令先实现与模拟验收，未宣称真实服务通过。

已发现关系库既有metadata诊断仍需统一凭据清理，另交子代理独立fix；不把S11功能通过当作最终T-03/C-09全范围通过。Mongo新能力的同类问题先修后另验收。AGENTS.md已核查，比较能力和agent/services目录此前已有边界，无核心目录改变，保持accepted版本不变。

files.tsv、revision files/guard 保留原冻结字节证据；主代理提交副本仅统一文档、日志及脚本末尾换行，原冻结源保持不变。末尾调整：


- docs/phase-11-comparison/mypy.txt
- docs/phase-11-comparison/pytest-initial.txt
- docs/phase-11-comparison/pytest-repair.txt
- docs/phase-11-comparison/pytest.txt
- docs/phase-11-comparison/ruff.txt
- docs/phase-11-comparison/run-checks.ps1

本地功能提交收据：ba579b416b24a02ea32f4c1616839d3b6e5a4401 feat: 实现数据库结构对比与受控迁移报告。本段为后续文档补录，不改变原测试快照。
