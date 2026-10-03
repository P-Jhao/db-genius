"""Real CSV storage and relational targets through the LangGraph workflow."""

from __future__ import annotations

import json
import os
import socket
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Self
from uuid import uuid4

import httpx
import pytest
from fastapi import UploadFile
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session, sessionmaker
from test_model_protocol import Handler, Provider, frame, model

from app.adapters import DbConnectionConfig, get_adapter
from app.agent.graph import RunContext, run_graph
from app.agent.streaming import ModelStream
from app.agent.tools import RunTools
from app.agent.types import ChatRequest, Usage
from app.core.config import Settings
from app.core.database import Base
from app.models import DbConfig, UploadedFile, User
from app.services import database_tools, file_tools, file_upload
from app.storage import backend

USER_ID = 731
DB_ID = 7311
CSV = "id,name,city\n1,Ada,杭州\n2,Lin,深圳\n".encode()


class DropConnection(Handler):
    def do_POST(self) -> None:
        server = self.server
        assert isinstance(server, Provider)
        if not server.replies or server.replies[0] != 0:
            super().do_POST()
            return
        server.replies.pop(0)
        length = int(self.headers["Content-Length"])
        request = json.loads(self.rfile.read(length))
        if not isinstance(request, dict):
            raise TypeError("Model request must be an object")
        server.requests.append(request)
        server.paths.append(self.path)
        self.close_connection = True
        self.connection.shutdown(socket.SHUT_RDWR)
        self.connection.close()


@pytest.fixture
def provider() -> Iterator[Provider]:
    service = Provider([])
    thread = threading.Thread(target=service.serve_forever, daemon=True)
    thread.start()
    yield service
    service.shutdown()
    service.server_close()
    thread.join(timeout=2)


@pytest.fixture
def upload_store(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'metadata.sqlite'}",
                           execution_options={"schema_translate_map": {"app": None}})
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as session:
        session.add(User(id=USER_ID, username="workflow-owner", password_hash="unused",
                         role="user", status=1))
        session.commit()
    monkeypatch.setattr(file_upload, "SessionLocal", factory)
    monkeypatch.setattr(backend, "get_settings", lambda: Settings(
        storage_backend="local", storage_root=str(tmp_path / "uploads")))
    try:
        yield factory
    finally:
        engine.dispose()


def upload_csv(factory: sessionmaker[Session], content: bytes = CSV) -> UploadedFile:
    with factory() as session:
        return file_upload.upload_file(session, USER_ID, UploadFile(
            filename="source.csv", file=BytesIO(content), headers={"content-type": "text/csv"}))


def target_config(db_type: str) -> DbConnectionConfig:
    prefix = "SQLCHAT_TEST_PG" if db_type == "postgresql" else "SQLCHAT_TEST_MYSQL"
    values = {key: os.environ.get(f"{prefix}_{key}") for key in
              ("HOST", "PORT", "DB", "USER", "PASSWORD")}
    if any(value is None for value in values.values()):
        pytest.skip(f"Isolated {db_type} target credentials are required")
    host, port, database, username, password = (values[key] for key in
                                                 ("HOST", "PORT", "DB", "USER", "PASSWORD"))
    assert host is not None and port is not None and database is not None
    assert username is not None and password is not None
    return DbConnectionConfig(db_type, host, int(port), database, username, password)


@contextmanager
def target_table(db_type: str) -> Iterator[tuple[DbConnectionConfig, str]]:
    config = target_config(db_type)
    adapter = get_adapter(db_type)
    engine = adapter._engine(config, 30)  # type: ignore[attr-defined]
    table = f"s10_import_{uuid4().hex[:12]}"
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(f"CREATE TABLE {table} ("
                                       "id INTEGER PRIMARY KEY, name VARCHAR(40) NOT NULL, "
                                       "city VARCHAR(40) NOT NULL)")
        yield config, table
    finally:
        try:
            with engine.begin() as connection:
                connection.exec_driver_sql(f"DROP TABLE IF EXISTS {table}")
            with engine.connect() as connection:
                assert not inspect(connection).has_table(table)
        finally:
            engine.dispose()


def install_target(monkeypatch: pytest.MonkeyPatch, config: DbConnectionConfig) -> None:
    row = SimpleNamespace(user_id=USER_ID, status=1, db_type=config.db_type)

    class ConfigSession:
        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def get(self, model_type: object, db_id: int) -> object | None:
            if model_type is not DbConfig:
                raise TypeError("Expected DbConfig lookup")
            return row if db_id == DB_ID else None

        def expunge(self, _record: object) -> None:
            return None

    def connection_for(record: object) -> DbConnectionConfig:
        if record is not row:
            raise ValueError("Unknown test configuration")
        return config

    monkeypatch.setattr(database_tools, "SessionLocal", ConfigSession)
    monkeypatch.setattr(database_tools, "connection_for", connection_for)


def tool_reply(name: str, args: dict[str, object], call_id: str) -> list[bytes]:
    return [frame({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": call_id,
             "function": {"name": name, "arguments": json.dumps(args)}}]}}]}), frame("[DONE]")]


def answer_reply(content: str) -> list[bytes]:
    return [frame({"choices": [{"delta": {"content": content}}]}), frame("[DONE]")]


