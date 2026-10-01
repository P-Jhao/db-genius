import oss2  # type: ignore[import-untyped]

from app.core.config import Settings
from app.storage.backend import StorageLimitExceeded


class OssStorage:
    def __init__(self, settings: Settings) -> None:
        if not all((settings.oss_endpoint, settings.oss_bucket,
                    settings.oss_access_key_id, settings.oss_access_key_secret)):
            raise ValueError("OSS storage is not configured")
        auth = oss2.Auth(settings.oss_access_key_id, settings.oss_access_key_secret)
        self.bucket = oss2.Bucket(auth, settings.oss_endpoint, settings.oss_bucket)

    def put(self, key: str, data: bytes, content_type: str | None) -> None:
        headers = {"Content-Type": content_type} if content_type else None
        self.bucket.put_object(key, data, headers=headers)

    def read(self, key: str, max_bytes: int) -> bytes:
        result = self.bucket.get_object(key)
        try:
            data: bytes = result.read(max_bytes + 1)
        finally:
            result.close()
        if len(data) > max_bytes:
            raise StorageLimitExceeded("Stored file exceeds read limit")
        return data

    def delete(self, key: str) -> None:
        self.bucket.delete_object(key)
