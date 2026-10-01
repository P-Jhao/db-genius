"""Partial metadata stays connected; failures and stale callbacks remain distinct."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.types import SchemaMetadata
from app.core.config import get_settings
from app.core.database import Base
from app.core.errors import BusinessError
from app.core.security import encrypt
from app.models import DbConfig, User
from app.services import database_tools, db_config, db_config_worker


def metadata(partial: bool) -> SchemaMetadata:
    return {"dbType": "mysql", "databaseName": "synthetic", "host": "localhost", "port": 3306,
            "tables": [{"name": "items", "comment": None, "rowCount": 1,
                        "columns": [{"name": "id", "type": "INT", "nullable": False,
                                     "primaryKey": True, "comment": None}], "indexes": []}],
            "incomplete": partial, "errorMessage": "indexes unavailable" if partial else None}


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    monkeypatch.setenv("SQLCHAT_ENCRYPT_KEY", "0123456789abcdef0123456789abcdef")
    get_settings.cache_clear()
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'system.sqlite'}",
                           execution_options={"schema_translate_map": {"app": None}})
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db_config_worker, "SessionLocal", factory)
    monkeypatch.setattr(database_tools, "SessionLocal", factory)
    with factory() as session:
        session.add_all([User(id=1, username="owner", password_hash="unused"),
                         User(id=2, username="outsider", password_hash="unused")])
        session.add(DbConfig(id=12, user_id=1, name="fixture", db_type="mysql", host="localhost",
                             port=3306, db_name="synthetic", username="fixture",
                             password_encrypted=encrypt("synthetic-password"), status=0,
                             builtin=False, verification_version=1))
        session.commit()
    try:
        yield factory
    finally:
        engine.dispose()
        get_settings.cache_clear()


def adapter_for(monkeypatch: pytest.MonkeyPatch, partial: bool = True) -> Mock:
    adapter = Mock()
    adapter.test_connection.return_value = True
    adapter.extract_metadata.return_value = metadata(partial)
    adapter.execute.return_value = {"success": True, "rowCount": 1, "data": [{"id": 1}],
                                    "truncated": False}
    for module in (db_config, db_config_worker, database_tools):
        monkeypatch.setattr(module, "get_adapter", lambda _db_type: adapter)
    return adapter


def verify(store: sessionmaker[Session], flow: str) -> None:
    if flow == "worker":
        db_config_worker.verify_and_generate(12, 1)
    else:
        with store() as session:
            db_config.generate_doc(session, 1, 12)


@pytest.mark.parametrize("flow", ("worker", "manual"))
@pytest.mark.parametrize("partial", (False, True))
def test_complete_and_partial_paths_keep_connected_with_honest_document(
    store: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch, flow: str, partial: bool,
) -> None:
    adapter = adapter_for(monkeypatch, partial)
    verify(store, flow)
    with store() as session:
        config = session.get(DbConfig, 12)
        assert config is not None and config.status == 1 and config.verification_error is None
        assert config.doc_generated_at is not None
        document = db_config.get_doc(session, 1, 12)
        assert "## Table: items" in document
        assert ("Error reading metadata" in document) is partial
        if partial:
            assert "indexes unavailable" in document
    adapter.test_connection.assert_called_once()
    assert database_tools.get_schema(1, 12)["incomplete"] is partial
    assert database_tools.execute_statement(1, 12, "SELECT id FROM items")["data"] == [{"id": 1}]
    calls = adapter.execute.call_count
    for operation in (lambda: database_tools.get_schema(2, 12),
                      lambda: database_tools.execute_statement(2, 12, "SELECT id FROM items")):
        with pytest.raises(BusinessError) as denied:
            operation()
        assert denied.value.code == 404
    assert adapter.execute.call_count == calls


def test_manual_refresh_requeues_and_keeps_partial_warning_on_new_version(
    store: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter_for(monkeypatch)
    db_config_worker.verify_and_generate(12, 1)
    queued = Mock(return_value=True)
    monkeypatch.setattr(db_config, "_enqueue", queued)
    with store() as session:
        db_config.refresh_doc(session, 1, 12)
        pending = session.get(DbConfig, 12)
        assert pending is not None and pending.status == 0 and pending.doc_content is None
        assert pending.verification_version == 2
    queued.assert_called_once()
    db_config_worker.verify_and_generate(12, 1)
    with store() as session:
        unchanged = session.get(DbConfig, 12)
        assert unchanged is not None and unchanged.status == 0 and unchanged.doc_content is None
    db_config_worker.verify_and_generate(12, 2)
    with store() as session:
        connected = session.get(DbConfig, 12)
        assert connected is not None and connected.status == 1
        assert "indexes unavailable" in db_config.get_doc(session, 1, 12)


@pytest.mark.parametrize("flow", ("worker", "manual"))
@pytest.mark.parametrize("failure", ("connect_false", "connect_error", "extract", "render"))
def test_actual_failures_still_persist_failed_and_no_document(
    store: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch, flow: str, failure: str,
) -> None:
    adapter = adapter_for(monkeypatch)
    if failure == "connect_false":
        adapter.test_connection.return_value = False
    elif failure == "connect_error":
        adapter.test_connection.side_effect = ConnectionError("connection rejected synthetic-password")
    elif failure == "extract":
        adapter.extract_metadata.side_effect = RuntimeError("extraction failed synthetic-password")
    else:
        module = db_config_worker if flow == "worker" else db_config
        monkeypatch.setattr(module, "render_document", Mock(side_effect=RuntimeError("render failed")))
    if flow == "manual":
        with pytest.raises(BusinessError) as raised:
            verify(store, flow)
        assert raised.value.code == 400
    else:
        verify(store, flow)
    with store() as session:
        config = session.get(DbConfig, 12)
        assert config is not None and config.status == 2
        assert config.doc_content is None and config.doc_generated_at is None
        assert config.verification_error is not None
        assert "synthetic-password" not in config.verification_error
    if failure.startswith("connect"):
        adapter.extract_metadata.assert_not_called()


@pytest.mark.parametrize("flow", ("worker", "manual"))
@pytest.mark.parametrize("action", ("new_version", "delete"))
def test_partial_callback_cannot_overwrite_newer_or_deleted_config(
    store: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch, flow: str, action: str,
) -> None:
    adapter = adapter_for(monkeypatch)

    def change_during_extract(_connection: object) -> SchemaMetadata:
        with store() as session:
            config = session.get(DbConfig, 12)
            assert config is not None
            if action == "delete":
                session.delete(config)
            else:
                config.verification_version += 1
                config.doc_content = "newer version sentinel"
                config.status = 0
            session.commit()
        return metadata(True)

    adapter.extract_metadata.side_effect = change_during_extract
    if flow == "manual":
        with pytest.raises(BusinessError) as raised:
            verify(store, flow)
        assert raised.value.code == 409
    else:
        verify(store, flow)
    with store() as session:
        config = session.get(DbConfig, 12)
        if action == "delete":
            assert config is None
        else:
            assert config is not None and config.status == 0
            assert config.verification_version == (2 if flow == "worker" else 3)
            assert config.doc_content == "newer version sentinel"
            assert config.doc_generated_at is None


def test_stale_or_deleted_worker_exits_before_adapter_lookup(
    store: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch,
) -> None:
    lookup = Mock(side_effect=AssertionError("stale callback must not touch target"))
    monkeypatch.setattr(db_config_worker, "get_adapter", lookup)
    db_config_worker.verify_and_generate(12, 0)
    with store() as session:
        config = session.get(DbConfig, 12)
        assert config is not None
        session.delete(config)
        session.commit()
    db_config_worker.verify_and_generate(12, 1)
    lookup.assert_not_called()
