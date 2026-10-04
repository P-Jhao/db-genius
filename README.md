# SQLChat

SQLChat reuses the DB-Genius Vue interface and provides a Python/FastAPI API, a Celery worker, PostgreSQL system storage, and RabbitMQ task delivery. The isolated S14 Compose stack serves the UI and `/api` through one Nginx entry point on `http://localhost:8109` by default. This machine’s acceptance stack uses host port `18109`; this is a local test setting, not the default.

当前中文交付范围、验收结果和模型/外部环境限制见[交付说明](docs/phase-15-acceptance/交付说明.md)。

## Local container stack

Copy `.env.example` to a local ignored env file, then replace every `REPLACE_*` value. The backend startup wrapper percent-encodes raw PostgreSQL and RabbitMQ credentials in memory, so passwords may contain reserved URL characters such as `@`, `:`, and `/`. Generate the 32-character encryption key with `python -c "import secrets; print(secrets.token_hex(16))"`; use different generated values for both passwords.

```powershell
Copy-Item .env.example .env.s14
# Edit .env.s14 and replace each placeholder.
# For this local validation stack, set SQLCHAT_STORAGE_BACKEND=local.
docker compose --project-name sqlchat-s14-test --env-file .env.s14 -f docker-compose.yml up --build -d
docker compose --project-name sqlchat-s14-test --env-file .env.s14 -f docker-compose.yml exec api python deploy/connection_env.py python -m app.services.bootstrap
```

The one-shot `migrate` service runs `alembic upgrade head` before the API and worker start. The one-shot `metrics-init` service starts a fresh Prometheus multiprocess epoch before either application process starts. PostgreSQL, RabbitMQ, uploaded files, and process metrics use separate named volumes scoped to the explicit `sqlchat-s14-test` project. The database and broker have no published host ports; the frontend binds to loopback port 8109. To stop the stack without deleting persistent data, run `docker compose --project-name sqlchat-s14-test --env-file .env.s14 -f docker-compose.yml stop`. The named volumes remain while stopped; a later whole-stack `up` runs `metrics-init` again and starts a new metrics epoch.

The legacy `GET /api/health` remains available. `GET /api/health/live` checks that the API process responds; `GET /api/health/ready` returns 200 only when PostgreSQL and RabbitMQ are available, otherwise 503. The external metrics URL is `GET /api/metrics` through Nginx. The backend also serves a direct-container `GET /metrics` alias, which the frontend Nginx does not expose at its root. This metrics layout supports one API container and one Worker container per stack; Worker prefork children share the worker directory. Do not use `docker compose --scale` for API or Worker because distinct containers can reuse PID values in the same service directory. API and worker write to separate subdirectories under the shared metrics volume; active processes hold a shared lifecycle lock, and the initializer refuses to clear files while either is running. Old worker PID files remain within an epoch, so use task-before/task-after counter deltas. A whole-stack plain `stop`/`up` reruns `metrics-init` and starts a new epoch; the S14 runtime observation recorded metric-file removal and a counter reset. Restarting only the API or Worker does not run the initializer. For a deterministic explicit new epoch before an upgrade, stop API and Worker and remove the completed `metrics-init` container before starting the stack; persistent data volumes remain. See [deployment operations](docs/phase-14-deploy/README.md). The model API key is blank in the example; configure `SQLCHAT_DEFAULT_MODEL_API_KEY` or app model settings before using model features.

## File storage, OCR and trial configuration

Compose reads the storage and OCR options from the env file for both API and worker. The default `SQLCHAT_STORAGE_BACKEND=oss` preserves the production file chain. Set `SQLCHAT_OSS_ENDPOINT`, `SQLCHAT_OSS_BUCKET`, `SQLCHAT_OSS_ACCESS_KEY_ID` and `SQLCHAT_OSS_ACCESS_KEY_SECRET` to the bucket endpoint, bucket name and credentials. Missing OSS configuration raises an error on file access; it does not switch storage automatically.

For development or this isolated deployment test, set `SQLCHAT_STORAGE_BACKEND=local` explicitly. Keep `SQLCHAT_STORAGE_ROOT=/app/uploads` to use the shared persistent uploads volume. Changing this path also requires a matching API/worker volume mount.

