"""Run integrated dedicated synthetic Mongo checks without printing or saving credentials."""

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from time import monotonic
from urllib.parse import quote, quote_plus

from pymongo import MongoClient


def run() -> int:
    root = Path(__file__).resolve().parents[2]
    backend = root / "backend"
    inspection = subprocess.run(["docker", "inspect", "sqlchat-s12-mongo"],
                                capture_output=True, text=True, check=True)
    container = json.loads(inspection.stdout)[0]
    if container["State"]["Running"] is not True:
        raise RuntimeError("Dedicated Mongo container is not running")
    bindings = container["NetworkSettings"]["Ports"].get("27017/tcp")
    if not isinstance(bindings, list) or not any(
        item["HostPort"] == "17017" and item["HostIp"] in {"127.0.0.1", "::1"} for item in bindings
    ):
        raise RuntimeError("Dedicated Mongo loopback port 17017 is unavailable")
    values = dict(item.split("=", 1) for item in container["Config"]["Env"])
    username = values.get("MONGO_INITDB_ROOT_USERNAME", "")
    password = values.get("MONGO_INITDB_ROOT_PASSWORD", "")
    if bool(username) != bool(password):
        raise RuntimeError("Dedicated Mongo credential pair is incomplete")
    environment = {**os.environ, "PYTHONPATH": str(backend),
                   "SQLCHAT_TEST_MONGO_HOST": "127.0.0.1", "SQLCHAT_TEST_MONGO_PORT": "17017",
                   "SQLCHAT_TEST_MONGO_USER": username, "SQLCHAT_TEST_MONGO_PASSWORD": password}
    client: MongoClient[dict[str, object]]
    if username:
        client = MongoClient("127.0.0.1", 17017, username=username, password=password,
                             serverSelectionTimeoutMS=5000)
    else:
        client = MongoClient("127.0.0.1", 17017, serverSelectionTimeoutMS=5000)
    with client:
        before = set(client.list_database_names())
        version = client.server_info()["version"]
        command = [sys.executable, "-m", "pytest", "tests/test_mongodb_integration.py",
                   "tests/test_mongodb_interruptions.py", "tests/test_mongodb_workflow_integration.py", "-q"]
        started = monotonic()
        result = subprocess.run(command, cwd=backend, env=environment, capture_output=True,
                                text=True, check=False)
        elapsed = monotonic() - started
        unchanged = set(client.list_database_names()) == before
    output = result.stdout + result.stderr
    if password:
        for secret in {password, repr(password)[1:-1], json.dumps(password)[1:-1],
                       quote(password, safe=""), quote_plus(password)}:
            output = output.replace(secret, "[REDACTED]")
    print(output, end="")
    matched = re.search(r"(\d+) passed", output)
    files = ["backend/app/adapters/mongodb.py", "backend/app/adapters/mongodb_command.py",
             "backend/app/adapters/types.py", "backend/app/adapters/mongodb_metadata.py",
             "backend/app/agent/workflow.py", "backend/app/agent/workflow_schema.py",
             "backend/app/agent/workflow_rows.py", "backend/app/agent/workflow_mongodb.py",
             "backend/tests/test_mongodb_workflow_integration.py", "backend/tests/test_mongodb_integration.py",
             "backend/tests/test_mongodb_interruptions.py"]
    evidence = {"baseCommit": json.loads((root / "BASELINE.json").read_text())["baseCommit"],
                "kind": "Integrated Mongo actual engine and HTTP-model protocol self-check", "target": "dedicated loopback:17017",
                "serverVersion": version, "command": "python -m pytest tests/test_mongodb_integration.py "
                "tests/test_mongodb_interruptions.py tests/test_mongodb_workflow_integration.py -q", "exitCode": result.returncode,
                "passed": int(matched[1]) if matched else 0, "elapsedSeconds": round(elapsed, 3),
                "databaseSetUnchanged": unchanged, "containerLifecycleChanged": False,
                "publicWriteCommandsAdded": False,
                "publicWorkflowIntegration": "production WorkflowProgress/WorkflowSchema/rows; model simulated over HTTP; system store temporary SQLite",
                "codeSha256": {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in files}}
    destination = Path(__file__).with_name("real-mongo-integrated.json")
    destination.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(f"databaseSetUnchanged={unchanged}; evidence={destination.name}")
    return result.returncode if unchanged else 1


if __name__ == "__main__":
    try:
        raise SystemExit(run())
    except Exception as error:  # noqa: BLE001 - never print container config or credentials
        print(f"Dedicated Mongo verification failed: {type(error).__name__}")
        raise SystemExit(1) from None
