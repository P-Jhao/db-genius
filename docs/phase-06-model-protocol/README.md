# S06 模型协议验收

状态：本地 HTTP 协议模拟验收通过；真实模型供应商待环境验证。

## 范围

- 对应 `spec/05-Agent与工作流设计.md` 第 6 节和 `spec/09-具体执行计划.md` 的 S06。
- `backend/app/agent/model.py` 处理兼容接口 URL、SSE 数据帧、推理内容、工具调用片段和用量。
- `backend/app/agent/streaming.py` 聚合流、回传工具消息、记录部分答案及用量。
- `backend/app/agent/types.py` 提供聊天和用量契约。
- `backend/tests/test_model_protocol.py` 使用本地 HTTP 服务覆盖分片、错误和取消。

## 验证

在 `backend` 目录执行：

```text
uv run --extra dev pytest -q tests/test_model_protocol.py
14 passed
uv run --extra dev ruff check app/agent/model.py app/agent/streaming.py app/agent/types.py tests/test_model_protocol.py
All checks passed!
```

未验证：真实 DeepSeek/OpenAI/Ollama/custom 供应商差异。S07 的聊天图、业务 SSE 和 S08 的驱动取消不属于本阶段结论。

提交：本阶段提交号见 Git 历史；本记录与实现同次提交。
