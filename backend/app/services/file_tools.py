"""Agent file tools: only IDs can be supplied by the model."""

from pathlib import PurePath

from app.core.config import get_settings
from app.storage.ocr import recognize
from app.storage.parsers import PARSERS
from app.storage.validation import validate_content

MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_OCR_CHARS = 30_000
IMAGE_EXTENSIONS = frozenset({"png", "jpg", "jpeg", "webp", "bmp"})


def _extension(name: str) -> str:
    return PurePath(name).suffix.lower().removeprefix(".")


def read_file(user_id: int, file_id: int) -> dict[str, object]:
    from app.services.file_upload import read_owned_bytes

    uploaded, data = read_owned_bytes(user_id, file_id, max_bytes=MAX_FILE_BYTES)
    extension = _extension(uploaded.original_name)
    parser = PARSERS.get(extension)
    if parser is None:
        raise ValueError(f"Unsupported document format: {extension or 'none'}")
    if not data:
        raise ValueError("Document is empty")
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("Document exceeds 20 MiB limit")
    try:
        content = parser(data)
    except Exception as error:
        raise ValueError(f"Failed to parse {extension} document") from error
    return {"success": True, "fileName": uploaded.original_name, "format": extension, **content}


def read_image(user_id: int, file_id: int) -> dict[str, object]:
    from app.services.file_upload import read_owned_bytes

    uploaded, data = read_owned_bytes(user_id, file_id, max_bytes=MAX_IMAGE_BYTES)
    extension = _extension(uploaded.original_name)
    if extension not in IMAGE_EXTENSIONS:
        raise ValueError(f"Unsupported image format: {extension or 'none'}")
    if not data:
        raise ValueError("Image is empty")
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("Image exceeds 10 MiB limit")
    validate_content(extension, data)
    if not get_settings().ocr_enabled:
        raise RuntimeError("OCR is disabled")
    text = recognize(data)
    return {"success": True, "fileName": uploaded.original_name, "text": text[:MAX_OCR_CHARS],
            "truncated": len(text) > MAX_OCR_CHARS}
