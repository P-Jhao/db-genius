# MySQL 协议族主代理验收

状态：独立适配器子阶段已验收并提交 ef1c17c；真实缺实例边界保留，S12整体未完成。

子代理15文件冻结清单 SHA256 f3573c36977adb8567f352a3c035eecd4bcf0954b5e805686e8e8e770ba83147，15变更及28保留文件原始SHA核对。主代理先在5b9c543基线上只叠冻结文件独立复验：全Ruff，strict mypy app76与9专项模块，14文件 **191 passed、0 skip、179.27秒**；包含专用PG/MySQL既有工作流和真实MariaDB4例，前后Maria表集合相同。脱敏日志 main-checks-prior.txt。

审查发现独立S05代码缺陷：合法partial元数据被拒绝导致StarRocks缺索引文档不能用于聊天。先修复并主验收提交 bdc0cc8，保留status1和明确文档错误；非元数据完整性错误仍失败。模型参数 a8e6a3a 同时接受后，主代理从新HEAD导出第二副本，仅叠同一15文件，未覆盖参数、db_config或其他共享草稿。再次全Ruff/strict mypy app76通过；partial状态机、HTTP模型参数、family超时/元数据/结果/工作流6文件 **119 passed、0 skip、32.46秒**。日志 main-checks-integration.txt。两次测试有重叠，不把数量相加。

业务既有diff仅registry新增5适配器及WorkflowSchema的MySQL族方言/字段映射；relational/safety/cancellation/SQL repair/types及S10其余模块保留。新增各引擎明确端口、会话超时单位及能力边界；MariaDB真实读写、回滚、注释/索引/类型、结果限制、禁用和试用规则、服务器超时、KILL确认均有证据。其他四引擎协议与工作流模拟通过，真实实例环境阻塞；不能把MariaDB结果移作其真实证据。

StarRocks索引视图未实现时明确incomplete，文档保留缺失提示，比较不得声称可靠自动迁移。TiDB超时仅SELECT，StarRocks写入超时及其他四类未固定代理的取消语义均未获真实实例确认；不发送不安全跨代理KILL，写入取消保留未知执行结果，不伪称服务器停止或自动重放。OLAP索引/行数读取失败保留已读列和具体错误，空列拒绝完整标记。主代理检查原Javapartial处理、原spec和AGENTS，核心目录和能力边界不变，不改AGENTS。

冻结原件不修改；暂存文本末尾统一单换行，freeze SHA记录原始历史字节。此提交不含Mongo、Oracle/SQLServer、试用/DSML、部署或效果矩阵，完整迁移仍需后续阶段。
