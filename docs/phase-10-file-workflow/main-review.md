# S10 主代理独立验收

状态：本地文件与工作流阶段门槛通过，已提交 `13d4595`；真实 OSS/OCR 为环境阻塞，不代表完整迁移完成。

源冻结副本 `.git/acceptance/s10-integration-1790786050404` 的 files.tsv SHA256 `f4faa47d61cdc050fa0cb09672a16679053646b9270218f687dda9d88ca4b08a`；52 个文件全部逐项校验。主代理从已验收 index 新导出 `.git/acceptance/s10-main-4ddac703205846cbac1707aabc0ae37a`，仅复制冻结文件，保留此前独立 SQL repair a83368f；共享后续业务草稿、原 Java 未覆盖。

主代理亲自执行：Ruff app/tests 通过，mypy app **74 个模块通过**（未全局 ignore missing imports）；真实专用 PostgreSQL16/15432、MySQL8/13306 全部 backend tests **274 passed、4 skipped，332.56 秒**。证据为 main-ruff.txt、main-mypy.txt、main-pytest.txt。凭据只读入当前子进程，不落日志。模型为实际 HTTP 协议模拟，不能证明真实模型效果。

确认上传归属、公开 VO 脱敏、类型/20MiB 限制、六类文档/五类图片、NULL/Decimal/文本编号、PG quoted 大小写/MySQL反引号、CREATE/ALTER后真实schema刷新、200/207行截断、SQL100行分页去重、原步骤上限、取消/Token/写入不重放均保留。真实 PG/MySQL 从上传文件服务→HTTP模型协议→LangGraph→写入→独立查询覆盖200/207行；普通无附件及非结构化附件操作另用SQLite实际目标验证，不冒充各引擎全流程。失败读取不继续写，已知安全SQL错误可修复但未知写入结果不重试。上传提交成功后确认失败保留对象，flush且已确认回滚失败才补偿删除；真实PG上传元数据API补偿联调未单独验证。

4项跳过：live Celery worker2项、故障broker1项因本轮未配置对应专用条件；Windows目录symlink1项因缺权限。前者已有S14独立真实运行证据，但该冻结阶段不将 skipped 计为通过。真实OSS/OCR缺配置，SDK模拟契约通过仍不能计T-17真实通过。

前端主代理在独立副本 `pnpm install --frozen-lockfile`、`pnpm build`（包含vue-tsc）通过；`node --test tests/s10-upload-contract.test.mjs` **2 passed，无跳过，8.94秒**。浏览器API为fixture，与真实后端联调分开。Vite native配置与大bundle提示为已有警告。上传扩展名和11类允许文件/20MiB与后端一致，UploadedFile移除内部key和归属字段并保留nullable。

AGENTS.md审查：只增加实际storage/parsers核心目录说明，工作区AGENTS不变。S11对比AST守卫、模型参数对齐、其他数据库、trial/DSML/观测/部署均未混入本阶段。旧共享工作区仍有未集成草稿，后续子代理整合后再最终部署；当前开发运行容器不能冒称该接受版本。

提交构建日志时去除 Vite 输出的一处尾随空白；原始 raw bytes 仍在冻结副本，files.tsv 描述其历史 SHA。业务及测试文件未改动。
