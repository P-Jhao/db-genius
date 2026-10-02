"""Linux process leases; close inherited descriptors without unlocking live forks."""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from importlib import import_module
from pathlib import Path
from typing import Protocol, cast


class FlockModule(Protocol):
    LOCK_EX: int
    LOCK_SH: int
    LOCK_NB: int

    def flock(self, descriptor: int, operation: int) -> None: ...


class MetricsLease:
    def __init__(self, descriptor: int) -> None:
        self._descriptor: int | None = descriptor

    def close(self) -> None:
        if self._descriptor is not None:
            os.close(self._descriptor)
            self._descriptor = None


def _acquire(root: Path, *, exclusive: bool) -> MetricsLease:
    if os.name != "posix":
        raise RuntimeError("Shared metric lifecycle locks require the Linux deployment runtime")
    fcntl = cast(FlockModule, import_module("fcntl"))

    resolved = root.resolve(strict=True)
    if not resolved.is_dir() or root.is_symlink():
        raise ValueError("Metric root must be an existing directory without a symlink")
    path = resolved / ".lifecycle.lock"
    if path.is_symlink():
        raise ValueError("Metric lifecycle lock cannot be a symlink")
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(descriptor, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
    except OSError as error:
        os.close(descriptor)
        raise RuntimeError("Metric epoch initialization conflicts with a live service") from error
    return MetricsLease(descriptor)


def acquire_shared(root: Path) -> MetricsLease:
    return _acquire(root, exclusive=False)


@contextmanager
def exclusive_epoch(root: Path) -> Iterator[Path]:
    """Only the deployment initializer may clear files while this lease is held."""
    lease = _acquire(root, exclusive=True)
    try:
        yield root.resolve(strict=True)
    finally:
        lease.close()
