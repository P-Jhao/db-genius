# 队列失败诊断主代理验收

主基线02c6e4b（含a0f17fe native），返工候选基线a4b36a6；manifest SHA 8b7d30aaaa1002b8725523726be494bcae9693d5836edf645d11c37473fe9b36，10个payload核对原字节/大小，其他121 accepted app文件归一化一致。旧b89候选明确拒绝且原freeze保留，不能把其53通过当最终通过。

主独立发现并复现：含两种引号和反斜杠的repr口令仍残留片段；先截1000字符再脱敏会留下密钥前缀。返工helper先按原BusinessError locale/args获取完整诊断，清理配置凭据的原文、URL/repr/JSON变体及任意named secret正确配对引号，最后保留原1000上限/类名前缀。主两探针均确认不再残留，原失败与新结果分别记录。

实际命令在backend：全app/tests Ruff通过；普通mypy app96通过；owned显式--strict --follow-imports=silent3文件通过；pytest test_queue_diagnostics/test_db_config_partial/test_queue_locale **92 passed、0 skipped、8.78秒**。该组仅合成凭据、SQLite和mock publish，不证明真实broker/Worker或外部模型效果。原native/元数据/C09、S13 locale/版本/权限保留；服务AST逐函数比较，仅一个import及_enqueue诊断表达式变化，原状态guard/commit/返回False/队列args与header不变。

AGENTS检查：没有核心目录或功能边界变化，保持不变。S14后续复用本helper，不含OTel/指标/依赖修改。本修复经真实配置凭据扫描后独立fix提交；完整部署和worker指标仍待S14。
