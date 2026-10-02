# 主代理验收

在最新accepted 8dacbf3新导出副本仅移最终12个SHA核对payload，另94个应用文件保持已接受字节（归一化换行）；native修复4c5a38d及所有新测试/报告完整继承，没有复制共享草稿。

主代理实际执行现有OCR/分类图/中止回归28 passed、0 skipped、28.29秒；Ruff全app/tests通过；全app显式mypy --strict通过96模块。进程handle在会话延续时丢失，但三个主代理完成日志全部存在并分别检查成功结果，未因handle丢失重跑同门槛。

主代理独立AST核对：仅剥离新增typing.cast与CompiledStateGraph导入、build_graph返回注解、cast调用后，两业务文件执行AST与当前已接受完全一致。没有新业务逻辑、SDK参数、权限、中止、提示词、工具调用或文件工作流改动；无新ignore/Any、依赖变更或镜像实现测试。

子代理81aedbe首轮61 passed/2真实trial未配置skip和4c5a38d最终28项证据分别保留，不混称同一运行，不与主28累加。真实OCR缺配置，当前OCR客户为模拟，不据全strict宣称云服务或最终部署通过。AGENTS功能边界/核心目录没有变化，检查后不改。

最终payload、原manifest与主证据扫描真实忽略配置中的敏感值及编码变体/长API key模式后暂存；旧source diff原字节保留，仅该证据排除空白检查，业务与新材料须通过。
