from typing import Protocol

from app.core.config import Settings, get_settings


class StorageBackend(Protocol):
    def put(self, key: str, data: bytes, content_type: str | None) -> None: ...

    def read(self, key: str, max_bytes: int) -> bytes: ...

    def delete(self, key: str) -> None: ...


class StorageLimitExceeded(ValueError):
    """Stored content exceeded the caller's byte limit."""


def get_storage(settings: Settings | None = None) -> StorageBackend:
    config = settings if settings is not None else get_settings()
    if config.storage_backend == "local":
        from app.storage.local import LocalStorage

        return LocalStorage(config.storage_root)
    if config.storage_backend == "oss":
        from app.storage.oss import OssStorage

        return OssStorage(config)
    raise ValueError(f"Unsupported storage backend: {config.storage_backend}")
