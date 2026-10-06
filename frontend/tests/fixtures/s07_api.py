"""Disposable FastAPI/model fixture for the browser-to-SSE S07 test."""

from __future__ import annotations

import argparse
import json
import os
import threading
import time
from collections import deque
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

import uvicorn
from sqlalchemy import create_engine, event
from sqlalchemy.engine import URL
from sqlalchemy.orm import sessionmaker


def frame(value: dict[str, object] | str) -> bytes:
    return f"data: {value if isinstance(value, str) else json.dumps(value)}\n\n".encode()


def model_reply(content: str) -> list[bytes]:
    return [frame({"choices": [{"delta": {"content": content}}]}),
            frame({"usage": {"prompt_tokens": 6, "completion_tokens": 4, "total_tokens": 10}}),
            frame("[DONE]")]


def tool_reply(db_id: int, statement: str) -> list[bytes]:
    arguments = json.dumps({"db_id": db_id, "statement": statement})
    packet = {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "s07_query",
              "function": {"name": "executeSql", "arguments": arguments}}]}}]}
    return [frame(packet), frame("[DONE]")]


class ModelServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, replies: list[list[bytes]]) -> None:
        self.replies = deque(replies)
        self.requests: list[dict[str, object]] = []
        super().__init__(("127.0.0.1", 0), ModelHandler)


class ModelHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self) -> None:
        server = self.server
        if not isinstance(server, ModelServer):
            raise TypeError("Unexpected model server")
        length = int(self.headers["Content-Length"])
        server.requests.append(json.loads(self.rfile.read(length)))
        if not server.replies:
            self.send_error(500, "Unexpected model call")
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()
        for chunk in server.replies.popleft():
            self.wfile.write(chunk)
            self.wfile.flush()

    def log_message(self, _format: str, *_args: object) -> None:
        return


def initialize(args: argparse.Namespace) -> tuple[ModelServer, threading.Thread, int]:
    backend_dir = Path(__file__).resolve().parents[3] / "backend"
    os.environ["SQLCHAT_DATABASE_URL"] = f"sqlite:///{Path(args.system_db).as_posix()}"
    os.environ["SQLCHAT_ENCRYPT_KEY"] = "0123456789abcdef0123456789abcdef"
    import sys

    sys.path.insert(0, str(backend_dir))
    from app.adapters.registry import get_adapter
    from app.core.database import Base, engine
    from app.core.security import encrypt, token_digest
    from app.models import AuthSession, DbConfig, User, UserModelConfig
    from app.services.model_config import initialize_providers

    @event.listens_for(engine, "connect")
    def attach_schema(connection: object, _record: object) -> None:
        connection.execute("ATTACH DATABASE ? AS app", (str(Path(args.app_db)),))

    Base.metadata.create_all(engine)
    provider = ModelServer([
        model_reply(json.dumps({"intent": "sql_query", "confidence": 0.99,
                                "reasoning": "The question needs a database.",
                                "needsClarification": False,
                                "taskGoal": {"mode": "statement_execution", "dbIds": [1],
                                             "tableScope": [{"dbId": 1, "tables": [args.table]}],
                                             "confidence": 0.99, "needsClarification": False,
                                             "reasoning": "Count persisted table rows."}})),
        tool_reply(1, f"SELECT COUNT(*) AS count FROM {args.table}"),
        model_reply("The count query completed; prepare the final report."),
        model_reply(json.dumps({"report": "There are 2 rows in the browser fixture.", "complete": True})),
        model_reply(json.dumps({"intent": "sql_query", "confidence": 0.99,
                                "reasoning": "The follow-up still needs the selected database.",
                                "needsClarification": False,
                                "taskGoal": {"mode": "statement_execution", "dbIds": [1],
                                             "tableScope": [{"dbId": 1, "tables": [args.table]}],
                                             "confidence": 0.99, "needsClarification": False,
                                             "reasoning": "Count persisted table rows."}})),
        tool_reply(1, f"SELECT COUNT(*) AS count FROM {args.table}"),
        model_reply("The continued count query completed; prepare the final report."),
        model_reply(json.dumps({"report": "The continued query also found 2 rows.", "complete": True})),
    ])
    provider_thread = threading.Thread(target=provider.serve_forever, daemon=True)
    provider_thread.start()
    provider_host, provider_port = provider.server_address

    requested_target_type = os.environ.get("SQLCHAT_E2E_TARGET_DB")
    target_type = requested_target_type
    if target_type in ("postgresql", "mysql"):
        prefix = "SQLCHAT_TEST_PG" if target_type == "postgresql" else "SQLCHAT_TEST_MYSQL"
        values = {key: os.environ.get(f"{prefix}_{key.upper()}")
                  for key in ("host", "port", "db", "user", "password")}
        if any(value is None for value in values.values()):
            raise RuntimeError(f"{prefix}_HOST/PORT/DB/USER/PASSWORD are required for a real target")
        target_engine = create_engine(URL.create(
            "postgresql+psycopg" if target_type == "postgresql" else "mysql+pymysql",
            username=values["user"], password=values["password"], host=values["host"],
            port=int(values["port"]), database=values["db"],
        ))
        host, port, db_name, username, password = (values[key] for key in ("host", "port", "db", "user", "password"))
    else:
        target_type = "postgresql-sqlite-substitute"
        target_engine = create_engine(f"sqlite:///{Path(args.target_db).as_posix()}")
        host, port, db_name, username, password = "s07-test-process", 5432, "s07", "fixture", "fixture"
        adapter = get_adapter("postgresql")
        adapter._engine = lambda _config, _timeout: create_engine(  # type: ignore[method-assign]
            f"sqlite:///{Path(args.target_db).as_posix()}"
        )
        adapter._set_timeout = lambda *_values: None  # type: ignore[method-assign]
        adapter.metadata_schema = None
        read_table = adapter._read_table

        def read_sqlite_table(connection: object, inspector: object, table_name: str):
            inspector.get_table_comment = lambda *_args, **_kwargs: {"text": None}  # type: ignore[attr-defined]
            return read_table(connection, inspector, table_name)

        adapter._read_table = read_sqlite_table  # type: ignore[method-assign]

    with target_engine.begin() as connection:
        if target_type == "postgresql":
            connection.exec_driver_sql(f'CREATE TABLE "{args.table}" (id INTEGER PRIMARY KEY, label TEXT)')
            connection.exec_driver_sql(f'INSERT INTO "{args.table}" VALUES (1, \'first\'), (2, \'second\')')
        else:
            connection.exec_driver_sql(f"CREATE TABLE {args.table} (id INTEGER PRIMARY KEY, label TEXT)")
            connection.exec_driver_sql(f"INSERT INTO {args.table} VALUES (1, 'first'), (2, 'second')")

    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as session:
        initialize_providers(session)
        user = User(username="s07-browser", password_hash="unused", nickname="S07 Browser", status=1)
        session.add(user)
        session.flush()
        token = "s07-browser-session-token"
        session.add(AuthSession(token_hash=token_digest(token), user_id=user.id,
                                expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1),
                                last_active_at=datetime.now(UTC).replace(tzinfo=None)))
        database = DbConfig(user_id=user.id, name="S07 target", db_type=(requested_target_type or "postgresql"), host=host,
                            port=int(port), db_name=str(db_name), username=str(username),
                            password_encrypted=encrypt(str(password)), status=1)
        session.add(database)
        session.flush()
        database_id = database.id
        session.add(UserModelConfig(user_id=user.id, provider_code="custom",
                                    display_name="S07 local model", base_url=f"http://{provider_host}:{provider_port}",
                                    api_key_encrypted=encrypt("local-test-only"), model_name="s07-fixture",
                                    context_window=8192, is_default=True, status=1))
        session.commit()
    print(f"S07_TARGET_MODE={target_type}", flush=True)
    target_engine.dispose()
    return provider, provider_thread, database_id


