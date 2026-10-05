#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

if [[ $# -ne 1 || ! $1 =~ ^[0-9a-f]{40}$ ]]; then
    echo 'Usage: bash deploy-on-server.sh <full lowercase 40-character commit SHA>' >&2
    exit 2
fi

readonly deploy_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly env_file="${deploy_dir}/.env.production"
readonly compose_file="${deploy_dir}/docker-compose.prod.yml"
export SQLCHAT_IMAGE_TAG="$1"

for executable in docker curl gzip flock python3; do
    command -v "$executable" >/dev/null || { echo "Missing executable: $executable" >&2; exit 1; }
done
[[ -f "$env_file" && -f "$compose_file" ]] || {
    echo 'Place .env.production and docker-compose.prod.yml beside this script before deploying.' >&2
    exit 1
}
if grep -Eq '^[[:space:]]*[A-Z_][A-Z_0-9]*=.*REPLACE_' "$env_file"; then
    echo 'Replace all REPLACE_* environment placeholders before deploying.' >&2
    exit 1
fi
chmod 600 "$env_file"
exec 9>"${deploy_dir}/.deploy.lock"
flock -n 9 || { echo 'Another SQLChat deployment is running.' >&2; exit 1; }

# Preserve a caller-supplied DOCKER_CONFIG for temporary private GHCR authentication.
compose=(docker compose -p sqlchat-prod -f "$compose_file" --env-file "$env_file")
"${compose[@]}" version >/dev/null
"${compose[@]}" config --quiet
# Compose parses dotenv values; never source the operator's configuration as shell code.
[[ -f "${deploy_dir}/trial-mode.py" ]] || { echo 'Missing trial-mode.py' >&2; exit 1; }
trial_mode=$("${compose[@]}" --profile trial-demo config --format json | python3 "${deploy_dir}/trial-mode.py")
if [[ "$trial_mode" == local ]]; then
    for asset in docker-compose.trial.yml trial-mysql/10-demo.sh trial-mysql/demo.sql; do
        [[ -f "${deploy_dir}/$asset" ]] || { echo "Missing deployment asset: $asset" >&2; exit 1; }
    done
    compose+=(-f "${deploy_dir}/docker-compose.trial.yml" --profile trial-demo)
    "${compose[@]}" config --quiet
fi

deployment_failed() {
    local exit_code=$?
    echo 'Deployment failed; persistent volumes are retained. Inspect SQLChat services before retrying.' >&2
    "${compose[@]}" ps --all >&2 || true
    exit "$exit_code"
}
trap deployment_failed ERR

wait_healthy() {
    local service=$1 deadline=$((SECONDS + 360)) container_id health state
    while (( SECONDS < deadline )); do
        container_id=$("${compose[@]}" ps --all -q "$service")
        if [[ -n "$container_id" ]]; then
            state=$(docker inspect --format '{{.State.Status}}' "$container_id")
            health=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' "$container_id")
            if [[ "$state" == running && "$health" == healthy ]]; then
                return
            fi
            if [[ "$state" == exited || "$state" == dead || "$health" == unhealthy || "$health" == missing ]]; then
                echo "Service $service failed its health gate (state=$state, health=$health)." >&2
                return 1
            fi
        fi
        sleep 5
    done
    echo "Timed out waiting for healthy service: $service" >&2
    return 1
}

verify_one_shot() {
    local service=$1 container_id state exit_code
    container_id=$("${compose[@]}" ps --all -q "$service")
    [[ -n "$container_id" ]] || { echo "Missing one-shot service: $service" >&2; return 1; }
    state=$(docker inspect --format '{{.State.Status}}' "$container_id")
    exit_code=$(docker inspect --format '{{.State.ExitCode}}' "$container_id")
    [[ "$state" == exited && "$exit_code" == 0 ]] || {
        echo "One-shot $service did not complete successfully (state=$state, exit=$exit_code)." >&2
        return 1
    }
}

echo "Pulling release ${SQLCHAT_IMAGE_TAG} before stopping application services."
existing_postgres=$("${compose[@]}" ps --all -q postgres)
existing_api=$("${compose[@]}" ps --all -q api)
"${compose[@]}" pull
if ! docker network inspect --format '{{.Name}}' promptforge_promptforge >/dev/null; then
    echo 'Required external network promptforge_promptforge is missing or inaccessible; SQLChat services have not been stopped.' >&2
    exit 1
fi
# Cold-start the capped demo database before interrupting the current application.
# Failure must leave the old frontend/API/Worker running. Only stop a newly created
# demo container on failure; never remove its volume or stop an existing demo here.
if [[ "$trial_mode" == local ]]; then
    existing_demo=$("${compose[@]}" ps --all -q trial-mysql)
    if ! "${compose[@]}" up -d --no-build --no-deps trial-mysql || ! wait_healthy trial-mysql; then
        echo 'Demo MySQL failed pre-maintenance; existing application services have not been stopped.' >&2
        if [[ -z "$existing_demo" ]]; then
            "${compose[@]}" stop -t 60 trial-mysql
        fi
        exit 1
    fi
fi
echo 'Entering maintenance: active requests/tasks may be interrupted; API/Worker get 180 seconds to stop.'
"${compose[@]}" stop -t 180 frontend api worker

# Profile changes do not stop already-created services automatically. Retain the volume.
if [[ "$trial_mode" != local ]]; then
    docker compose -p sqlchat-prod -f "$compose_file" --env-file "$env_file" \
        --profile trial-demo stop -t 60 trial-mysql
fi

if [[ -n "$existing_postgres" ]]; then
    # Start the existing container, preserving its original image and configured credentials.
    "${compose[@]}" start postgres
    wait_healthy postgres
    backup_dir="${deploy_dir}/backups/$(date -u +%Y%m%dT%H%M%SZ)-${SQLCHAT_IMAGE_TAG}"
    mkdir -m 700 -p "$backup_dir"
    echo 'Backing up PostgreSQL and matching environment. Keep an off-server copy; backups are never auto-deleted.'
    "${compose[@]}" exec -T postgres sh -c 'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom' \
        | gzip >"${backup_dir}/postgres.dump.gz.partial"
    mv -- "${backup_dir}/postgres.dump.gz.partial" "${backup_dir}/postgres.dump.gz"
    cp -- "$env_file" "${backup_dir}/.env.production"
    printf '%s\n' "$SQLCHAT_IMAGE_TAG" >"${backup_dir}/target-image-tag"
    if [[ -n "$existing_api" ]]; then
        docker inspect --format '{{.Config.Image}}' "$existing_api" >"${backup_dir}/source-backend-image"
    fi
    echo "Backup saved: $backup_dir"
fi

# Both application writers are stopped before starting a fresh metrics epoch.
# Removing only the completed one-shot containers deterministically reruns migration/init.
"${compose[@]}" rm --stop --force migrate metrics-init
"${compose[@]}" up -d --no-build

for service in postgres rabbitmq api worker frontend; do
    wait_healthy "$service"
done
verify_one_shot migrate
verify_one_shot metrics-init

# docker exec does not inherit URLs constructed in the entrypoint process.
"${compose[@]}" exec -T api python deploy/connection_env.py python -m app.services.bootstrap
if [[ "$trial_mode" != off ]]; then
    # On a fresh install the API lifespan ran before the bootstrap account existed.
    "${compose[@]}" exec -T api python deploy/connection_env.py python -c \
        'from app.core.database import SessionLocal; from app.services.db_config_init import initialize_trial_database; session = SessionLocal(); initialize_trial_database(session); session.close()'
fi
"${compose[@]}" exec -T frontend sh -c 'wget -q -O /dev/null http://127.0.0.1/api/health/ready'
published_address=$("${compose[@]}" port frontend 80)
[[ "$published_address" =~ ^127\.0\.0\.1:[0-9]+$ ]] || {
    echo 'Expected a loopback-only frontend published port.' >&2
    exit 1
}
curl --fail --silent --show-error --max-time 15 "http://${published_address}/api/health/ready" >/dev/null
"${compose[@]}" ps --all
printf '%s\n' "$SQLCHAT_IMAGE_TAG" >"${deploy_dir}/.deployed-image-tag"
echo "SQLChat release ${SQLCHAT_IMAGE_TAG} is healthy at http://${published_address}."
