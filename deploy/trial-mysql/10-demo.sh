#!/bin/bash
# Invoked by the official MySQL entrypoint on an empty data directory only.
set -e

# Windows bind mounts may mark this file executable, so entrypoint runs a child
# shell instead of sourcing it. Load functions only; the official source guard
# prevents main() from running and recursively initializing the server.
if ! declare -F docker_process_sql >/dev/null; then
    source /usr/local/bin/docker-entrypoint.sh
    declare -F docker_process_sql >/dev/null || { echo 'MySQL SQL helper unavailable' >&2; exit 1; }
    SOCKET="$(mysql_get_config 'socket' mysqld)"
fi

[[ "$TRIAL_DATABASE" =~ ^[A-Za-z][A-Za-z0-9_-]{0,31}$ ]] || { echo 'Invalid TRIAL_DATABASE' >&2; exit 1; }
[[ "$TRIAL_USERNAME" =~ ^[A-Za-z][A-Za-z0-9_-]{0,31}$ && "${TRIAL_USERNAME,,}" != root ]] || { echo 'Invalid TRIAL_USERNAME' >&2; exit 1; }
[[ "$TRIAL_PASSWORD" =~ ^[0-9a-fA-F]{32,64}$ ]] || { echo 'TRIAL_PASSWORD must be hexadecimal' >&2; exit 1; }

docker_process_sql --default-character-set=utf8mb4 <<SQL
CREATE DATABASE IF NOT EXISTS \`$TRIAL_DATABASE\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER '$TRIAL_USERNAME'@'%' IDENTIFIED BY '$TRIAL_PASSWORD';
GRANT SELECT, SHOW VIEW ON \`$TRIAL_DATABASE\`.* TO '$TRIAL_USERNAME'@'%';
SQL
docker_process_sql --default-character-set=utf8mb4 --database="$TRIAL_DATABASE" < /opt/sqlchat-demo.sql
docker_process_sql --default-character-set=utf8mb4 --database="$TRIAL_DATABASE" < /opt/sqlchat-seed.sql
