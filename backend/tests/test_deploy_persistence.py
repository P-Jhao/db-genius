"""Two-phase restart acceptance; lifecycle changes are performed by the operator."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from deploy_proxy_support import (
    api,
    cleanup_proxy_user,
    container_for_tests,
    frame,
    object_value,
    open_proxy_session,
    runtime_script,
    stop_proxy_transport,
)


def _state_path() -> Path:
    configured = os.environ.get("SQLCHAT_TEST_PERSIST_STATE")
    if configured is None:
        pytest.skip("Set the two-phase state path inside .git/acceptance")
    path = Path(configured).resolve()
    allowed = (Path(__file__).resolve().parents[2] / ".git" / "acceptance").resolve()
    if not path.is_relative_to(allowed) or path.suffix != ".json":
        raise ValueError("Persistence state must be a JSON file inside this repository's .git/acceptance")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _password() -> str:
    password = os.environ.get("SQLCHAT_TEST_PERSIST_PASSWORD")
    if password is None:
        pytest.skip("Set one temporary persistence user password for both phases")
    if len(password) < 16:
        raise ValueError("Persistence fixture requires a password of at least 16 characters")
    return password


def _starts(container: str) -> dict[str, str]:
    report = {}
    for name in (container, "sqlchat-s14-test-worker-1", "sqlchat-s14-test-postgres-1"):
        result = subprocess.run(["docker", "inspect", "--format",
                                 '{{index .Config.Labels "com.docker.compose.project"}}|{{.State.StartedAt}}',
                                 name], capture_output=True, text=True, check=True)
        project, started = result.stdout.strip().split("|", 1)
        assert project == "sqlchat-s14-test", "Restart acceptance must use its isolated Compose project"
        report[name] = started
    return report


def _snapshot(container: str, state: dict[str, object]) -> dict[str, object]:
    script = (
        "import sys,json,hashlib; from sqlalchemy import select; from app.core.database import SessionLocal; "
        "from app.models import User,Conversation,Message,AuthSession; "
        "from app.services.file_upload import read_owned_bytes; "
        "s=SessionLocal(); u=s.scalar(select(User).where(User.username==sys.argv[1])); assert u is not None; "
        "c=s.get(Conversation,int(sys.argv[3])); assert c is not None and c.user_id==u.id; "
        "a=s.get(AuthSession,sys.argv[4]); assert a is not None and a.user_id==u.id; "
        "f,b=read_owned_bytes(u.id,int(sys.argv[2])); "
        "rows=list(s.scalars(select(Message).where(Message.conversation_id==c.id).order_by(Message.id))); "
        "print(json.dumps({'file':{'name':f.original_name,'size':f.file_size,'sha256':hashlib.sha256(b).hexdigest()},"
        "'conversation':{'id':c.id,'totalTokens':c.total_tokens,'contextTokens':c.context_tokens,"
        "'metadata':c.metadata_json},'messages':[{'id':m.id,'type':m.type,'content':m.content,"
        "'metadata':m.metadata_json} for m in rows],'sessionExpiresAt':a.expires_at.isoformat()})); s.close()"
    )
    return object_value(json.loads(runtime_script(container, script, str(state["username"]),
                                                  str(state["fileId"]), str(state["conversationId"]),
                                                  str(state["sessionDigest"]))))


def test_prepare_restart_persistence_fixture() -> None:
    if os.environ.get("SQLCHAT_TEST_PERSIST_PHASE") != "prepare":
        pytest.skip("Run prepare before the operator restarts API, worker and PostgreSQL")
    password, path = _password(), _state_path()
    assert not path.exists(), "Use a fresh state path; existing resources must not be overwritten"
    username = f"s14_proxy_{uuid4().hex[:20]}"
    target, thread = open_proxy_session(persistent_username=username, persistent_password=password)
    prepared = False
    try:
        payload = b"id,name\n1,restart-fixture\n"
        response = target.client.post("file/upload", files={"file": ("persist.csv", payload, "text/csv")})
        assert response.status_code == 200
        packet = object_value(response.json())
        assert packet["code"] == 200, "Persistence upload failed"
        uploaded = object_value(packet["data"])
        target.provider.replies = [[
            (frame({"choices": [{"delta": {"content": "persisted-answer"}}]}), 0),
            (frame({"usage": {"prompt_tokens": 4, "completion_tokens": 2}}), 0),
            (frame("[DONE]"), 0),
        ]]
        events = []
        with target.client.stream("POST", "chat", json={"message": "restart fixture",
                                                       "confirmedIntent": "simple_chat",
                                                       "fileIds": [uploaded["id"]]}) as result:
            assert result.status_code == 200
            for line in result.iter_lines():
                if line.startswith("data:"):
                    events.append(object_value(json.loads(line.removeprefix("data:"))))
        assert [event["type"] for event in events].count("done") == 1
        assert not any(event["type"] == "error" for event in events)
        state: dict[str, object] = {
            "username": username, "fileId": uploaded["id"],
            "conversationId": next(event["content"] for event in events if event["type"] == "conversation"),
            "sessionDigest": hashlib.sha256(target.token.encode()).hexdigest(),
            "startsBefore": _starts(target.container), "phase": "prepared",
        }
        state["snapshot"] = _snapshot(target.container, state)
        snapshot = object_value(state["snapshot"])
        assert object_value(snapshot["file"])["sha256"] == hashlib.sha256(payload).hexdigest()
        assert object_value(snapshot["conversation"])["totalTokens"] == 6
        path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        prepared = True
    finally:
        stop_proxy_transport(target, thread)
        if not prepared:
            cleanup_proxy_user(target.container, username)


def test_verify_restart_preserves_file_history_session_and_token_usage() -> None:
    if os.environ.get("SQLCHAT_TEST_PERSIST_PHASE") != "verify":
        pytest.skip("Run verify only after the operator restarts API, worker and PostgreSQL")
    password, path = _password(), _state_path()
    state = object_value(json.loads(path.read_text(encoding="utf-8")))
    assert state["phase"] == "prepared"
    username = str(state["username"])
    assert username.startswith("s14_proxy_")
    url = os.environ.get("SQLCHAT_TEST_DEPLOY_URL")
    if url is None:
        pytest.skip("Real isolated Compose URL is not configured")
    container = container_for_tests()
    after = _starts(container)
    before = object_value(state["startsBefore"])
    assert all(after[name] != before[name] for name in after), "All three services must actually restart"
    try:
        with httpx.Client(base_url=url.rstrip("/") + "/api/", timeout=30) as client:
            login = object_value(api(client, "POST", "auth/login", json={"username": username, "password": password}))
            client.headers["Authorization"] = f"Bearer {login['token']}"
            rows = api(client, "GET", f"chat/conversations/{state['conversationId']}/messages")
            assert isinstance(rows, list)
            assert [(object_value(row)["type"], object_value(row)["content"]) for row in rows] == [
                ("user", "restart fixture"), ("content", "persisted-answer"),
            ]
        assert _snapshot(container, state) == state["snapshot"]
        state.update({"phase": "verified", "startsAfter": after})
        path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    finally:
        cleanup_proxy_user(container, username)
