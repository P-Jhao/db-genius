"""Real HTTP/SSE protocol tests for OpenAI-compatible model adapters."""

import asyncio
import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from langchain_core.messages import HumanMessage, ToolMessage
from pydantic import SecretStr

from app.agent.model import CompatibleChatModel, completion_url
from app.agent.streaming import ModelStream
from app.agent.types import Usage


def frame(packet: dict[str, object] | str) -> bytes:
    data = packet if isinstance(packet, str) else json.dumps(packet)
    return f"data: {data}\n\n".encode()


class Provider(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, replies: list[list[bytes] | int]) -> None:
        self.replies = replies
        self.requests: list[dict[str, object]] = []
        self.paths: list[str] = []
        super().__init__(("127.0.0.1", 0), Handler)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self) -> None:
        server = self.server
        assert isinstance(server, Provider)
        length = int(self.headers["Content-Length"])
        request = json.loads(self.rfile.read(length))
        server.requests.append(request)
        server.paths.append(self.path)
        reply = server.replies.pop(0)
        if isinstance(reply, int):
            self.send_response(reply)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()
        for part in reply:
            try:
                self.wfile.write(part)
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                break

    def log_message(self, format: str, *args: object) -> None:
        pass


@pytest.fixture
def provider() -> Iterator[Provider]:
    service = Provider([])
    thread = threading.Thread(target=service.serve_forever, daemon=True)
    thread.start()
    yield service
    service.shutdown()
    service.server_close()
    thread.join(timeout=2)


def model(provider: Provider, path: str = "") -> CompatibleChatModel:
    host, port = provider.server_address
    return CompatibleChatModel(
        base_url=f"http://{host}:{port}{path}", api_key=SecretStr("test-only"), model_name="test-model"
    )


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://api.deepseek.com", "https://api.deepseek.com/v1/chat/completions"),
        ("https://api.openai.com/v1/", "https://api.openai.com/v1/chat/completions"),
        ("http://localhost:11434", "http://localhost:11434/v1/chat/completions"),
        ("https://example.com/proxy/v1", "https://example.com/proxy/v1/chat/completions"),
        ("https://example.com/proxy/chat/completions", "https://example.com/proxy/chat/completions"),
    ],
)
def test_completion_url(url: str, expected: str) -> None:
    assert completion_url(url) == expected


@pytest.mark.parametrize(
    "url",
    ["", "localhost:11434", "ftp://example.com", "https://user:pass@host/v1", "https://host/v1?key=secret"],
)
def test_invalid_completion_url(url: str) -> None:
    with pytest.raises(ValueError):
        completion_url(url)


@pytest.mark.asyncio
async def test_tool_arguments_reasoning_usage_and_round_trip(provider: Provider) -> None:
    split_call = frame(
        {
            "choices": [
                {
                    "delta": {
                        "reasoning_content": "schema",
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": "executeSql", "arguments": '{"dbConfigId":'},
                            }
                        ],
                    }
                }
            ]
        }
    )
    provider.replies.extend(
        [
            [
                frame({"choices": [{"delta": {"reasoning_content": "inspect "}}]}),
                split_call[:9],
                split_call[9:27],
                split_call[27:],
                frame(
                    {
                        "choices": [
                            {
                                "delta": {
                                    "tool_calls": [
                                        {"index": 0, "function": {"arguments": ' 3, "sql": "SELECT 1"}'}}
                                    ]
                                }
                            }
                        ]
                    }
                ),
                frame(
                    {
                        "choices": [],
                        "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
                    }
                ),
                frame("[DONE]"),
            ],
            [frame({"choices": [{"delta": {"content": "One row."}}]}), frame("[DONE]")],
        ]
    )
    events: list[tuple[str, object, int]] = []

    async def emit(kind: str, content: object, step: int) -> None:
        events.append((kind, content, step))

    usage = Usage()
    stream = ModelStream(model(provider, "/proxy/v1"), emit, usage)
    assistant = await stream.call([HumanMessage(content="run query")], event="content")
    assert assistant.tool_calls == [
        {
            "name": "executeSql",
            "args": {"dbConfigId": 3, "sql": "SELECT 1"},
            "id": "call_1",
            "type": "tool_call",
        }
    ]
    assert assistant.additional_kwargs["reasoning_content"] == "inspect schema"
    assert events == [("reasoning", "inspect ", 0), ("reasoning", "schema", 0)]
    assert usage.callCount == 1 and usage.totalTokens == 18 and usage.contextTokens == 11

    follow_up = await stream.call(
        [HumanMessage(content="run query"), assistant, ToolMessage(content="one row", tool_call_id="call_1")]
    )
    assert follow_up.content == "One row."
    assert usage.callCount == 2 and usage.totalTokens == 18
    assert provider.paths == ["/proxy/v1/chat/completions"] * 2
    wire = provider.requests[1]["messages"]
    assert isinstance(wire, list)
    assert wire[1]["reasoning_content"] == "inspect schema"
    assert wire[1]["tool_calls"][0]["id"] == "call_1"
    assert wire[2]["tool_call_id"] == "call_1"
    assert provider.requests[0]["stream_options"] == {"include_usage": True}


@pytest.mark.asyncio
async def test_http_and_stream_errors(provider: Provider) -> None:
    provider.replies.extend([429, [frame({"error": {"message": "provider secret"}})]])

    async def emit(kind: str, content: object, step: int) -> None:
        pass

    usage = Usage()
    stream = ModelStream(model(provider), emit, usage)
    with pytest.raises(RuntimeError, match="HTTP 429"):
        await stream.call([HumanMessage(content="hello")])
    with pytest.raises(RuntimeError, match="stream error"):
        await stream.call([HumanMessage(content="hello")])
    assert usage.callCount == 2 and usage.totalTokens == 0


@pytest.mark.asyncio
async def test_invalid_tool_json_and_partial_usage(provider: Provider) -> None:
    provider.replies.extend(
        [
            [
                frame(
                    {
                        "choices": [
                            {
                                "delta": {
                                    "tool_calls": [
                                        {
                                            "index": 0,
                                            "id": "call_bad",
                                            "function": {"name": "executeSql", "arguments": "{bad json"},
                                        }
                                    ]
                                }
                            }
                        ]
                    }
                ),
                frame("[DONE]"),
            ],
            [frame({"choices": [], "usage": {"prompt_tokens": 5}}), frame("[DONE]")],
        ]
    )

    async def emit(kind: str, content: object, step: int) -> None:
        pass

    usage = Usage()
    stream = ModelStream(model(provider), emit, usage)
    with pytest.raises(ValueError, match="invalid tool-call JSON"):
        await stream.call([HumanMessage(content="hello")])
    with pytest.raises(TypeError, match="requires prompt and completion"):
        await stream.call([HumanMessage(content="hello")])
    assert usage.callCount == 2 and usage.totalTokens == 0


@pytest.mark.asyncio
async def test_cancel_closes_provider_stream(provider: Provider) -> None:
    provider.replies.append(
        [
            frame({"choices": [{"delta": {"content": "partial"}}]}),
            frame({"choices": [{"delta": {"content": "later"}}]}),
        ]
    )
    first = asyncio.Event()

    async def emit(kind: str, content: object, step: int) -> None:
        first.set()
        await asyncio.sleep(10)

    usage = Usage()
    stream = ModelStream(model(provider), emit, usage)
    task = asyncio.create_task(stream.call([HumanMessage(content="hello")]))
    await asyncio.wait_for(first.wait(), timeout=3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert stream.partial == "partial"
    assert usage.callCount == 1 and usage.totalTokens == 0
