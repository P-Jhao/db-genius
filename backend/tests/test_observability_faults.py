"""Real local stalled TCP, probe cleanup, and queue failure semantics."""

import socket
import threading
from time import monotonic
from unittest.mock import Mock

import pytest
from kombu.exceptions import OperationalError  # type: ignore[import-untyped]
from sqlalchemy.orm import Session, sessionmaker

from app.core import observability_health as health
from app.core.config import Settings
from app.core.observability_metrics import REGISTRY
from app.models import DbConfig
from app.services import db_config
from app.tasks import db_config as queue_task

pytest_plugins = ["test_db_config_partial"]


def test_stalled_local_amqp_handshake_times_out_and_closes() -> None:
    stopped = threading.Event()
    accepted = threading.Event()
    closed = threading.Event()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(2)
        port = listener.getsockname()[1]

        def stall() -> None:
            connection, _address = listener.accept()
            with connection:
                accepted.set()
                stopped.wait(timeout=3)
                connection.settimeout(1)
                data = connection.recv(4096)
                # Client may have sent the protocol header before disconnecting.
                while data:
                    data = connection.recv(4096)
                closed.set()

        thread = threading.Thread(target=stall, daemon=True)
        thread.start()
        started = monotonic()
        try:
            with pytest.raises(OperationalError):
                health.broker_ready(Settings(broker_url=f"amqp://synthetic:synthetic@127.0.0.1:{port}//",
                                             ready_broker_timeout_seconds=0.2))
            assert monotonic() - started < 3
            assert accepted.is_set()
        finally:
            stopped.set()
            thread.join(timeout=2)
        assert not thread.is_alive() and closed.is_set()


def test_engine_is_disposed_after_failed_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = Mock()
    engine.connect.side_effect = ConnectionError("SYNTHETIC_PRIVATE_URL")
    monkeypatch.setattr(health, "probe_engine", lambda _settings: engine)
    with pytest.raises(ConnectionError):
        health.migration_ready(Settings())
    engine.dispose.assert_called_once()


def test_queue_failure_counts_once_without_changing_status_or_args(
    store: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(db_config, "get_settings", lambda: Settings(
        broker_url="amqp://fixture:synthetic-password@local.invalid//"))
    publish = Mock(side_effect=OperationalError("synthetic-password"))
    monkeypatch.setattr(queue_task.verify_config, "apply_async", publish)
    before = REGISTRY.get_sample_value("sqlchat_queue_publications_total", {"outcome": "error"})
    with store() as session:
        assert db_config._enqueue(session, 12, 1) is False
        config = session.get(DbConfig, 12)
        assert config is not None and config.status == 2
        assert config.verification_error is not None and "synthetic-password" not in config.verification_error
    publish.assert_called_once_with(args=(12, 1), headers={"locale": "en"})
    after = REGISTRY.get_sample_value("sqlchat_queue_publications_total", {"outcome": "error"})
    assert after == (0 if before is None else before) + 1
