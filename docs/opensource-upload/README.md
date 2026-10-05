# 开源版文件上传入口

2026-10-05：按用户确认，聊天页复用已有 `FileUploader`，开源版（`trial_enabled=true`）仅允许上传 `.xlsx`、`.xls`。上传入口在版本状态未知和开源版均可见；状态未知时也只允许 Excel，待 `trialStore` 确认正式版后恢复已有全部格式。`accept`、上传前扩展名校验和错误提示均随状态更新。正式版继续支持 csv、docx、pdf、md 和已有图片格式。

后端在读取文件内容、获取存储和保存元数据之前按 `get_settings().trial_enabled` 检查扩展名。开源版非 Excel 文件即使绕过前端也返回业务码 400，且不落盘、不保存上传元数据。Excel 继续执行已有内容校验、20 MiB 大小限制、登录认证、文件归属及存储配置检查。未修改真实 `.env`、`.env.example` 或 OCR 配置。

数据库比较、workflow、SQL 写入、数据源与模型管理等其他正式版限制继续生效。上传成功不代表试用版已开放 Excel 数据库导入工作流；存储未配置时继续明确报错。

已有前端浏览器测试验证状态未知与开源版只接受 Excel、csv/pdf 在发送请求前被拒绝、xlsx/xls 到达 mock 上传 API 并显示返回文件；切换为已确认正式版后恢复 csv。数据库比较、数据源及模型管理限制继续验证。正式版独立组件契约 fixture 显式设定正式版状态，保留全格式、大小校验与 API 错误展示测试。

后端 API 测试生成有效 xlsx，并复用已有 `s10_sample.xls` 二进制样本，在开源版上传至真实本地存储、回读字节一致，跨用户读取返回业务码 403。九种非 Excel 扩展名均验证业务码 400、无文件读取/存储调用、无元数据、无存储目录。正式版 csv、20 MiB 边界、内容校验和存储事务测试继续覆盖。既有 `buildRequest` 继续携带已上传文件的 `fileIds`，本次未对该聊天请求单独新增断言。

验证：`pnpm typecheck`、`pnpm build` 通过；`pnpm exec node --test tests/s13-trial-ui.test.mjs tests/s10-upload-contract.test.mjs` 为 3 passed；后端 `.venv/Scripts/python.exe -m pytest tests/test_file_upload.py tests/test_file_upload_persistence.py tests/test_trial_api_matrix.py tests/test_trial.py -q` 为 50 passed / 1 skipped（Windows 测试进程不支持目录符号链接）。改动的上传服务和测试通过 Ruff，上传服务通过 mypy（`--follow-imports=silent --ignore-missing-imports`）。build 仅有既有 Vite 原生配置兼容及产物分块大小警告。

本轮 Excel 格式约束已部署正式 8109 栈：API 和前端镜像构建成功，通过 Compose `--no-deps up` 更新这两个服务，命令退出码为 0，两服务均 healthy。`GET http://localhost:8109/api/health/ready` 返回业务码 200、status UP，数据库及消息代理均 UP；运行中 API 上传服务源码 hash 与工作树一致。格式拒绝行为由本轮本地 API 测试验证；云端 OSS 尚未进行真实上传验收。根目录和 sqlchat 的 `AGENTS.md` 已检查，功能边界及核心目录未变化，保持不变。
