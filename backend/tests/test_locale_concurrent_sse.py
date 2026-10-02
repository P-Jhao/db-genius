"""Concurrent POST SSE sends separate language prompts to a real HTTP provider mock."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler

from fastapi.testclient import TestClient
from test_chat_api import parse_events
from test_model_protocol import Provider, frame

from app.models import DbConfig, User

pytest_plugins = ["test_chat_api"]


class LocaleHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    barrier = threading.Barrier(2)

    def do_POST(self) -> None:
        server = self.server
        assert isinstance(server, Provider)
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        server.requests.append(request)
        messages = request["messages"]
        systems = "\n".join(message["content"] for message in messages if message["role"] == "system")
        names = [name for name in ("French", "Japanese") if f"You MUST respond in {name}." in systems]
        assert len(names) == 1
        self.barrier.wait(timeout=15)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()
        for content in ("synthetic ", names[0]):
            self.wfile.write(frame({"choices": [{"delta": {"content": content}}]}))
            self.wfile.flush()
        self.wfile.write(frame({"usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6}}))
        self.wfile.write(frame("[DONE]"))
        self.wfile.flush()

    def log_message(self, format: str, *args: object) -> None:
        pass


def test_concurrent_sse_and_history_do_not_cross_language_or_usage(
    chat_client: tuple[TestClient, User, User, DbConfig], provider: Provider,
) -> None:
    client, _, _, _ = chat_client
    provider.RequestHandlerClass = LocaleHandler
    LocaleHandler.barrier = threading.Barrier(2)

    def ask(locale: str) -> tuple[str, int]:
        response = client.post("/api/chat", headers={"Accept-Language": locale},
                               json={"message": "hello", "confirmedIntent": "simple_chat"})
        events = parse_events(response.text)
        assert not any(event["type"] in {"error", "aborted"} for event in events)
        text = "".join(str(event["content"]) for event in events if event["type"] == "content")
        conversation_id = events[0]["content"]
        assert isinstance(conversation_id, int)
        history = client.get(f"/api/chat/conversations/{conversation_id}/messages").json()["data"]
        assert history[-1]["content"] == text
        usage = next(event["content"] for event in events if event["type"] == "usage")
        assert isinstance(usage, dict)
        assert usage["callCount"] == 1 and usage["totalTokens"] == 6
        return text, conversation_id

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(ask, ["fr", "ja"]))
    assert [value[0] for value in results] == ["synthetic French", "synthetic Japanese"]
    assert len({value[1] for value in results}) == 2 and len(provider.requests) == 2
