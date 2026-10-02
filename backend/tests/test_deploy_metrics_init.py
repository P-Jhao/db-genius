from __future__ import annotations

import sys
import types
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path

import pytest

from deploy.init_metrics import initialize_metrics_epoch


class _MetricsLockModule(types.ModuleType):
    exclusive_epoch: Callable[[Path], AbstractContextManager[Path]]


def _install_lock_module(
    monkeypatch: pytest.MonkeyPatch,
    exclusive_epoch: Callable[[Path], AbstractContextManager[Path]],
) -> None:
    module = _MetricsLockModule("app.core.observability_metrics_lock")
    module.exclusive_epoch = exclusive_epoch
    monkeypatch.setitem(sys.modules, module.__name__, module)


def test_initialization_clears_only_metric_databases_under_both_service_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    metrics_root = tmp_path / "prometheus"
    api_root = metrics_root / "api"
    worker_root = metrics_root / "worker"
    api_root.mkdir(parents=True)
    worker_root.mkdir()
    (metrics_root / ".lifecycle.lock").write_text("lock", encoding="utf-8")
    (api_root / "counter_100.db").write_bytes(b"old api counter")
    (api_root / "histogram_100.db").write_bytes(b"old api histogram")
    (worker_root / "counter_200.db").write_bytes(b"old worker counter")
    (api_root / "notes.txt").write_text("keep", encoding="utf-8")
    (worker_root / "counter_200.db.bak").write_text("keep", encoding="utf-8")
    nested = worker_root / "nested"
    nested.mkdir()
    (nested / "counter_201.db").write_bytes(b"keep nested data")

    lock_roots: list[Path] = []

    @contextmanager
    def exclusive_epoch(root: Path) -> Iterator[Path]:
        lock_roots.append(root)
        yield root.resolve()

    _install_lock_module(monkeypatch, exclusive_epoch)
    removed = initialize_metrics_epoch(metrics_root)

    assert lock_roots == [metrics_root]
    assert removed == {"api": 2, "worker": 1}
    assert not (api_root / "counter_100.db").exists()
    assert not (api_root / "histogram_100.db").exists()
    assert not (worker_root / "counter_200.db").exists()
    assert (metrics_root / ".lifecycle.lock").read_text(encoding="utf-8") == "lock"
    assert (api_root / "notes.txt").read_text(encoding="utf-8") == "keep"
    assert (worker_root / "counter_200.db.bak").read_text(encoding="utf-8") == "keep"
    assert (nested / "counter_201.db").read_bytes() == b"keep nested data"


def test_initialization_refuses_a_live_service_epoch_without_deleting_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    metrics_root = tmp_path / "prometheus"
    api_root = metrics_root / "api"
    api_root.mkdir(parents=True)
    active_file = api_root / "counter_123.db"
    active_file.write_bytes(b"live counter")

    @contextmanager
    def exclusive_epoch(root: Path) -> Iterator[Path]:
        if root.exists():
            raise RuntimeError("Metrics epoch is active")
        yield root

    _install_lock_module(monkeypatch, exclusive_epoch)
    with pytest.raises(RuntimeError, match="Metrics epoch is active"):
        initialize_metrics_epoch(metrics_root)

    assert active_file.read_bytes() == b"live counter"
    assert not (metrics_root / "worker").exists()


def test_initialization_rejects_a_relative_root_before_locking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lock_called = False

    @contextmanager
    def exclusive_epoch(root: Path) -> Iterator[Path]:
        nonlocal lock_called
        lock_called = True
        yield root

    _install_lock_module(monkeypatch, exclusive_epoch)
    with pytest.raises(ValueError, match="absolute path"):
        initialize_metrics_epoch(Path("relative/metrics"))

    assert not lock_called
