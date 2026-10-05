# 开源版文件上传入口

2026-10-05：按用户要求，聊天页复用已有 `FileUploader`，移除上传入口的版本门控，并仅移除后端上传服务的试用拦截。支持已有格式（包括 xls/xlsx），未调整文件格式、20 MiB 大小限制、登录认证、文件归属校验和存储配置。

数据库比较、workflow、SQL 写入、数据源与模型管理等其他正式版限制继续生效。上传成功不代表试用版已开放 Excel 数据库导入工作流；存储未配置时继续明确报错。

已有前端浏览器测试验证状态未知与试用模式均显示上传入口，xlsx 到达 mock 上传 API 并显示返回文件，同时数据库比较、数据源及模型管理继续隐藏。已有后端 API 测试生成有效 xlsx，在试用模式上传至真实本地存储、回读字节一致，跨用户读取返回业务码 403。既有 `buildRequest` 继续携带已上传文件的 `fileIds`，本次未对该聊天请求单独新增断言。

验证：`pnpm typecheck`、`pnpm build` 通过；`pnpm exec node --test tests/s13-trial-ui.test.mjs tests/s10-upload-contract.test.mjs` 为 3 passed；后端 `.venv/Scripts/python.exe -m pytest tests/test_file_upload.py tests/test_file_upload_persistence.py tests/test_trial_api_matrix.py tests/test_trial.py -q` 为 40 passed / 1 skipped（Windows 测试进程不支持目录符号链接）。build 仅有既有 Vite 原生配置兼容及产物分块大小警告。

正式 8109 栈已完成前端及 API 镜像重建，并通过 Compose `--no-deps up` 更新这两个服务，命令退出码为 0、两服务均 healthy。`GET http://localhost:8109/api/health/ready` 返回业务码 200、status UP，数据库及消息代理均 UP。云端 OSS 尚未进行真实上传验收。根目录和 sqlchat 的 `AGENTS.md` 已检查，功能边界及核心目录未变化，保持不变。
