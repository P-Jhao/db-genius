# S14 Deployment and Operations

Status: isolated candidate exported from accepted source HEAD 93175f927beb517beb8992b3ade3486d0a7abf53 (including the accepted queue-redaction, native SQL error-repair, and OCR/workflow typing changes); the frontend tree is byte-for-byte unchanged from accepted S13 commit 62c19bb7096e397e53008ff2e235286d396e18a3. This temporary snapshot is not merged into the shared worktree. Runtime acceptance applies only after root combines the accepted S15 backend payload with this S14 allowlist and rebuilds the exact images.

## Topology and port exposure

Compose starts postgres, rabbitmq, migrate, metrics-init, api, worker, and frontend. The one-shot migrate service waits for PostgreSQL health and runs Alembic before API and worker start. The one-shot metrics initializer starts a new Prometheus multiprocess epoch only after acquiring the exclusive lifecycle lock. API and worker wait for both one-shot services and for PostgreSQL and RabbitMQ health. Frontend starts after API readiness.

The browser enters Nginx on loopback port 8109. Nginx forwards /api traffic to api:8109. PostgreSQL and RabbitMQ do not publish host ports. PostgreSQL, RabbitMQ, and uploaded local files use separate named volumes. API and worker share the uploads volume. Compose logs have bounded size and rotation.

The frontend build uses only public arguments: VITE_API_BASE_URL=/api and VITE_GITHUB_REPO. It receives no API key, encryption key, administrator password, object-storage credential, or OCR credential.

## Health and metrics contract

The legacy GET /api/health response remains available. S15 adds:

- GET /api/health/live: HTTP 200 when the API process can answer.
- GET /api/health/ready: HTTP 200 only when the PostgreSQL and RabbitMQ checks are UP; HTTP 503 when either dependency is DOWN. The response must not include a connection URL or diagnostic secret.
- GET /api/metrics is the canonical external metrics URL through the frontend Nginx proxy; GET /metrics is a direct API-container alias and is not exposed at the frontend root. Both backend routes return Prometheus text from the same handler, without the application R envelope. The API collects separate `/var/lib/sqlchat/prometheus/api` and `/var/lib/sqlchat/prometheus/worker` directories so API and worker PID namespaces cannot collide.

Compose probes /api/health/ready with a 10-second client request timeout and a 30-second container health timeout. The backend's staged PostgreSQL and broker I/O budgets are 3 and 2 seconds. These are per-stage limits, not a strict overall HTTP deadline.

The Worker healthcheck builds the same database and broker URLs as `deploy/connection_env.py` within one Python process, imports the Celery app, then calls `ping(timeout=3)`. A ping with no worker reply remains unhealthy. The 12-second container timeout covers the root's measured 9.4078-second cold probe (2.3301 seconds for app import and 3.1491 seconds for ping) with about 2.59 seconds of margin.

RabbitMQ 4.3 requires the S15 Celery configuration to keep control_queue_durable and event_queue_durable enabled while preserving the existing TTL/expiry and locale headers. Worker ping and readiness are meaningful only after that accepted backend change is present.

The metrics layout supports one API container and one Worker container per stack; Worker prefork children share the worker subdirectory. Do not scale either Compose service: multiple containers can reuse the same PID values in a shared service directory and collide. API and worker write to different subdirectories under one named volume. Each process holds a shared lifecycle lock while running. `metrics-init` takes that lock exclusively and exits with an error if either application process is alive; it deletes only recognized counter/histogram `.db` files inside the `api` and `worker` directories. It does not remove the lock file, recurse into unrelated paths, or run inside an API/worker restart. Dead-process metric files therefore accumulate within one stack epoch; use task-before/task-after counter deltas for job evidence. Root's plain `stop` followed by `up -d --no-build --wait` observation showed that this sequence reruns `metrics-init` and starts a new epoch: the initializer container ID stayed the same while StartedAt changed, its log removed 11 API and 5 Worker metric files, and the business counter total fell from 70 to 0. The [public epoch observation record](../phase-14-main/main-plain-start-epoch-observation.json) documents those removals and counter reset; it records `deploymentStartupPassed: false` for the earlier 8-second attempt and does not establish that the health-budgeted stack started successfully. A single `restart api` or `restart worker` does not rerun the initializer; compare its ID and StartedAt and confirm the other service's files remain. A deliberate removal of the completed initializer while API and worker are stopped remains a deterministic way to force a new epoch, but is not the only operation observed to start one.

## Nginx transport and file limits

The API proxy keeps the /api prefix and uses HTTP/1.1. Response and request buffering and proxy cache are disabled. A browser disconnect closes the upstream request. Read and send timeouts are one hour, above the 15-second SSE keepalive. Nginx logs the URI without the query string.

The proxy request cap is 21 MiB to allow multipart overhead. The application still enforces the 20 MiB single-file limit. This transport margin does not increase the product upload limit.

## Locked builds and secrets

The frontend package manager is pnpm 11.1.3. The Dockerfile copies package.json, pnpm-lock.yaml, and pnpm-workspace.yaml before running pnpm install --frozen-lockfile. The workspace build policy allows only @parcel/watcher; do not disable this policy or regenerate the lockfile to make builds pass.

The backend Dockerfile copies pyproject.toml and uv.lock and uses uv sync --frozen --no-dev. Keep those S15-owned inputs from the root-combined accepted payload; this candidate did not copy or edit them.

Copy .env.example to a local ignored .env.s14 file and replace all placeholders. The deploy helper constructs database and broker URLs in process memory and URL-encodes reserved characters. It does not print those URLs. SQLCHAT_ENCRYPT_KEY must be exactly 32 UTF-8 bytes; back it up with the database. The default model key is blank. Local tests explicitly select SQLCHAT_STORAGE_BACKEND=local; production OSS remains the default and does not silently fall back to local. OSS and OCR need their own configured credentials.

