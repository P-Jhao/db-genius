"""Isolated Compose runtime fixture helpers; never records credentials."""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from time import sleep
from typing import cast
from uuid import uuid4

import httpx
import pytest


def object_value(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise TypeError("Expected a JSON object")
    return cast(dict[str, object], value)


def api(client: httpx.Client, method: str, path: str, *, json: object = None) -> object:
    response = client.request(method, path, json=json)
    assert response.status_code == 200, f"{method} {path}: HTTP {response.status_code}"
    packet = object_value(response.json())
    assert packet["code"] == 200, f"{method} {path}: application code {packet['code']}"
    return packet.get("data")


def frame(packet: dict[str, object] | str) -> bytes:
    encoded = packet if isinstance(packet, str) else json.dumps(packet)
    return f"data: {encoded}\n\n".encode()


def tool_reply(name: str, arguments: dict[str, object]) -> list[tuple[bytes, float]]:
    return [(frame({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": uuid4().hex,
             "function": {"name": name, "arguments": json.dumps(arguments)}}]}}]}), 0),
            (frame({"usage": {"prompt_tokens": 4, "completion_tokens": 2}}), 0),
            (frame("[DONE]"), 0)]


class SlowProvider(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self) -> None:
        self.replies: list[list[tuple[bytes, float]]] = []
        self.calls = 0
        self.finished = threading.Event()
        super().__init__(("0.0.0.0", 0), SlowHandler)


class SlowHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self) -> None:
        server = self.server
        assert isinstance(server, SlowProvider)
        self.rfile.read(int(self.headers["Content-Length"]))  # No prompt/header capture.
        server.calls += 1
        if not server.replies:
            self.send_error(503)
            return
        reply = server.replies.pop(0)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            for part, delay in reply:
                sleep(delay)
                self.wfile.write(part)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            server.finished.set()

    def log_message(self, format: str, *args: object) -> None:
        pass


def container_for_tests() -> str:
    container = os.environ.get("SQLCHAT_TEST_DEPLOY_API_CONTAINER", "sqlchat-s14-test-api-1")
    result = subprocess.run(["docker", "inspect", "--format",
                             '{{index .Config.Labels "com.docker.compose.project"}}', container],
                            capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "sqlchat-s14-test", "Runtime fixture requires its isolated Compose project"
    return container


def runtime_script(container: str, script: str, *arguments: str) -> str:
    result = subprocess.run(["docker", "exec", container, "python", "deploy/connection_env.py", "python",
                             "-c", script, *arguments], capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, "Isolated Compose inspection/cleanup command failed"
    return result.stdout


@dataclass
class ProxySession:
    client: httpx.Client
    provider: SlowProvider
    username: str
    token: str = field(repr=False)
    container: str
    url: str

    def terminal_metadata(self) -> list[dict[str, object]]:
        script = (
            "import json,sys; from sqlalchemy import select; "
            "from app.core.database import SessionLocal; from app.models import Message,Conversation,User; "
            "s=SessionLocal(); rows=s.execute(select(Message.metadata_json,Conversation.total_tokens)"
            ".join(Conversation,Message.conversation_id==Conversation.id)"
            ".join(User,Conversation.user_id==User.id).where(User.username==sys.argv[1],"
            "Message.type.in_(['aborted','summary','content','error']))).all(); "
            "print(json.dumps([{'metadata':r[0],'totalTokens':r[1]} for r in rows])); s.close()"
        )
        decoded: object = json.loads(runtime_script(self.container, script, self.username))
        if not isinstance(decoded, list):
            raise TypeError("Expected terminal metadata list")
        return [object_value(row) for row in decoded]


def open_proxy_session(*, persistent_username: str | None = None,
                       persistent_password: str | None = None) -> tuple[ProxySession, threading.Thread]:
    url, password = (os.environ.get(key) for key in ("SQLCHAT_TEST_DEPLOY_URL", "SQLCHAT_TEST_DEPLOY_PASSWORD"))
    if url is None or password is None:
        pytest.skip("real isolated Compose URL/admin password are not configured")
    container = container_for_tests()
    provider = SlowProvider()
    thread = threading.Thread(target=provider.serve_forever, daemon=True)
    thread.start()
    client = httpx.Client(base_url=url.rstrip("/") + "/api/", timeout=30)
    if (persistent_username is None) != (persistent_password is None):
        raise ValueError("Both persistence fixture credentials are required")
    username = f"s14_proxy_{uuid4().hex[:20]}" if persistent_username is None else persistent_username
    test_password = secrets.token_urlsafe(24) if persistent_password is None else persistent_password
    if not username.startswith("s14_proxy_"):
        raise ValueError("Persistence fixture username must use its reserved prefix")
    target = ProxySession(client, provider, username, "", container, url)
    try:
        admin = object_value(api(client, "POST", "auth/login", json={
            "username": os.environ.get("SQLCHAT_TEST_DEPLOY_USERNAME", "admin"), "password": password,
        }))
        client.headers["Authorization"] = f"Bearer {admin['token']}"
        api(client, "POST", "auth/user", json={"username": username, "password": test_password, "role": "user"})
        user = object_value(api(client, "POST", "auth/login", json={"username": username, "password": test_password}))
        target.token = str(user["token"])
        client.headers["Authorization"] = f"Bearer {target.token}"
        host = os.environ.get("SQLCHAT_TEST_DEPLOY_PROVIDER_HOST", "host.docker.internal")
        api(client, "POST", "model-config/configs", json={
            "providerCode": "custom", "providerType": "openai_compatible", "displayName": "S14 proxy fixture",
            "baseUrl": f"http://{host}:{provider.server_port}", "modelName": "s14-controlled-provider",
            "apiKey": "local-fixture-only", "contextWindow": 8192,
        })
        return target, thread
    except Exception:
        close_proxy_session(target, thread)
        raise


def close_proxy_session(target: ProxySession, thread: threading.Thread) -> None:
    stop_proxy_transport(target, thread)
    cleanup_proxy_user(target.container, target.username)


def stop_proxy_transport(target: ProxySession, thread: threading.Thread) -> None:
    target.client.close()
    target.provider.shutdown()
    target.provider.server_close()
    thread.join(3)


def cleanup_proxy_user(container: str, username: str) -> None:
    script = (
        "import sys; from sqlalchemy import delete,select; from app.core.database import SessionLocal; "
        "from app.models import User,Conversation,DbConfig,AuthSession,UserModelConfig,UploadedFile; "
        "from app.storage.backend import get_storage; "
        "s=SessionLocal(); u=s.scalar(select(User).where(User.username==sys.argv[1])); "
        "assert sys.argv[1].startswith('s14_proxy_'); "
        "sys.exit(0) if u is None else None; "
        "files=list(s.scalars(select(UploadedFile).where(UploadedFile.user_id==u.id))); "
        "assert all(f.oss_key.startswith(f'uploads/{u.id}/') for f in files); "
        "[get_storage().delete(f.oss_key) for f in files]; "
        "[s.execute(delete(t).where(t.user_id==u.id)) for t in "
        "(Conversation,DbConfig,AuthSession,UserModelConfig,UploadedFile)]; s.delete(u); s.commit(); s.close()"
    )
    runtime_script(container, script, username)
