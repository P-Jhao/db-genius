from datetime import datetime

from app.models import UploadedFile
from app.schemas.base import ApiModel


class UploadedFileVO(ApiModel):
    id: int
    original_name: str
    file_size: int | None
    content_type: str | None
    created_at: datetime

    @classmethod
    def from_entity(cls, file: UploadedFile) -> "UploadedFileVO":
        return cls.model_validate(file)
