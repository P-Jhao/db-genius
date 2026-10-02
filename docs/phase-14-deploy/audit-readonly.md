# S14 deployment audit (read-only)

**Audit date:** 2026-10-02  
**Accepted source reviewed:** sqlchat HEAD 93175f927beb517beb8992b3ade3486d0a7abf53 (including accepted queue-redaction, native SQL error-repair, and OCR/workflow typing changes; frontend source remains byte-for-byte equal to S13 commit 62c19bb7096e397e53008ff2e235286d396e18a3).  
**Audit source:** shared S14 deployment draft in the working tree. This report records source review only; it does not claim Compose parsing, image build, or container runtime acceptance.  
**Authority boundary:** this report was written outside the repository. It does not modify the shared working tree, accepted files, secrets, or container state.

## Requirements reviewed

- spec/06-数据访问安全与部署设计.md: 20 MiB application upload limit; separate Alembic step; separate liveness/readiness; durable PostgreSQL and local-upload storage; no unnecessary public DB/broker ports; proxy buffering disabled; client disconnect cancellation; bounded logs and no sensitive content.
- spec/07-测试与验收规范.md: T32 first start/restart and persistence; T33 Nginx incremental SSE, disconnect propagation and concurrent ordinary API; T01 visual comparison with matching viewport/language/data; distinguish mocked UI checks from real deployment checks.
- F18 (deployment and observability) and T32/T33 are the deployment acceptance focus. T34 route details remain S15-owned.

## Source findings

| Area | Read-only finding | Evidence status |
|---|---|---|
| Network and services | Draft Compose declares PostgreSQL 16, RabbitMQ 4.3.6, one-shot migrate, API, worker and frontend. DB and broker have no host-published ports; frontend is bound to loopback port 8109. API and worker depend on database/broker health and successful migration; frontend depends on API health. Named volumes cover PostgreSQL, RabbitMQ and uploads. | Source reviewed; docker compose config and runtime not run here. |
| Health | Accepted backend system router only exposes legacy /api/health. S15 confirmed its fresh payload will preserve that endpoint and add /api/health/live, /api/health/ready, /api/metrics, plus /metrics alias. Readiness is HTTP 200 only when both DB and broker are UP, otherwise 503 without diagnostic or URL disclosure. Compose must target /api/health/ready; do not claim readiness until the root-combined S15 payload is built and checked. Proposed container health timeout is 30s to cover the staged 3s PG + 2s broker checks with margin; these are I/O stage budgets, not a strict total HTTP deadline. |
| RabbitMQ 4.3 | S15 confirmed Celery control and event queues need control_queue_durable=True and event_queue_durable=True, while preserving configured TTL/expiry and S13 locale headers. API readiness and worker ping depend on this. | Requirement relayed to S15; only root's accepted merged backend can be runtime-verified. |
| Nginx and upload | Draft forwards /api/ to api:8109, retains the /api prefix, disables response/request buffering and cache, propagates client abort, and sets 3600s read/send timeouts. The SSE heartbeat draft is 15s. client_max_body_size 21m is above the 20 MiB application file cap to allow multipart overhead. | Config reviewed; incremental stream, abort, and max-upload boundary not rerun here. |
| Frontend build | Package manager is pinned to pnpm 11.1.3; Docker uses pnpm install --frozen-lockfile. It copies package.json, pnpm-lock.yaml, and pnpm-workspace.yaml before installation so allowBuilds is applied; that allowlist permits only @parcel/watcher. Vite dev proxy defaults to 127.0.0.1:8109, and production VITE_API_BASE_URL is /api. | Source reviewed; frozen install/build unverified in this audit. |
| Python build | Draft backend Dockerfile copies pyproject.toml and uv.lock and runs uv sync --frozen --no-dev. Do not overlay S15-owned dependency files. | Source reviewed; clean image build must use the root-combined accepted dependency set. |
| Secret boundary | Root .env.example contains placeholders only. Root .env/.env.s14 are ignored. Frontend build receives only public Vite build args; Nginx logs $uri, not query parameters. The frontend .dockerignore excludes .env* except the public .env.example. Backend and frontend build contexts are separate. | No secret file was opened or copied. Compose resolution and built-image inspection remain unverified. |
| URL credentials | backend/deploy/connection_env.py encodes DB and Rabbit credentials in process memory and does not log the URL. The .env.example placeholder says URL_SAFE while README says reserved characters such as @:/ are supported; align the placeholder wording so operators do not infer a narrower contract. | Source/test reviewed; URL-encoding test not run here. |
| Run docs | Root README includes isolated project commands and says stop preserves named volumes. The two-phase persistence test requires operator-controlled API/worker/PostgreSQL restart and explicitly checks all three StartedAt values; fixtures do not perform restart/stop/recreate. | Docs and test source reviewed; container lifecycle remains root-controlled. |
| Stale frontend docs | frontend/README.md still documents dev and production upstream port 8000. Current Vite proxy and Nginx upstream use 8109. Correct this as part of S14 docs. | Confirmed by direct source review. |
| Compose environment | The Compose draft maps SQLCHAT_TOOL_OUTPUT_MAX_ROWS; accepted HEAD config uses tool_output_max_rows. Shared unaccepted core/config.py draft uses tool_output_max_lines; do not copy that draft into this snapshot. | Accepted source contract checked with git show HEAD. |

## Minimal candidate overlay

Start from a fresh archive of accepted HEAD 62c19bb, then overlay only the S14 allowlist: root docker-compose.yml, .env.example, README.md; frontend Dockerfile, .dockerignore, nginx.conf, and corrected README.md; backend Dockerfile, .dockerignore, and deployment-only backend/deploy helpers; deployment contract/browser tests and narrowly scoped deploy fixtures; docs/phase-14-deploy. Add no S13 business changes or S15-owned backend/app/main.py, core, tasks/celery_app.py, pyproject.toml, or uv.lock. Keep native database adapter and registry files out (S10-owned).

## Required validation before any runtime-passed claim

1. Review the SHA manifest for the fresh candidate and confirm the allowlist has no overwritten ownership.
2. Run Node source-contract tests and Python URL-encoding/upload boundary tests on the candidate.
3. Parse Compose with .env.example using docker compose config --quiet; never print or persist resolved secret values.
4. After root merges S15 health and durable-queue changes, build the exact merged image and verify /api/health/live, readiness UP and DOWN, /api/metrics and /metrics.
5. In root-coordinated isolated runtime, verify T32 migration/API/worker readiness and persistence across an operator restart; verify T33 incremental SSE, aborted-client propagation, and concurrent ordinary API. The controlled model fixture proves transport only, not live-model accuracy.
6. Capture only changed T01 states (database type selector/validation and trial UI); do not rerun unchanged 36-image matrix. Screenshots complement click/network/permission assertions and do not replace them.

## Explicit limits

No Docker command, Compose lifecycle operation, Node/Python test, pnpm install, container restart, or cleanup was run as part of this read-only audit. Existing S14 draft test summaries are reported claims, not independently accepted results.
