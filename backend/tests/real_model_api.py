"""Actual original/Python API sessions, SSE history and exact owned-resource cleanup."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from time import monotonic, sleep
from typing import Literal
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from dotenv import dotenv_values
from pydantic import SecretStr
from real_model_cases import CSV, LOCALE, MODEL
from real_model_database import TargetSnapshot
from real_model_relay import RealProviderRelay, object_value

ROOT = Path(__file__).resolve().parents[2]
type Variant = Literal["python", "java"]


def api(client: httpx.Client, method: str, path: str, *, body: object = None) -> object:
    response = client.request(method, path, json=body)
    if response.status_code != 200:
        raise RuntimeError(f"{method} {path}: HTTP {response.status_code}")
    packet = object_value(response.json())
    if packet["code"] != 200:
        raise RuntimeError(f"{method} {path}: application code {packet['code']}")
    return packet.get("data")


def _admin(variant: Variant) -> tuple[str, SecretStr]:
    if variant == "python":
        values = dotenv_values(ROOT / ".env.s14", interpolate=False)
        username, password = values.get("SQLCHAT_BOOTSTRAP_USERNAME"), values.get("SQLCHAT_BOOTSTRAP_PASSWORD")
    else:
        runtime = Path(os.environ.get("SQLCHAT_REAL_JAVA_RUNTIME_DIR",
                                     str(ROOT / ".git/acceptance/s15-java-runtime"))).resolve()
        if not runtime.is_relative_to((ROOT / ".git/acceptance").resolve()):
            raise ValueError("Original runtime secrets must stay inside .git/acceptance")
        values = dotenv_values(runtime / "admin.env", interpolate=False)
        username, password = values.get("JAVA_ADMIN_USERNAME"), values.get("JAVA_ADMIN_PASSWORD")
    if not username or not password:
        raise ValueError("Actual isolated API administrator credentials are required")
    return username, SecretStr(password)


def _cleanup(variant: Variant, username: str) -> None:
    if re.fullmatch(r"s15_real_[0-9a-f]{20}", username) is None:
        raise ValueError("Cleanup requires its exact randomly generated user")
    if variant == "python":
        script = (
            "import sys; from sqlalchemy import delete,select; from app.core.database import SessionLocal; "
            "from app.models import User,Conversation,DbConfig,AuthSession,UserModelConfig,UploadedFile; "
            "from app.storage.backend import get_storage; "
            "s=SessionLocal(); u=s.scalar(select(User).where(User.username==sys.argv[1])); "
            "sys.exit(0) if u is None else None; "
            "files=list(s.scalars(select(UploadedFile).where(UploadedFile.user_id==u.id))); "
            "assert all(f.oss_key.startswith(f'uploads/{u.id}/') for f in files); "
            "[get_storage().delete(f.oss_key) for f in files]; "
            "[s.execute(delete(t).where(t.user_id==u.id)) for t in "
            "(Conversation,DbConfig,AuthSession,UserModelConfig,UploadedFile)]; s.delete(u); s.commit(); s.close()"
        )
        command = ["docker", "exec", "sqlchat-s14-test-api-1", "python", "deploy/connection_env.py",
                   "python", "-c", script, username]
        result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=30)
    else:
        owned = f"(SELECT id FROM app.sys_user WHERE username='{username}')"
        sql = (
            "BEGIN; "
            f"DELETE FROM app.message WHERE conversation_id IN (SELECT id FROM app.conversation WHERE user_id IN {owned}); "
            f"DELETE FROM app.conversation WHERE user_id IN {owned}; "
            f"DELETE FROM app.db_config WHERE user_id IN {owned}; "
            f"DELETE FROM app.user_model_config WHERE user_id IN {owned}; "
            f"DELETE FROM app.uploaded_file WHERE user_id IN {owned}; "
            f"DELETE FROM app.sys_user WHERE username='{username}'; COMMIT;"
        )
        result = subprocess.run([
            "docker", "exec", "-i", "sqlchat-s15-java-postgres", "sh", "-c",
            'exec psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1',
        ], input=sql, capture_output=True, text=True, check=False, timeout=30)
    if result.returncode != 0:
        raise RuntimeError("Exact real-model user cleanup failed; diagnostics omit credentials")


@dataclass
class ApiSession:
    variant: Variant
    username: str
    client: httpx.Client = field(repr=False)
    token: SecretStr = field(repr=False)

    def upload_csv(self) -> int:
        response = self.client.post("file/upload", files={"file": ("s15_contacts.csv", CSV, "text/csv")})
        if response.status_code != 200:
            raise RuntimeError("Actual file upload HTTP failure")
        packet = object_value(response.json())
        if packet.get("code") != 200:
            raise RuntimeError("Actual file upload application failure")
        file_id = object_value(packet.get("data"))["id"]
        if not isinstance(file_id, int) or isinstance(file_id, bool):
            raise TypeError("Expected an actual uploaded file ID")
        return file_id

    def connect(self, target: TargetSnapshot) -> int:
        created = object_value(api(self.client, "POST", "db-config", body=target.request()))
        config_id = created["id"]
        if not isinstance(config_id, int) or isinstance(config_id, bool):
            raise TypeError("Expected a data source ID")
        deadline = monotonic() + 60
        while True:
            current = object_value(api(self.client, "GET", f"db-config/{config_id}"))
            if current["status"] == 1:
                break
            if current["status"] == 2:
                raise RuntimeError("Actual background data source connection failed")
            if monotonic() > deadline:
                raise TimeoutError("Actual worker did not verify the data source")
            sleep(0.25)
        document = api(self.client, "GET", f"db-config/{config_id}/doc")
        if not isinstance(document, str) or "orders" not in document:
            raise ValueError("Actual data source metadata was not generated")
        return config_id

    def chat(self, body: dict[str, object]) -> tuple[list[dict[str, object]], dict[str, object]]:
        events: list[dict[str, object]] = []
        started = monotonic()
        first_visible: float | None = None
        with self.client.stream("POST", "chat", json=body) as response:
            if response.status_code != 200 or not response.headers.get("content-type", "").startswith("text/event-stream"):
                raise RuntimeError("Actual chat API did not return SSE")
            for line in response.iter_lines():
                if not line.startswith("data:"):
                    continue
                event = object_value(json.loads(line.removeprefix("data:")))
                events.append(event)
                if first_visible is None and event["type"] in {"content", "summary_delta", "reasoning"} and event["content"]:
                    first_visible = monotonic() - started
        return events, {"elapsedSeconds": monotonic() - started, "firstVisibleSeconds": first_visible}

    def messages(self, conversation_id: int) -> list[dict[str, object]]:
        value = api(self.client, "GET", f"chat/conversations/{conversation_id}/messages")
        if not isinstance(value, list):
            raise TypeError("Expected persisted chat history")
        return [object_value(row) for row in value]


@contextmanager
def api_session(variant: Variant, relay: RealProviderRelay) -> Iterator[ApiSession]:
    default = "http://127.0.0.1:18109" if variant == "python" else "http://127.0.0.1:18110"
    url = os.environ.get(f"SQLCHAT_REAL_{variant.upper()}_URL", default)
    parsed = urlsplit(url)
    if parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.port != (18109 if variant == "python" else 18110):
        raise ValueError("Real-model fixture requires the isolated loopback deployment")
    username = f"s15_real_{uuid4().hex[:20]}"
    password = SecretStr(secrets.token_urlsafe(24))
    administrator, admin_password = _admin(variant)
    client = httpx.Client(base_url=url.rstrip("/") + "/api/", timeout=httpx.Timeout(330, connect=10),
                          headers={"Accept-Language": LOCALE})
    target = ApiSession(variant, username, client, SecretStr(""))
    try:
        admin = object_value(api(client, "POST", "auth/login", body={
            "username": administrator, "password": admin_password.get_secret_value(),
        }))
        client.headers["Authorization"] = str(admin["token"])
        api(client, "POST", "auth/user", body={"username": username, "password": password.get_secret_value(),
                                              "role": "user"})
        api(client, "POST", "auth/logout")
        user = object_value(api(client, "POST", "auth/login", body={
            "username": username, "password": password.get_secret_value(),
        }))
        if user.get("role") != "user":
            raise ValueError("Both real-model API sessions require identical ordinary-user permissions")
        target.token = SecretStr(str(user["token"]))
        client.headers["Authorization"] = target.token.get_secret_value()
        base = f"http://host.docker.internal:{relay.server_port}/{variant}"
        model = object_value(api(client, "POST", "model-config/configs", body={
            "providerCode": "custom", "providerType": "openai_compatible", "displayName": "S15 actual Flash",
            "baseUrl": base, "modelName": MODEL, "apiKey": relay.access_key.get_secret_value(),
            "contextWindow": 1048576,
        }))
        api(client, "PUT", f"model-config/configs/{model['id']}/default")
        active = object_value(api(client, "GET", "model-config/active"))
        if active["modelName"] != MODEL or active["baseUrl"] != base:
            raise ValueError("The actual chat API did not select its provider relay")
        yield target
    finally:
        try:
            if target.token.get_secret_value():
                api(client, "POST", "auth/logout")
        finally:
            client.close()
            _cleanup(variant, username)


def runtime_identity() -> dict[str, object]:
    result: dict[str, object] = {}
    for name in ("sqlchat-s14-test-api-1", "sqlchat-s15-java"):
        inspected = subprocess.run(["docker", "inspect", "--format",
                                    '{{json .Image}}|{{json .State.StartedAt}}', name],
                                   capture_output=True, text=True, check=True)
        image, started = inspected.stdout.strip().split("|", 1)
        result[name] = {"image": json.loads(image), "startedAt": json.loads(started)}
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True)
    result["candidateCommit"] = commit.stdout.strip()
    source = ROOT / ".git/acceptance/original-73bb7e87cf32-manifest.json"
    if source.is_file():
        hashes = object_value(json.loads(source.read_text(encoding="utf-8")))["sourceHashes"]
        result["originalSourceManifestSha256"] = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    return result
