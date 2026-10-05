#!/bin/bash
# Sourced by the official MySQL entrypoint on an empty data directory only.
set -e

[[ "$TRIAL_DATABASE" =~ ^[A-Za-z][A-Za-z0-9_-]{0,31}$ ]] || { echo 'Invalid TRIAL_DATABASE' >&2; exit 1; }
[[ "$TRIAL_USERNAME" =~ ^[A-Za-z][A-Za-z0-9_-]{0,31}$ && "${TRIAL_USERNAME,,}" != root ]] || { echo 'Invalid TRIAL_USERNAME' >&2; exit 1; }
[[ "$TRIAL_PASSWORD" =~ ^[0-9a-fA-F]{32,64}$ ]] || { echo 'TRIAL_PASSWORD must be hexadecimal' >&2; exit 1; }

docker_process_sql <<SQL
CREATE DATABASE IF NOT EXISTS \`$TRIAL_DATABASE\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER '$TRIAL_USERNAME'@'%' IDENTIFIED BY '$TRIAL_PASSWORD';
GRANT SELECT, SHOW VIEW ON \`$TRIAL_DATABASE\`.* TO '$TRIAL_USERNAME'@'%';
SQL
docker_process_sql --database="$TRIAL_DATABASE" < /opt/sqlchat-demo.sql
