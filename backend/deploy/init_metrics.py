"""Start a fresh Prometheus multiprocess epoch when no app process is active."""

from __future__ import annotations

import os
import re
from pathlib import Path

METRICS_ROOT_ENV = "SQLCHAT_METRICS_MULTIPROCESS_ROOT"
SERVICE_DIRECTORIES = ("api", "worker")
METRIC_DATABASE_NAME = re.compile(r"(?:counter|histogram)_[0-9]+\.db\Z", re.ASCII)


def initialize_metrics_epoch(metrics_root: Path) -> dict[str, int]:
    """Remove only prior counter/histogram files while holding the exclusive lifecycle lock."""
    if not metrics_root.is_absolute():
        raise ValueError("SQLCHAT_METRICS_MULTIPROCESS_ROOT must be an absolute path")

    from app.core.observability_metrics_lock import exclusive_epoch

    removed_by_service: dict[str, int] = {}
    with exclusive_epoch(metrics_root) as locked_root:
        root = Path(locked_root).resolve(strict=True)
        configured_root = metrics_root.resolve(strict=True)
        if root != configured_root:
            raise RuntimeError("Metrics epoch lock resolved a different root")
        if not root.is_dir():
            raise RuntimeError("Metrics multiprocess root must be a directory")

        for service_name in SERVICE_DIRECTORIES:
            service_root = root / service_name
            if service_root.is_symlink():
                raise RuntimeError(f"Metrics service directory must not be a symlink: {service_name}")
            service_root.mkdir(exist_ok=True)
            if not service_root.is_dir():
                raise RuntimeError(f"Metrics service path must be a directory: {service_name}")

            removed = 0
            for entry in service_root.iterdir():
                if not METRIC_DATABASE_NAME.fullmatch(entry.name):
                    continue
                if entry.is_symlink():
                    raise RuntimeError(f"Metrics database file must not be a symlink: {entry.name}")
                if not entry.is_file():
                    raise RuntimeError(f"Metrics database path must be a file: {entry.name}")
                entry.unlink()
                removed += 1
            removed_by_service[service_name] = removed

    return removed_by_service


def main() -> None:
    configured_root = os.environ.get(METRICS_ROOT_ENV)
    if configured_root is None or not configured_root.strip():
        raise RuntimeError(f"Required environment variable {METRICS_ROOT_ENV} is missing")
    metrics_root = Path(configured_root)
    if not metrics_root.is_absolute():
        raise ValueError(f"{METRICS_ROOT_ENV} must be an absolute path")

    removed = initialize_metrics_epoch(metrics_root)
    print(
        "Initialized Prometheus metrics epoch; "
        f"removed api={removed['api']} worker={removed['worker']} stale database files"
    )


if __name__ == "__main__":
    main()
