"""Actual Mongo comparison integration; anonymous dedicated target, no lifecycle changes."""

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
    inspection = subprocess.run(["docker", "inspect", "sqlchat-s12-mongo"],
                                capture_output=True, text=True, check=True)
    container = json.loads(inspection.stdout)[0]
    if container["State"]["Running"] is not True:
        raise RuntimeError("Dedicated Mongo target is not running")
    bindings = container["NetworkSettings"]["Ports"].get("27017/tcp")
    if not isinstance(bindings, list) or not any(
        item["HostPort"] == "17017" and item["HostIp"] in {"127.0.0.1", "::1"} for item in bindings
    ):
        raise RuntimeError("Dedicated Mongo loopback binding is unavailable")
    values = dict(item.split("=", 1) for item in container["Config"]["Env"])
    username = values.get("MONGO_INITDB_ROOT_USERNAME", "")
    password = values.get("MONGO_INITDB_ROOT_PASSWORD", "")
    if bool(username) != bool(password):
        raise RuntimeError("Dedicated Mongo credential pair is incomplete")
    environment = {**os.environ, "PYTHONPATH": str(root / "backend"),
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
        started = monotonic()
        result = subprocess.run([sys.executable, "-m", "pytest", "tests/test_compare_mongodb_integration.py", "-q"],
                                cwd=root / "backend", env=environment, capture_output=True, text=True, check=False)
        elapsed = monotonic() - started
        unchanged = set(client.list_database_names()) == before
    output = result.stdout + result.stderr
    passed, skipped = re.search(r"(\d+) passed", output), re.search(r"(\d+) skipped", output)
    if password:
        for secret in {password, repr(password)[1:-1], json.dumps(password)[1:-1],
                       quote(password, safe=""), quote_plus(password)}:
            output = output.replace(secret, "[REDACTED]")
    print(output, end="")
    sources = ["backend/app/services/database_tools.py", "backend/app/services/schema_diff.py",
               "backend/app/agent/tools.py", "backend/app/agent/graph_sql.py", "backend/app/agent/compare.py",
               "backend/app/adapters/mongodb.py", "backend/tests/test_compare_mongodb_integration.py"]
    evidence = {"acceptedBusinessBase": "5c9c2cdb22c920f595dd5c8485a013c650a4fff1",
                "sourceSnapshot": "main-mongo-1790852339433; readonly copied combination",
                "target": "dedicated loopback Mongo:17017", "serverVersion": version,
                "command": "python -m pytest tests/test_compare_mongodb_integration.py -q",
                "exitCode": result.returncode, "passed": int(passed[1]) if passed else 0,
                "skipped": int(skipped[1]) if skipped else 0, "elapsedSeconds": round(elapsed, 3),
                "databaseSetUnchanged": unchanged, "containerLifecycleChanged": False,
                "publicWriteCommandsAdded": False, "databaseContentsUnchanged": "asserted by each fixture",
                "model": "controlled HTTP simulation; no actual provider effects", "systemStore": "temporary SQLite",
                "codeSha256": {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in sources}}
    Path(__file__).with_name("real-compare-mongo.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(f"databaseSetUnchanged={unchanged}; actualModel=False")
    return result.returncode if unchanged and skipped is None else 1


if __name__ == "__main__":
    try:
        raise SystemExit(run())
    except Exception as error:  # noqa: BLE001 - do not print internal inspection or credentials
        print(f"Dedicated Mongo comparison failed: {type(error).__name__}")
        raise SystemExit(1) from None
