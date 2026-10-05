#!/usr/bin/env bash
# Exercise the real deployment wrapper against a Docker stub; no containers/network.
set -Eeuo pipefail
readonly source_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
readonly fixture_dir="$(mktemp -d /tmp/sqlchat-trial-lifecycle.XXXXXX)"
[[ "$fixture_dir" == /tmp/sqlchat-trial-lifecycle.* ]] || exit 2
trap 'rm -rf -- "$fixture_dir"' EXIT
mkdir -p "$fixture_dir/bin" "$fixture_dir/trial-mysql"
cp "$source_dir/deploy-on-server.sh" "$source_dir/trial-mode.py" \
   "$source_dir/docker-compose.prod.yml" "$source_dir/docker-compose.trial.yml" "$fixture_dir/"
cp "$source_dir/trial-mysql/10-demo.sh" "$source_dir/trial-mysql/demo.sql" "$source_dir/trial-mysql/seed.sql" "$source_dir/trial-mysql/healthcheck.sh" "$fixture_dir/trial-mysql/"
printf '%s\n' '# Disposable no-secret fixture; never used by a real Docker daemon.' > "$fixture_dir/.env.production"
cat > "$fixture_dir/bin/docker" <<'STUB'
#!/usr/bin/env bash
set -eu
printf '%s\n' "$*" >> "$FIXTURE_DIR/calls"
case "$*" in
  *'config --format json') cat "$FIXTURE_DIR/config.json";;
  *'ps --all -q trial-mysql') [[ ! -f "$FIXTURE_DIR/started" ]] || echo fixture-demo;;
  *'ps --all -q '*|*'ps --all') ;;
  *'up -d --no-build --no-deps trial-mysql')
    [[ "$SCENARIO" != start-failure ]] || exit 22
    touch "$FIXTURE_DIR/started";;
  'inspect --format {{.State.Status}} fixture-demo') echo running;;
  'inspect --format {{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}} fixture-demo')
    if [[ "$SCENARIO" == *health-failure ]]; then echo unhealthy; else echo healthy; fi;;
  *'up -d --no-build') exit 66;; # Stop before application startup; ordering is the assertion.
esac
STUB
chmod 700 "$fixture_dir/bin/docker"
export FIXTURE_DIR="$fixture_dir"
export PATH="$fixture_dir/bin:$PATH"
for SCENARIO in start-failure health-failure existing-health-failure healthy off; do
    export SCENARIO
    rm -f -- "$fixture_dir/started" "$fixture_dir/calls"
    if [[ "$SCENARIO" == existing-health-failure ]]; then touch "$fixture_dir/started"; fi
    if [[ "$SCENARIO" == off ]]; then enabled=false; else enabled=true; fi
    python3 - "$enabled" "$fixture_dir/config.json" <<'PY'
import json
import sys
api = {"SQLCHAT_TRIAL_ENABLED": sys.argv[1], "SQLCHAT_TRIAL_BUILTIN_DB_NAME": "db-genius",
       "SQLCHAT_TRIAL_BUILTIN_HOST": "trial-mysql", "SQLCHAT_TRIAL_BUILTIN_PORT": "3306",
       "SQLCHAT_TRIAL_BUILTIN_USERNAME": "sqlchat_demo", "SQLCHAT_TRIAL_BUILTIN_PASSWORD": "a" * 48}
demo = {"MYSQL_ROOT_PASSWORD": "b" * 48, "TRIAL_PASSWORD": "a" * 48}
with open(sys.argv[2], "w", encoding="utf-8") as stream:
    json.dump({"services": {"api": {"environment": api}, "trial-mysql": {"environment": demo}}}, stream)
PY
    if bash "$fixture_dir/deploy-on-server.sh" 0000000000000000000000000000000000000000 \
      > "$fixture_dir/output" 2>&1; then
        echo "Expected a deliberate stub failure: $SCENARIO" >&2
        exit 1
    fi
    python3 - "$SCENARIO" "$fixture_dir/calls" <<'PY'
from pathlib import Path
import sys
scenario = sys.argv[1]
calls = Path(sys.argv[2]).read_text().splitlines()
app_stop = [index for index, call in enumerate(calls) if "stop -t 180 frontend api worker" in call]
db_stop = [index for index, call in enumerate(calls) if "stop -t 60 trial-mysql" in call]
db_start = [index for index, call in enumerate(calls) if "up -d --no-build --no-deps trial-mysql" in call]
if scenario in {"start-failure", "health-failure"}:
    assert not app_stop, "Old application was stopped despite demo preflight failure"
    assert len(db_stop) == 1, "New failed demo was not stopped"
elif scenario == "healthy":
    health = [index for index, call in enumerate(calls) if ".State.Health" in call]
    assert len(app_stop) == 1 and db_start[0] < health[0] < app_stop[0]
    assert not db_stop
elif scenario == "existing-health-failure":
    assert not app_stop and not db_stop, "Preflight stopped existing services"
else:
    assert not db_start and len(app_stop) == len(db_stop) == 1
    assert app_stop[0] < db_stop[0], "Trial DB stopped before application maintenance"
print(f"{scenario}: lifecycle assertions passed")
PY
done
