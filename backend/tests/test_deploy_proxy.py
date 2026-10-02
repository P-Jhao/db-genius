"""Real Nginx/API/worker/PG persistence; a controlled model isolates transport behaviour."""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Iterator
from pathlib import Path
from time import monotonic, sleep

import pytest
from deploy_proxy_support import (
    ProxySession,
    api,
    close_proxy_session,
    frame,
    object_value,
    open_proxy_session,
)


@pytest.fixture
def proxy_session() -> Iterator[ProxySession]:
    target, thread = open_proxy_session()
    try:
        yield target
    finally:
        close_proxy_session(target, thread)


def _reply(delay: float) -> list[tuple[bytes, float]]:
    return [(frame({"choices": [{"delta": {"content": "first"}}]}), 0),
            (frame({"choices": [{"delta": {"content": "second"}}]}), delay),
            (frame({"usage": {"prompt_tokens": 4, "completion_tokens": 2}}), 0),
            (frame("[DONE]"), 0)]


def test_real_nginx_forwards_incremental_sse_and_serves_concurrent_api(proxy_session: ProxySession) -> None:
    target = proxy_session
    target.provider.replies = [_reply(2)]
    events: list[dict[str, object]] = []
    with target.client.stream("POST", "chat", json={"message": "proxy streaming fixture",
                                                   "confirmedIntent": "simple_chat"}) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        for line in response.iter_lines():
            if not line.startswith("data:"):
                continue
            event = object_value(json.loads(line.removeprefix("data:")))
            events.append(event)
            if event["type"] == "content" and event["content"] == "first":
                assert not target.provider.finished.is_set(), "Nginx buffered the stream until model completion"
                started = monotonic()
                assert target.client.get("health/live").status_code == 200
                assert monotonic() - started < 1.5, "Ordinary API blocked behind a long SSE request"
    assert [event["type"] for event in events].count("done") == 1
    assert "".join(str(event["content"]) for event in events if event["type"] == "content") == "firstsecond"
    usage = next(object_value(event["content"]) for event in events if event["type"] == "usage")
    assert usage["callCount"] == 1 and usage["totalTokens"] == 6
    conversation_id = next(event["content"] for event in events if event["type"] == "conversation")
    rows = api(target.client, "GET", f"chat/conversations/{conversation_id}/messages")
    assert isinstance(rows, list)
    assert [(object_value(row)["type"], object_value(row)["content"]) for row in rows] == [
        ("user", "proxy streaming fixture"), ("content", "firstsecond"),
    ]
    terminal = target.terminal_metadata()
    assert len(terminal) == 1 and terminal[0]["totalTokens"] == 6


def _assert_aborted(target: ProxySession, conversation_id: object) -> None:
    deadline = monotonic() + 10
    while monotonic() < deadline:
        rows = api(target.client, "GET", f"chat/conversations/{conversation_id}/messages")
        assert isinstance(rows, list)
        terminal = [object_value(row) for row in rows if object_value(row)["type"] == "aborted"]
        if terminal:
            assert len(terminal) == 1 and terminal[0]["content"] == "first"
            assert not any(object_value(row)["type"] in {"content", "summary"} for row in rows)
            metadata = target.terminal_metadata()
            assert len(metadata) == 1
            assert object_value(metadata[0]["metadata"])["runStatus"] == "aborted"
            assert target.provider.calls == 1
            return
        sleep(0.1)
    pytest.fail("Nginx client disconnect did not persist one aborted terminal")


def test_real_nginx_tcp_disconnect_persists_partial_once(proxy_session: ProxySession) -> None:
    target = proxy_session
    target.provider.replies = [_reply(5)]
    conversation_id: object = None
    with target.client.stream("POST", "chat", json={"message": "proxy disconnect fixture",
                                                   "confirmedIntent": "simple_chat"}) as response:
        assert response.status_code == 200
        for line in response.iter_lines():
            if not line.startswith("data:"):
                continue
            event = object_value(json.loads(line.removeprefix("data:")))
            if event["type"] == "conversation":
                conversation_id = event["content"]
            if event["type"] == "content":
                assert event["content"] == "first" and not target.provider.finished.is_set()
                response.close()
                break
    assert isinstance(conversation_id, int)
    _assert_aborted(target, conversation_id)


def test_real_browser_abort_reaches_nginx_and_api(proxy_session: ProxySession) -> None:
    if os.environ.get("SQLCHAT_TEST_DEPLOY_BROWSER") != "1":
        pytest.skip("Set SQLCHAT_TEST_DEPLOY_BROWSER=1 with the frontend Playwright browser installed")
    target = proxy_session
    target.provider.replies = [_reply(5)]
    script = Path(__file__).resolve().parents[2] / "tests" / "s14-browser-disconnect.mjs"
    result = subprocess.run(["node", str(script)], input=json.dumps({
        "url": target.url, "token": target.token,
        "body": {"message": "browser disconnect fixture", "confirmedIntent": "simple_chat"},
    }), capture_output=True, text=True, timeout=30, check=False)
    diagnostic = re.sub(r"(?i)bearer\s+\S+", "Bearer [redacted]", result.stderr[:1600])
    assert result.returncode == 0, f"Playwright browser disconnect fixture failed: {diagnostic}"
    report = object_value(json.loads(result.stdout))
    assert report["firstContent"] == "first" and report["healthStatus"] == 200
    assert isinstance(report["concurrentSeconds"], (int, float)) and report["concurrentSeconds"] < 1.5
    assert not target.provider.finished.is_set()
    _assert_aborted(target, report["conversationId"])