The supported frontend/database families remain enabled. No dedicated live TiDB, Doris, StarRocks, or OceanBase instance was available in this validation window; keep these as implemented, with protocol/adapter evidence separate from real-instance acceptance. Real OSS and OCR services also remain unverified without service credentials; mock or local-storage tests do not prove those external services.

## Run, upgrade, and rollback

For an isolated local run, copy the env example, set a local storage root, then use the same project name and env file for all commands. Validate config before starting:

    Copy-Item .env.example .env.s14
    # Edit .env.s14; set SQLCHAT_STORAGE_BACKEND=local for this test deployment.
    docker compose --project-name sqlchat-s14-test --env-file .env.s14 -f docker-compose.yml config --quiet
    docker compose --project-name sqlchat-s14-test --env-file .env.s14 -f docker-compose.yml up --build -d
    docker compose --project-name sqlchat-s14-test --env-file .env.s14 -f docker-compose.yml exec api python deploy/connection_env.py python -m app.services.bootstrap
    docker compose --project-name sqlchat-s14-test --env-file .env.s14 -f docker-compose.yml ps

Use GET /api/health/live for process liveness and GET /api/health/ready for dependency readiness. Never print the resolved Compose configuration when real credentials are loaded. The test project name isolates its network, containers, and named volumes from other Compose projects.

Before an upgrade, take a PostgreSQL backup and preserve the matching encryption key. Stop both API and worker, then remove the completed `metrics-init` container before rebuilding/upgrading when you need a deterministic explicit new metric epoch. A whole-stack plain `stop`/`up` also starts a new epoch as observed above; a single API or worker restart does not start the initializer and preserves the other process's active metric files. If the initializer cannot obtain its lock, keep existing data and resolve the running service before retrying. Apply the image/source update with Compose up; the migration service must complete before API and worker become healthy. Review health and application logs before routing users.

To stop without deleting persistent data, use docker compose stop. Compose down removes the project containers and network but leaves named volumes unless explicitly asked to remove them. Do not use down --volumes for routine deployment or rollback. If the new application is incompatible with a migrated schema, restore the prior application and its matching database backup together; this project does not claim automatic Alembic downgrade or data rollback.

## Tests and evidence boundaries

Static deployment checks:

- node --test tests/s14-deployment-contract.test.mjs checks Compose structure, loopback exposure, migration ordering, frontend secret isolation, health route/timeout, Nginx buffering, disconnect, and size limits. If Docker Compose is installed, it parses the example env config without starting services.
- `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_deploy_metrics_init.py` checks that the initializer removes only counter/histogram files in the two allowed service directories and leaves the epoch untouched when the exclusive lock is unavailable.
- backend/.venv/Scripts/python.exe -m pytest backend/tests/test_deploy_connection_env.py backend/tests/test_file_upload.py checks reserved-character URL encoding and the exact 20 MiB upload boundary.
- pnpm --config.verify-deps-before-run=false typecheck and build check the accepted S13 frontend from a separate candidate copy using a junction to the existing locked dependency tree; the commands do not install packages. See [candidate-freeze.md](candidate-freeze.md) for the exact runner and results.

T33 real-stack tests are backend/tests/test_deploy_proxy.py and tests/s14-browser-disconnect.mjs. They use a controlled local SSE provider to verify incremental delivery, concurrent ordinary API response, one persisted partial response after TCP/browser abort, and absence of later stream content. These prove proxy transport with a fixture, not live-model quality.

T32 real-stack tests cover migration-gated startup, API/worker readiness, a Rabbit/Celery background task, and data retention across an operator-controlled API/worker/PostgreSQL restart. The fixture never performs lifecycle operations itself. Its state file contains generated test resource IDs and content hashes only; it must be a new path inside the test acceptance directory.

S15 UI/T01 contrast tests use the same in-process mock HTTP API for original and candidate pages. They assert the ten-type selector, Mongo credential-pair validation, retryable unknown trial status, and trial read-only UI, then capture only those changed states at 1440x1000 and English. The accepted targeted runs and retained superseded-attempt evidence are listed in [ui-targeted-evidence.md](ui-targeted-evidence.md). A screenshot does not establish a live FastAPI result.

## Historical draft evidence, not acceptance of this candidate

The prior shared S14 draft reported successful image builds, 3 proxy/browser tests in 37.30 seconds, 2 worker/finalization tests in 58.33 seconds, and a prepare/restart/verify persistence sequence (1 test in 9.11 seconds and 1 in 8.29 seconds). Those records are retained from the prior draft. They do not identify or verify this exact accepted-base plus S15-merged image, so they are not a runtime pass for this candidate.

The read-only audit and UI source list are stored beside this document. [candidate-freeze.md](candidate-freeze.md) records the isolated static verification and remaining integration gates; the exact source-hash manifest is stored beside the candidate directory. Root must rebuild and rerun runtime acceptance on the final combined payload before describing T32/T33 or health as runtime-passed.

## T01 targeted UI comparison

The original Vue source remains read-only. The changed-state screenshots compare that original UI with accepted S13 UI under the same viewport, locale, and mock HTTP fixture. The database selector and Mongo-pair error are authorized S13 additions. The original UI did not have a type selector, and its generic required-field validation closes the dialog; reports must keep those differences explicit. Trial chat hides upload and comparison controls in the candidate; the original UI exposed its upload control. Unknown status now shows a retryable warning and keeps restricted actions closed.

Only these changed UI states are recaptured. The prior 36-image matrix is not rerun. Each screenshot is paired with actual click/API/permission assertions; mocked-browser results are labelled as such. The report records both source hashes and all screenshot hashes.