def request_for(file_id: int) -> ChatRequest:
    return ChatRequest.model_validate({"message": "Import the attached CSV and verify every row",
                                       "dbConfigIds": [DB_ID], "fileIds": [file_id],
                                       "confirmedIntent": "workflow"})


async def run(provider: Provider, file_id: int) -> tuple[str, list[tuple[str, object]]]:
    events: list[tuple[str, object]] = []

    async def emit(kind: str, content: object, _step: int) -> None:
        events.append((kind, content))

    request = request_for(file_id)
    context = RunContext(request, [], "en", ModelStream(model(provider), emit, Usage()),
                         RunTools(USER_ID, request), emit)
    result = await run_graph(context)
    return result["answer"], events


def actual_rows(config: DbConnectionConfig, table: str) -> list[tuple[object, ...]]:
    engine = get_adapter(config.db_type)._engine(config, 30)  # type: ignore[attr-defined]
    try:
        with engine.connect() as connection:
            return [tuple(row) for row in connection.exec_driver_sql(
                f"SELECT id, name, city FROM {table} ORDER BY id")]
    finally:
        engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("db_type", ["postgresql", "mysql"])
async def test_actual_upload_import_and_row_verification(
    db_type: str, provider: Provider, upload_store: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with target_table(db_type) as (config, table):
        install_target(monkeypatch, config)
        uploaded = upload_csv(upload_store)
        insert = (f"INSERT INTO {table} (id, name, city) VALUES "
                  "(1, 'Ada', '杭州'), (2, 'Lin', '深圳')")
        select = f"SELECT id, name, city FROM {table} ORDER BY id"
        provider.replies = [tool_reply("readFile", {"file_id": uploaded.id}, "source"),
                            tool_reply("executeSql", {"db_id": DB_ID, "statement": insert}, "insert"),
                            tool_reply("executeSql", {"db_id": DB_ID, "statement": select}, "verify"),
                            tool_reply("doTerminate", {"reason": "verified"}, "done"),
                            answer_reply(json.dumps({"report": "Two source rows were imported and verified.",
                                                     "complete": True}))]
        result, events = await run(provider, uploaded.id)
        assert result == "Two source rows were imported and verified."
        assert actual_rows(config, table) == [(1, "Ada", "杭州"), (2, "Lin", "深圳")]
        read_steps = [content for kind, content in events if kind == "step" and
                      isinstance(content, str) and content.startswith("readFile: ")]
        assert len(read_steps) == 1
        source = json.loads(read_steps[0].removeprefix("readFile: "))
        assert source["fileName"] == "source.csv" and source["format"] == "csv"
        assert source["headers"] == ["id", "name", "city"]
        assert source["totalRows"] == 2 and source["truncated"] is False
        assert source["data"] == [{"id": "1", "name": "Ada", "city": "杭州"},
                                  {"id": "2", "name": "Lin", "city": "深圳"}]
        assert len(provider.requests) == 5
        next_messages = provider.requests[1]["messages"]
        assert isinstance(next_messages, list)
        assert next_messages[-1]["tool_call_id"] == "source"
        assert "杭州" in next_messages[-1]["content"]


@pytest.mark.asyncio
@pytest.mark.parametrize("db_type", ["postgresql", "mysql"])
async def test_model_http_failure_after_committed_write_does_not_repeat_insert(
    db_type: str, provider: Provider, upload_store: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with target_table(db_type) as (config, table):
        install_target(monkeypatch, config)
        uploaded = upload_csv(upload_store)
        insert = f"INSERT INTO {table} (id, name, city) VALUES (1, 'Ada', '杭州')"
        provider.RequestHandlerClass = DropConnection
        provider.replies = [tool_reply("readFile", {"file_id": uploaded.id}, "source"),
                            tool_reply("executeSql", {"db_id": DB_ID, "statement": insert}, "insert"),
                            0]
        with pytest.raises((httpx.TransportError, RuntimeError)) as failure:
            await run(provider, uploaded.id)
        if isinstance(failure.value, RuntimeError):
            assert "HTTP 502" in str(failure.value)
        assert actual_rows(config, table) == [(1, "Ada", "杭州")]
        assert len(provider.requests) == 3 and provider.replies == []


def test_real_uploaded_csv_keeps_200_row_boundary(
    upload_store: sessionmaker[Session],
) -> None:
    content = ("id,name,city\n" + "".join(f"{i},Name{i},City{i}\n" for i in range(1, 202))).encode()
    uploaded = upload_csv(upload_store, content)
    parsed = file_tools.read_file(USER_ID, uploaded.id)
    assert parsed["fileName"] == "source.csv" and parsed["format"] == "csv"
    assert parsed["headers"] == ["id", "name", "city"]
    assert parsed["totalRows"] == 201 and parsed["truncated"] is True
    data = parsed["data"]
    assert isinstance(data, list) and len(data) == 200
    assert data[0] == {"id": "1", "name": "Name1", "city": "City1"}
    assert data[-1] == {"id": "200", "name": "Name200", "city": "City200"}
    assert not any(row.get("id") == "201" for row in data if isinstance(row, dict))
