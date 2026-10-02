"""Portable lock-boundary simulation; real Linux flock is a deployment gate."""

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from prometheus_client import values
from pydantic import ValidationError

from app.core import observability_metrics_lock as locks
from app.core import observability_multiprocess as multiprocess
from app.core.config import Settings


def test_shared_services_block_epoch_init_until_all_descriptors_close(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    held: dict[int, int] = {}
    calls: list[int] = []

    def flock(descriptor: int, flags: int) -> None:
        calls.append(flags)
        if held and ((flags & 2) or any(mode & 2 for mode in held.values())):
            raise BlockingIOError("synthetic live process")
        held[descriptor] = flags

    def close(descriptor: int) -> None:
        held.pop(descriptor, None)
        os.close(descriptor)

    monkeypatch.setitem(sys.modules, "fcntl", SimpleNamespace(LOCK_SH=1, LOCK_EX=2, LOCK_NB=4, flock=flock))
    monkeypatch.setattr(locks, "os", SimpleNamespace(name="posix", open=os.open, close=close,
                                                     O_CREAT=os.O_CREAT, O_RDWR=os.O_RDWR))
    api, worker = locks.acquire_shared(tmp_path), locks.acquire_shared(tmp_path)
    try:
        with pytest.raises(RuntimeError, match="live service"), locks.exclusive_epoch(tmp_path):
            pytest.fail("Initializer cannot hold an exclusive lease with live services")
        api.close()
        with pytest.raises(RuntimeError, match="live service"), locks.exclusive_epoch(tmp_path):
            pytest.fail("Remaining worker still owns a shared descriptor")
        worker.close()
        with locks.exclusive_epoch(tmp_path) as root:
            assert root == tmp_path.resolve()
            with pytest.raises(RuntimeError, match="live service"):
                locks.acquire_shared(tmp_path)
    finally:
        api.close()
        worker.close()
    assert not held and all(flag & 4 for flag in calls)
    assert set(calls) == {5, 6}


def test_writer_configuration_must_precede_import_and_match_service(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    for name in ("api", "worker"):
        (tmp_path / name).mkdir()
    settings = Settings(metrics_multiprocess_root=str(tmp_path))
    monkeypatch.setattr(multiprocess, "_lease", None)
    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(tmp_path / "worker"))
    with pytest.raises(ValueError, match="fixed service"):
        multiprocess.start_metrics(settings, service="api")
    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(tmp_path / "api"))
    monkeypatch.setattr(values, "ValueClass", SimpleNamespace(_multiprocess=False))
    with pytest.raises(RuntimeError, match="before importing"):
        multiprocess.start_metrics(settings, service="api")
    lease = Mock(spec=locks.MetricsLease)
    acquire = Mock(return_value=lease)
    monkeypatch.setattr(values, "ValueClass", SimpleNamespace(_multiprocess=True))
    monkeypatch.setattr(multiprocess, "acquire_shared", acquire)
    try:
        multiprocess.start_metrics(settings, service="api")
        multiprocess.start_metrics(settings, service="api")
        acquire.assert_called_once_with(tmp_path)
    finally:
        multiprocess.close_metrics()
    lease.close.assert_called_once()


def test_shared_mode_never_silently_falls_back(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(tmp_path))
    with pytest.raises(ValueError, match="must be configured"):
        multiprocess.start_metrics(Settings(metrics_multiprocess_root=""), service="api")
    with pytest.raises(ValidationError, match="absolute path"):
        Settings(metrics_multiprocess_root="relative/path")
    (tmp_path / "api").mkdir()
    (tmp_path / "worker").mkdir()
    (tmp_path / "worker" / "gauge_all_1.db").touch()
    with pytest.raises(ValueError, match="Unsupported metric file"):
        list(multiprocess.ServiceMetricsCollector(tmp_path).collect())
