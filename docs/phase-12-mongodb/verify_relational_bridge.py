"""Run the new-head SQL bridge without using the PostgreSQL app system schema."""

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from time import monotonic
from urllib.parse import quote, quote_plus

from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.pool import NullPool


def target(name: str, prefix: str, port: int, internal_port: str, driver: str,
           database_key: str, password_key: str, username_key: str | None) -> tuple[dict[str, str], str]:
    inspection = subprocess.run(["docker", "inspect", name], capture_output=True, text=True, check=True)
    container = json.loads(inspection.stdout)[0]
    if container["State"]["Running"] is not True:
        raise RuntimeError(f"Dedicated target {name} is not running")
    bindings = container["NetworkSettings"]["Ports"].get(internal_port)
    if not isinstance(bindings, list) or not any(
        binding["HostPort"] == str(port) and binding["HostIp"] in {"127.0.0.1", "::1"} for binding in bindings
    ):
        raise RuntimeError(f"Dedicated target {name} has an unexpected port")
    values = dict(item.split("=", 1) for item in container["Config"]["Env"])
    username = "root" if username_key is None else values[username_key]
    password, database = values[password_key], values[database_key]
    url = URL.create(driver, host="127.0.0.1", port=port, database=database,
                     username=username, password=password)
    engine = create_engine(url, poolclass=NullPool, connect_args={"connect_timeout": 5})
    try:
        with engine.connect() as connection:
            if connection.exec_driver_sql("SELECT 1").scalar_one() != 1:
                raise RuntimeError(f"Dedicated target {name} is not ready")
    finally:
        engine.dispose()
    return {f"{prefix}_{key}": value for key, value in {
        "HOST": "127.0.0.1", "PORT": str(port), "DB": database,
        "USER": username, "PASSWORD": password,
    }.items()}, password


def run() -> int:
    root = Path(__file__).resolve().parents[2]
    backend = root / "backend"
    environment = {**os.environ, "PYTHONPATH": str(backend)}
    secrets: list[str] = []
    targets = [
        ("sqlchat-migration-test-postgres", "SQLCHAT_TEST_PG", 15432, "5432/tcp", "postgresql+psycopg",
         "POSTGRES_DB", "POSTGRES_PASSWORD", "POSTGRES_USER"),
        ("sqlchat-migration-test-mysql", "SQLCHAT_TEST_MYSQL", 13306, "3306/tcp", "mysql+pymysql",
         "MYSQL_DATABASE", "MYSQL_ROOT_PASSWORD", None),
        ("sqlchat-s12-mariadb", "SQLCHAT_TEST_MARIA", 13307, "3306/tcp", "mysql+pymysql",
         "MARIADB_DATABASE", "MARIADB_ROOT_PASSWORD", None),
    ]
    for arguments in targets:
        variables, password = target(*arguments)
        environment.update(variables)
        secrets.append(password)
    files = ["tests/test_adapters_integration.py", "tests/test_mariadb_integration.py",
             "tests/test_workflow_integration.py", "tests/test_workflow_identifiers.py",
             "tests/test_workflow_sql_repair.py"]
    started = monotonic()
    result = subprocess.run([sys.executable, "-m", "pytest", *files, "-q"],
                            cwd=backend, env=environment, capture_output=True, text=True, check=False)
    elapsed = monotonic() - started
    output = result.stdout + result.stderr
    matched = re.search(r"(\d+) passed", output)
    skipped = re.search(r"(\d+) skipped", output)
    for password in secrets:
        if password:
            for secret in {password, repr(password)[1:-1], json.dumps(password)[1:-1],
                           quote(password, safe=""), quote_plus(password)}:
                output = output.replace(secret, "[REDACTED]")
    print(output, end="")
    sources = ["backend/app/adapters/relational.py", "backend/app/adapters/registry.py",
               "backend/app/adapters/types.py", "backend/app/adapters/document.py",
               "backend/app/agent/workflow.py", "backend/app/agent/workflow_schema.py",
               "backend/app/agent/workflow_rows.py"]
    evidence = {"baseCommit": json.loads((root / "BASELINE.json").read_text())["baseCommit"],
                "kind": "accepted-cursor-head SQL/Mongo factory and workflow bridge",
                "targets": ["dedicated PG:15432", "dedicated MySQL:13306", "dedicated Maria:13307"],
                "command": "python -m pytest " + " ".join(files) + " -q",
                "exitCode": result.returncode, "passed": int(matched[1]) if matched else 0,
                "skipped": int(skipped[1]) if skipped else 0, "elapsedSeconds": round(elapsed, 3),
                "postgresAppSchemaUsed": False, "systemStore": "temporary SQLite / service fixture",
                "containerLifecycleChanged": False, "modelEffects": "not tested; HTTP model simulated",
                "codeSha256": {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in sources}}
    destination = Path(__file__).with_name("real-relational-bridge.json")
    destination.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(f"evidence={destination.name}; postgresAppSchemaUsed=False")
    return result.returncode


if __name__ == "__main__":
    try:
        raise SystemExit(run())
    except Exception as error:  # noqa: BLE001 - credentials stay internal, including failed readiness
        print(f"Dedicated relational bridge failed: {type(error).__name__}")
        raise SystemExit(1) from None