class ControlHandler(BaseHTTPRequestHandler):
    stop: threading.Event

    def do_POST(self) -> None:
        if self.path != "/stop":
            self.send_error(404)
            return
        self.stop.set()
        self.send_response(204)
        self.end_headers()

    def log_message(self, _format: str, *_args: object) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--control-port", type=int, required=True)
    parser.add_argument("--system-db", required=True)
    parser.add_argument("--app-db", required=True)
    parser.add_argument("--target-db", required=True)
    parser.add_argument("--table", default=f"s07_{uuid4().hex[:12]}")
    args = parser.parse_args()
    provider, provider_thread, _db_id = initialize(args)
    from app.main import app

    stop = threading.Event()
    ControlHandler.stop = stop
    control = ThreadingHTTPServer(("127.0.0.1", args.control_port), ControlHandler)
    threading.Thread(target=control.serve_forever, daemon=True).start()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=args.port, log_level="warning"))
    api_thread = threading.Thread(target=server.run, daemon=True)
    api_thread.start()
    while not server.started:
        if not api_thread.is_alive():
            raise RuntimeError("FastAPI fixture server failed to start")
        time.sleep(0.05)
    print("S07_API_READY", flush=True)
    stop.wait()
    server.should_exit = True
    api_thread.join(timeout=5)
    provider.shutdown()
    provider.server_close()
    provider_thread.join(timeout=2)
    control.shutdown()
    control.server_close()
    if os.environ.get("SQLCHAT_E2E_TARGET_DB") in ("postgresql", "mysql"):
        prefix = "SQLCHAT_TEST_PG" if os.environ["SQLCHAT_E2E_TARGET_DB"] == "postgresql" else "SQLCHAT_TEST_MYSQL"
        values = {key: os.environ[f"{prefix}_{key.upper()}"]
                  for key in ("host", "port", "db", "user", "password")}
        target_engine = create_engine(URL.create(
            "postgresql+psycopg" if prefix == "SQLCHAT_TEST_PG" else "mysql+pymysql",
            username=values["user"], password=values["password"], host=values["host"],
            port=int(values["port"]), database=values["db"],
        ))
        with target_engine.begin() as connection:
            connection.exec_driver_sql(f"DROP TABLE IF EXISTS {args.table}")
        target_engine.dispose()


if __name__ == "__main__":
    main()
