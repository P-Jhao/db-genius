"""Load ignored/local fixture credentials privately and run the final bridge gate."""

import json
import os
import subprocess
import sys
from pathlib import Path

PHASE = Path(__file__).resolve().parent
RUNTIME = Path("C:/Users/22126/Desktop/web/text2sql/sqlchat/.git/acceptance/s12-runtime")


def container_env(name: str) -> dict[str, str]:
    result = subprocess.run(["docker", "inspect", name], capture_output=True, check=True)
    config = json.loads(result.stdout)[0]
    if config["State"]["Running"] is not True:
        raise RuntimeError(f"Isolated target is not running: {name}")
    return dict(value.split("=", 1) for value in config["Config"]["Env"] if "=" in value)


def required(values: dict[str, str], key: str) -> str:
    value = values.get(key)
    if value is None or not value:
        raise ValueError(f"Isolated target requires {key}")
    return value


def main() -> int:
    pg = container_env("sqlchat-migration-test-postgres")
    mysql = container_env("sqlchat-migration-test-mysql")
    mongo = container_env("sqlchat-s12-mongo")
    for prefix, port, user, database, password in (
        ("PG", "15432", required(pg, "POSTGRES_USER"), required(pg, "POSTGRES_DB"), required(pg, "POSTGRES_PASSWORD")),
        ("MYSQL", "13306", "root", required(mysql, "MYSQL_DATABASE"), required(mysql, "MYSQL_ROOT_PASSWORD")),
    ):
        for key, value in {"HOST": "127.0.0.1", "PORT": port, "USER": user, "DB": database, "PASSWORD": password}.items():
            os.environ[f"SQLCHAT_TEST_{prefix}_{key}"] = value
    mongo_user = mongo.get("MONGO_INITDB_ROOT_USERNAME", "")
    mongo_password = mongo.get("MONGO_INITDB_ROOT_PASSWORD", "")
    if bool(mongo_user) != bool(mongo_password):
        raise ValueError("Mongo fixture credentials must be a complete pair")
    for key, value in {"HOST": "127.0.0.1", "PORT": "17017", "USER": mongo_user, "PASSWORD": mongo_password}.items():
        os.environ[f"SQLCHAT_TEST_MONGO_{key}"] = value
    os.environ["SQLCHAT_SQLSERVER_RUNTIME"] = str(RUNTIME / "sqlserver.env")
    os.environ["SQLCHAT_ORACLE_RUNTIME"] = str(RUNTIME / "oracle-target.env")
    os.environ["NATIVE_GATE_NAME"] = "final-native-s13"
    backend = PHASE.parents[1] / "backend"
    tests = sorted({str(path.relative_to(backend)).replace("\\", "/")
                    for pattern in ("test_native*.py", "test_oracle*.py", "test_sqlserver_real.py")
                    for path in (backend / "tests").glob(pattern)})
    tests += ["tests/test_workflow_identifiers.py", "tests/test_workflow_corrections.py",
              "tests/test_mongodb_workflow.py", "tests/test_mongodb_workflow_integration.py",
              "tests/test_model_parameters.py", "tests/test_compare_reads.py", "-s"]
    for arguments in (tests, ["-ruff"], ["-mypy"]):
        result = subprocess.run([sys.executable, str(PHASE / "run-checks.py"), *arguments], check=False)
        if result.returncode:
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
