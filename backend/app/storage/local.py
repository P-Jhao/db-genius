from pathlib import Path, PurePosixPath

from app.storage.backend import StorageLimitExceeded


class LocalStorage:
    def __init__(self, root: str) -> None:
        if not root.strip():
            raise ValueError("Local storage root is not configured")
        self.root = Path(root).resolve()

    def _path(self, key: str) -> Path:
        parts = PurePosixPath(key).parts
        if (not parts or key.startswith(("/", "\\")) or "\\" in key
                or any(part in ("", ".", "..") for part in parts)):
            raise ValueError("Invalid storage key")
        if len(parts) != 3 or parts[0] != "uploads" or not parts[1].isdecimal():
            raise ValueError("Storage key must identify a user's upload")
        path = self.root.joinpath(*parts).resolve()
        expected_user_root = self.root.joinpath(*parts[:2])
        user_root = expected_user_root.resolve()
        if user_root != expected_user_root or not path.is_relative_to(user_root):
            raise ValueError("Storage key escapes local root")
        return path

    def put(self, key: str, data: bytes, content_type: str | None) -> None:
        del content_type
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(data)

    def read(self, key: str, max_bytes: int) -> bytes:
        path = self._path(key)
        with path.open("rb") as stream:
            data = stream.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise StorageLimitExceeded("Stored file exceeds read limit")
        return data

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)
