"""S13 dedicated SQL fixtures; credentials remain inside subprocesses."""

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from time import monotonic
from urllib.parse import quote, quote_plus


def target(name: str, prefix: str, port: int, internal_port: str,
           database_key: str, password_key: str, username_key: str | None) -> tuple[dict[str, str], str]:
    result = subprocess.run(["docker", "inspect", name], capture_output=True, text=True, check=True)
    container = json.loads(result.stdout)[0]
    if container["State"]["Running"] is not True:
        raise RuntimeError("Dedicated SQL target is not running")
    bindings = container["NetworkSettings"]["Ports"].get(internal_port)
    if not isinstance(bindings, list) or not any(
        item["HostPort"] == str(port) and item["HostIp"] in {"127.0.0.1", "::1"} for item in bindings
    ):
        raise RuntimeError("Dedicated SQL target has unexpected binding")
    values = dict(item.split("=", 1) for item in container["Config"]["Env"])
    username = "root" if username_key is None else values[username_key]
    password = values[password_key]
    environment = {f"{prefix}_{key}": value for key, value in {
        "HOST": "127.0.0.1", "PORT": str(port), "DB": values[database_key],
        "USER": username, "PASSWORD": password,
    }.items()}
    return environment, password


def run() -> int:
    root = Path(__file__).resolve().parents[2]
    environment = {**os.environ, "PYTHONPATH": str(root / "backend")}
    targets = [
        ("sqlchat-migration-test-postgres", "SQLCHAT_TEST_PG", 15432, "5432/tcp",
         "POSTGRES_DB", "POSTGRES_PASSWORD", "POSTGRES_USER"),
        ("sqlchat-migration-test-mysql", "SQLCHAT_TEST_MYSQL", 13306, "3306/tcp",
         "MYSQL_DATABASE", "MYSQL_ROOT_PASSWORD", None),
    ]
    passwords = []
    for arguments in targets:
        variables, password = target(*arguments)
        environment.update(variables)
        passwords.append(password)
    command = [sys.executable, "-m", "pytest", "tests/test_trial_targets.py", "tests/test_trial_graph_targets.py", "-q"]
    started = monotonic()
    result = subprocess.run(command, cwd=root / "backend", env=environment,
                            capture_output=True, text=True, check=False)
    output = result.stdout + result.stderr
    passed = re.search(r"(\d+) passed", output)
    skipped = re.search(r"(\d+) skipped", output)
    for password in passwords:
        if password:
            for secret in {password, repr(password)[1:-1], json.dumps(password)[1:-1],
                           quote(password, safe=""), quote_plus(password)}:
                output = output.replace(secret, "[REDACTED]")
    print(output, end="")
    files = ["backend/app/agent/dsml.py", "backend/app/agent/streaming.py", "backend/app/services/database_tools.py",
             "backend/app/adapters/relational.py", "backend/tests/test_trial_targets.py", "backend/tests/test_trial_graph_targets.py"]
    evidence = {
        "baseCommit": (root / "BASELINE").read_text().strip(),
        "kind": "real PG/MySQL trial side effects, production services and graph with controlled HTTP model",
        "command": "python -m pytest tests/test_trial_targets.py tests/test_trial_graph_targets.py -q",
        "passed": int(passed[1]) if passed else 0, "skipped": int(skipped[1]) if skipped else 0,
        "exitCode": result.returncode, "elapsedSeconds": round(monotonic() - started, 3),
        "postgresAppSchemaUsed": False, "containerLifecycleChanged": False,
        "actualModelTested": False, "syntheticFixturesOnly": True,
        "codeSha256": {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in files},
    }
    Path(__file__).with_name("real-trial-targets.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    return result.returncode


if __name__ == "__main__":
    try:
        raise SystemExit(run())
    except Exception as error:  # noqa: BLE001 - failed inspection never prints credentials
        print(f"Dedicated S13 regression failed: {type(error).__name__}")
        raise SystemExit(1) from None
