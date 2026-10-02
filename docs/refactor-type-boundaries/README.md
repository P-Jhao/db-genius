# OCR 与图执行的静态类型边界

独立 refactor，最终基线为已验收 native repair 提交 `4c5a38d`（完整 SHA 见根目录 `BASE.txt`）。
从已验收 Git 对象只读导出，只移植此前已验证的两个类型边界，不复制共享工作区草稿。
`accepted-baseline-delta.json` 记录从 `81aedbe` 到新基线的唯一既有源码变化 `sql_errors.py`，以及新增 repair 测试和文档；它们全部原样继承。

## 改动

- `backend/app/storage/ocr.py`：将无类型第三方 SDK 构造结果显式声明为现有 `_OcrClient` Protocol；OCR 凭据选择、SDK 构造参数、请求与响应检查均保持原样。
- `backend/app/agent/graph.py`：`build_graph` 返回 `CompiledStateGraph[RunState, None, RunState, RunState]`；默认 `ainvoke` 的宽泛 SDK 返回类型在已有 `RunState` TypedDict 边界显式转换。

只新增返回类型注解、两个 `typing.cast` 和必要类型导入。没有新增 `Any`、类型忽略、运行时校验、业务 helper 或镜像测试。两个业务文件分别 69 与 167 行，均未达到 300 行。
分类 `classification=True`、S13 locale/DSML、工作流/对比、工具执行、取消、`finally` 清理、提示词、路由和 SDK 调用参数不变。

## 首轮真实执行的检查（81aedbe）

以下是此前 `type-boundaries-c585c5f4efbf4cbf9d19fdec40bd276d` 的 `backend` 工作目录中，使用仓库现有 `.venv/Scripts/python.exe` 执行的检查。原证据完整移入本目录，没有将其伪称为新基线运行：

```text
python -m mypy --strict app
Success: no issues found in 96 source files
python -m ruff check app tests
All checks passed!
python -m pytest -q tests/test_ocr_boundaries.py tests/test_model_parameters.py tests/test_chat_graph.py tests/test_workflow_graph.py tests/test_compare_graph.py tests/test_trial_graph_targets.py tests/test_chat_abort.py tests/test_chat_abort_api.py
61 passed, 2 skipped in 126.59s
```

`mypy-strict.log`、`ruff.log` 保存工具返回的原始完整输出；`regression.log` 保存子进程输出。
这次是显式全 app `--strict`，并非将普通 `mypy app` 误称为 strict。
此前主验收发现的三处错误由这两个边界修复；本次最新基线含一个后续已验收模块，所以报告 96 个模块。

61 项实际运行使用假 OCR 客户端、本地受控 HTTP 模型、临时 SQLite 系统存储与模拟目标工具，覆盖 OCR 空文本/凭据全 pair、分类参数与严格 JSON、普通问答、SQL 工具回传、摘要、文件工作流、对比和取消。
两项跳过是 `test_trial_graph_targets.py` 的 PG/MySQL 真实目标用例；这次明确不配置 `SQLCHAT_TEST_PG_*` / `SQLCHAT_TEST_MYSQL_*`，对应 fixture 在调用目标适配器前执行 `pytest.skip("... disposable target credentials are not configured")`。
没有访问主代理占用的真实目标库，也没有进行真实 OSS/OCR 或外部模型调用。本修复不需要重新验证已验收的数据库族能力。

复验可执行 `python docs/refactor-type-boundaries/run-checks.py --all`；设置唯一 `TYPE_EVIDENCE_SUFFIX`，脚本拒绝覆盖既有证据。复验脚本使用 `-ra`，会同时输出跳过原因。

## 最终集成复验（4c5a38d）

从新已验收基线导出，只移植相同两文件；未重新执行已验收 native feature/repair 目标库测试。
在本副本执行 `python docs/refactor-type-boundaries/run-checks.py --integration`，实际子命令与结果：

```text
python -m pytest -q -ra tests/test_ocr_boundaries.py tests/test_chat_graph.py tests/test_chat_abort.py
28 passed in 21.62s
python -m ruff check app tests
All checks passed!
python -m mypy --strict app
Success: no issues found in 96 source files
```

原始输出见 `integration-regression.log`、`integration-ruff.log`、`integration-mypy-strict.log`。
这次没有 skip，也没有使用真实目标实例；新增 repair 白名单和测试/文档由最终基线继承，受 699 个非 owned 文件的逐字节守卫保护。

## 冻结与风险

`files.tsv` / `freeze.json` 只列两个业务文件及本短文档、现有检查证据和复验脚本。
`preserved.tsv` 校验其余 699 个最终已验收基线文件逐字节不变；包括新增 native repair、公共数据库执行、native/S13 安全守卫、模型参数和 `AGENTS.md`。
`type-boundaries.diff` 是两文件最小 diff；`guard-proof.json` 确认剥离新增类型注解、类型导入与 `cast` 后，两文件执行 AST 与已验收基线一致。
功能边界和核心目录未变化，检查后保持工作区与仓库 `AGENTS.md` 不变。

`cast` 只为已使用的第三方协议/图状态提供静态契约，不增加运行时验证。现有 OCR 响应检查和 `RunState` 生产节点依然承担原有运行时责任；第三方 SDK 将来改变接口时需要重新审查。
本次核对环境为 LangGraph 1.2.12、Aliyun OCR SDK 3.1.3、mypy 2.3.1、Ruff 0.16.9。没有更改依赖版本。
native repair 已由主代理独立验收提交；此 refactor payload 不包含它的白名单改动，不覆盖它的源码或测试文档。
