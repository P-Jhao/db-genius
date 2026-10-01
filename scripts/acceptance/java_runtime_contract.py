"""Prepare an ignored original-Java runtime env; never starts containers or prints credentials."""

from __future__ import annotations

import argparse
import json
import secrets
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / ".git" / "acceptance" / "original-73bb7e87cf32"
RUNTIME = ROOT / ".git" / "acceptance" / "s15-java-runtime"
JAR = SOURCE / "db-genius-web" / "target" / "db-genius-web-1.0.0.jar"
SCHEMA = SOURCE / "db-genius-web" / "src" / "main" / "resources" / "db" / "schema.sql"


def required(path: Path, *names: str) -> dict[str, str]:
    raw = dotenv_values(path, interpolate=False)
    result = {}
    for name in names:
        value = raw.get(name)
        if value is None or not value.strip():
            raise ValueError(f"{path.name}: missing {name}")
        if any(character in value for character in "\r\n\x00"):
            raise ValueError(f"{path.name}: invalid multiline environment value")
        result[name] = value
    return result


def prepare(*, write: bool, source_root: Path = SOURCE, runtime_dir: Path = RUNTIME) -> dict[str, object]:
    source_root, runtime_dir = source_root.resolve(), runtime_dir.resolve()
    allowed = (ROOT / ".git" / "acceptance").resolve()
    if not source_root.is_relative_to(allowed) or not runtime_dir.is_relative_to(allowed):
        raise ValueError("Original copy and secret runtime paths must stay inside .git/acceptance")
    jar = source_root / "db-genius-web" / "target" / "db-genius-web-1.0.0.jar"
    schema = source_root / "db-genius-web" / "src" / "main" / "resources" / "db" / "schema.sql"
    if not jar.is_file() or not schema.is_file():
        raise FileNotFoundError("Original boot JAR/schema must exist in the isolated source copy")
    database = required(runtime_dir / "postgres.env", "POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD")
    broker = required(runtime_dir / "rabbit.env", "RABBITMQ_DEFAULT_USER", "RABBITMQ_DEFAULT_PASS")
    if not database["POSTGRES_DB"].replace("_", "").isalnum():
        raise ValueError("Original system database name must be an identifier")
    environment = {
        "SPRING_DATASOURCE_URL":
            f"jdbc:postgresql://java-postgres:5432/{database['POSTGRES_DB']}?currentSchema=app",
        "SPRING_DATASOURCE_USERNAME": database["POSTGRES_USER"],
        "SPRING_DATASOURCE_PASSWORD": database["POSTGRES_PASSWORD"],
        "SPRING_RABBITMQ_HOST": "java-rabbit",
        "SPRING_RABBITMQ_PORT": "5672",
        "SPRING_RABBITMQ_USERNAME": broker["RABBITMQ_DEFAULT_USER"],
        "SPRING_RABBITMQ_PASSWORD": broker["RABBITMQ_DEFAULT_PASS"],
        "DB_GENIUS_ENCRYPT_KEY": secrets.token_hex(16),
        "DB_GENIUS_DEFAULT_MODEL": "deepseek-flash",
        "DB_GENIUS_DEFAULT_MODEL_BASE_URL": "https://api.deepseek.com",
        # The harness sets a per-user real-provider relay; startup never calls this placeholder.
        "DB_GENIUS_DEFAULT_MODEL_API_KEY": "local-s15-bootstrap-only",
        # Required original fail-fast bean configuration; no OSS request is made for SQL cases.
        "ALIYUN_OSS_ENDPOINT": "https://oss.s15.invalid",
        "ALIYUN_OSS_BUCKET": "s15-unconfigured",
        "ALIYUN_ACCESS_KEY_ID": "s15-unconfigured",
        "ALIYUN_ACCESS_KEY_SECRET": "s15-unconfigured",
        "ALIYUN_OSS_DIR_PREFIX": "uploads/",
        "ALIYUN_OCR_ENABLED": "false",
        "DB_GENIUS_TRIAL_ENABLED": "false",
        "MANAGEMENT_TRACING_SAMPLING_PROBABILITY": "0",
        "LOGGING_LEVEL_COM_DBGENIUS": "WARN",
        "LOGGING_LEVEL_ORG_SPRINGFRAMEWORK_AI": "WARN",
    }
    env_file = runtime_dir / "java.env"
    if write:
        if env_file.exists():
            raise FileExistsError("Keep the existing original encryption key; review/remove only this file explicitly")
        env_file.write_text("".join(f"{key}={value}\n" for key, value in environment.items()), encoding="utf-8")
    command = [
        "docker", "run", "-d", "--name", "sqlchat-s15-java",
        "--label", "sqlchat.acceptance=s15-java", "--network", "sqlchat-s15-java",
        "--publish", "127.0.0.1:18110:8109", "--memory", "1g", "--cpus", "2",
        "--mount", f"type=bind,source={jar},target=/app/db-genius.jar,readonly",
        "--env-file", str(env_file), "eclipse-temurin:21-jre",
        "java", "-Xms128m", "-Xmx512m", "-XX:MaxMetaspaceSize=256m", "-jar", "/app/db-genius.jar",
    ]
    return {"jar": str(jar), "schema": str(schema), "environmentFile": str(env_file),
            "environmentNames": sorted(environment), "command": command,
            "healthUrl": "http://127.0.0.1:18110/api/health", "originalFileChain": "environment-blocked"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-env", action="store_true", help="Create only the ignored Java env file")
    parser.add_argument("--source-root", type=Path, default=SOURCE, help="Read-only original copy under .git/acceptance")
    parser.add_argument("--runtime-dir", type=Path, default=RUNTIME, help="Ignored credential directory under .git/acceptance")
    options = parser.parse_args()
    print(json.dumps(prepare(write=options.write_env, source_root=options.source_root,
                             runtime_dir=options.runtime_dir), indent=2))
