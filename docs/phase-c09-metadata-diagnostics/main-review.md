# 主代理验收：关系库元数据诊断

基线 615ff1f70632a51c61da30359a79d6688f86b49d；随后 780becf 仅前端和文档，不影响本次后端证据。冻结输入 dfc3a127dc10ab4f664d1c808116b8bc0f1e9d5cf81c35debc8dfcc394575551，9 项 payload 全部逐项 SHA 验证。

主代理证明业务变化严格等于两处 import 和三个 errorMessage 赋值，执行、驱动、流式游标、单表读取、取消和超时方法 AST 不变；109 个其他 app 文件与 accepted HEAD 归一化源码相同，ConnectionConfig 的 615ff1f repr 修复保留。Git archive 因换行属性产生 CRLF，不能把归一化等价称作字节一致。证据见 main-scope-review.json。

主代理 Ruff 全 app/tests/运行脚本通过，app mypy 84 文件通过，owned strict mypy 4 文件通过。13 文件 pytest 246 passed / 0 skipped / 35.65 秒；真实 PostgreSQL16.14/MySQL8.0.46 元数据、只读写入守卫、失败计数隔离专项 3 passed / 0 skipped / 8.73 秒。凭据仅在内部读取、子进程环境传递，日志已脱敏；模型效果没有在此阶段测试。

元数据只有错误诊断去除密码及编码/URI形式，保留组件错误、incomplete、未知 rowCount 和有效业务结构/注释。没有第二次结构读取、吞掉顶层异常、将失败变成功或清理真实查询数据。AGENTS.md 无功能或目录变化，保持不变。

历史 public-diff.patch 原始 SHA ed9ef805b28fac0eca5c6ee0d983879ad6f43e8f63b997af5ee6c866a88dc670 保持；git apply --check --cached 通过。嵌套 patch 上下文空行有尾随空格，因此 staged diff whitespace 检查只排除这份原始 patch，其他文件全部检查；不修改历史证据来让检查表面通过。
