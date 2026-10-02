"""Merge fixed service directories across independent container PID namespaces."""

import os
import re
from collections.abc import Iterable
from pathlib import Path
from threading import Lock
from typing import cast

from prometheus_client import values
from prometheus_client.metrics_core import Metric
from prometheus_client.multiprocess import MultiProcessCollector

from app.core.config import Settings
from app.core.observability_metrics_lock import MetricsLease, acquire_shared

_SERVICES = ("api", "worker")
_FILE = re.compile(r"(?:counter|histogram)_[0-9]+\.db")
_guard = Lock()
_lease: MetricsLease | None = None


class ServiceMetricsCollector:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve(strict=True)

    def collect(self) -> Iterable[Metric]:
        files: list[str] = []
        for name in _SERVICES:
            folder = self.root / name
            if not folder.is_dir() or folder.is_symlink():
                raise ValueError("Metric service directory must be initialized without a symlink")
            for file in folder.glob("*.db"):
                if not _FILE.fullmatch(file.name) or file.is_symlink():
                    raise ValueError("Unsupported metric file")
                files.append(str(file))
        # This locked client exposes merge as a public static method without
        # annotations. One merged stream avoids duplicate Metric families.
        return cast(Iterable[Metric], MultiProcessCollector.merge(files))  # type: ignore[no-untyped-call]


def start_metrics(settings: Settings, *, service: str) -> None:
    global _lease
    root = settings.metrics_multiprocess_root
    directory = os.environ.get("PROMETHEUS_MULTIPROC_DIR")
    if not root:
        if directory:
            raise ValueError("Shared metric root must be configured with multiprocess mode")
        return
    if service not in _SERVICES:
        raise ValueError("Unknown metric service")
    expected = Path(root).resolve(strict=True) / service
    if not directory or Path(directory).resolve(strict=True) != expected:
        raise ValueError("Metric writer directory must match the fixed service directory")
    if not getattr(values.ValueClass, "_multiprocess", False):
        raise RuntimeError("PROMETHEUS_MULTIPROC_DIR must be set before importing the metrics client")
    with _guard:
        if _lease is None:
            _lease = acquire_shared(Path(root))


def close_metrics() -> None:
    global _lease
    with _guard:
        if _lease is not None:
            _lease.close()
            _lease = None