Image text recognition requires `SQLCHAT_OCR_ENABLED=true`, `SQLCHAT_OCR_ENDPOINT`, `SQLCHAT_OCR_ACCESS_KEY_ID` and `SQLCHAT_OCR_ACCESS_KEY_SECRET`. Configure this separate OCR credential group with access to Aliyun RecognizeAdvanced. With OCR disabled, image recognition reports an explicit service error. Actual OSS/OCR acceptance still requires working service credentials; local storage tests do not verify those services.

Trial mode is optional: set `SQLCHAT_TRIAL_ENABLED=true` and configure `SQLCHAT_TRIAL_BUILTIN_HOST`, `SQLCHAT_TRIAL_BUILTIN_PORT`, `SQLCHAT_TRIAL_BUILTIN_DB_NAME`, `SQLCHAT_TRIAL_BUILTIN_USERNAME` and `SQLCHAT_TRIAL_BUILTIN_PASSWORD` for the built-in MySQL database. Trial permissions apply to the API and worker, including rejection of writes and file upload.

## Context and execution limits

The env example exposes cross-turn compression (`SQLCHAT_CONTEXT_AUTO_COMPRESS_*`, `SQLCHAT_CONTEXT_KEEP_LAST_MESSAGES`), observation elision, step summaries, stale reasoning discard, repeated-call limits and tool output/artifact limits. `SQLCHAT_TOOL_OUTPUT_MAX_ROWS` controls result rows; `SQLCHAT_TOOL_OUTPUT_PER_TOOL_MAX_CHARACTERS` optionally accepts `executeSql=1000,readFile=5000` or a JSON object to override individual tools. Leaving it empty preserves the global character limit. Compose forwards these options to API and worker with the Settings defaults. Automatic cross-turn compression is off by default; observation elision and step summaries are on. Session expiry, SQL timeout/row limits and each workflow's maximum steps are also configurable without editing Compose.

Nginx proxies `/api` to the API on port 8109 with response buffering disabled, a one-hour read timeout, a 21 MiB transport limit to leave multipart overhead above the API's 20 MiB file limit, and client-abort propagation. Its access log records the request path without query parameters. API and worker logs use the backend redaction filter, and container logs have rotation limits. This Compose file is an isolated local validation stack; production deployments should use a managed secret store, TLS termination, backups, and an explicitly reviewed exposure policy.

## Upgrade and rollback

Before an upgrade, back up the PostgreSQL system database and the encryption key together; existing saved database/model credentials cannot be recovered without the original key. Keep the PostgreSQL, RabbitMQ, uploads, and metrics named volumes. For a deterministic new metrics epoch, stop API and Worker and remove the completed `metrics-init` container before rebuilding/upgrading; the initializer can then run while persistent data volumes are preserved. A whole-stack plain `stop`/`up` also reruns the initializer; restarting only API or Worker does not. The one-shot migration runs before API and worker startup on `up`; check the API readiness endpoint and worker health before directing users to the stack.

For a temporary stop that preserves data, use the `stop` command above. The current metrics epoch remains in the named volume while the stack is stopped, but the next whole-stack `up` reruns `metrics-init` and starts a new epoch. `docker compose down` also preserves named volumes unless `--volumes` is explicitly supplied. Do not use `down --volumes` as an upgrade or rollback step. If an upgrade fails, stop the affected stack and restore the prior application version with the matching database backup when its schema is incompatible; this project does not promise automatic schema downgrade or data rollback.

## Deployment checks

Run deployment contract tests with `node --test tests/s14-deployment-contract.test.mjs` and the backend boundary tests with `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_deploy_connection_env.py backend/tests/test_deploy_metrics_init.py backend/tests/test_file_upload.py`. Validate Compose with `docker compose --project-name sqlchat-s14-test --env-file .env.example -f docker-compose.yml config --quiet`. Build images with the same `docker compose` prefix followed by `build`; these checks do not start services or remove volumes.

Deployment details and evidence are tracked in [docs/phase-14-deploy/README.md](docs/phase-14-deploy/README.md).
