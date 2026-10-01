# C09 关系库元数据诊断脱敏

最终副本从 accepted `a56734b90871fc64f8d36821ff0b12bb6e5fa7db` fresh 只读导出，包含 Mongo accepted `5c9c2cdb22c920f595dd5c8485a013c650a4fff1`。业务差量只有 relational.py/mysql_family_metadata.py 两处 import、三个 errorMessage 赋值；新测试和本阶段文档独立交付，不混 Mongo 比对测试或 S11 业务。

复用已接受 diagnostics.sanitize_diagnostic，accepted SHA `8fdd20a98bcd657db4e2e8bcfeb365c5fb3d406b8acfbb72428dcbd819498f0d`（原冻结 SHA `f63553b974c350f00c9e0bd9828526a2abce77f5ed6854756f7cefc1b83befac`，仅 Git 换行不同，归一化源码相同）；helper 本次不改、不列交付。元数据公开诊断删除配置密码原文、URL quote/quote_plus 和 URI userinfo，保留具体组件失败、incomplete、可靠表/列/索引和未知 rowCount None。业务表名、字段名、注释、真实结果不清理。没有重取 metadata、改变 driver 调用次数或把顶层抛出异常转换成 partial 成功。

public-diff.patch 是相对 accepted HEAD 的代码/测试最小差量；preserved-methods-final.json 证明除两元数据公开方法外所有执行、PG游标、连接、超时、取消和单表读取方法 AST 保持一致。final-freeze.json 提供唯一 SHA/bytes 清单与 accepted 后端守卫，只按清单整合，不整份复制旧公共文件。

Ruff 全 app/tests 与运行脚本通过；三个业务/测试文件加运行脚本 strict mypy 通过，app mypy84通过。十三文件确定性回归 **246 passed / 0 skipped / 51.90s**，包含新55项、既有partial/family/safety/contract/cancel和 S11 diff/evidence/read/graph。实际专用 PG16.14/MySQL8.0.46 三项元数据/访问守卫 **3 passed / 0 skipped / 9.30s**，验证字段/注释/索引/行数、partial事实和非错误路径不变。详见 checks.json / real-metadata.json。

真实目标仅 loopback15432/13306；凭据在脚本内部 Docker inspect 读取，通过临时子进程环境传递，输出按原文/编码形式脱敏。fixture 只创建和精确清理随机测试表/角色，不改其他库、容器生命周期或 PG app。模型仅确定性与受控 HTTP 模拟，未进行真实 provider 效果对照。

复验使用共享 backend/.venv/Scripts/python.exe：在本副本根目录运行 docs/phase-c09-metadata-diagnostics/verify_real_metadata.py；在 backend 运行检查与 checks.json 的 pytest 命令。静态命令为 `python -m ruff check app tests ../docs/phase-c09-metadata-diagnostics/verify_real_metadata.py`、`python -m mypy app`、`python -m mypy --strict --follow-imports=silent app/adapters/relational.py app/adapters/mysql_family_metadata.py tests/test_metadata_diagnostics.py ../docs/phase-c09-metadata-diagnostics/verify_real_metadata.py`。

已检查 AGENTS.md，无核心目录/功能边界变化，保持不变。旧 C09 准备副本、复制的 preparation-public.patch/preserved-methods.json 和旧 Mongo/S11/family/S15 冻结保持原样，准备证明不属于本次唯一交付清单。没有共享写入、Git写操作、容器启停/删除或原 Java 修改。
