from io import BytesIO
from zipfile import BadZipFile, ZipFile

from app.storage.parsers.zip_guard import inspect_zip

DOC_EXTENSIONS = frozenset({"xlsx", "xls", "csv", "docx", "pdf", "md"})
IMAGE_EXTENSIONS = frozenset({"png", "jpg", "jpeg", "webp", "bmp"})
MAX_FILE_SIZE = 20 * 1024 * 1024


def validate_content(extension: str, data: bytes) -> None:
    """Reject obviously damaged uploads before saving them to storage."""
    if extension in {"csv", "md"}:
        try:
            decoded = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("Text file must be UTF-8") from exc
        if "\x00" in decoded:
            raise ValueError("Text file contains NUL bytes")
    elif extension in {"xlsx", "docx"}:
        required = "xl/workbook.xml" if extension == "xlsx" else "word/document.xml"
        try:
            inspect_zip(data)
            with ZipFile(BytesIO(data)) as archive:
                if required not in archive.namelist() or archive.testzip() is not None:
                    raise ValueError("Office document is damaged")
        except BadZipFile as exc:
            raise ValueError("Office document is damaged") from exc
    elif extension == "xls":
        if not data.startswith(bytes.fromhex("D0CF11E0A1B11AE1")):
            raise ValueError("Excel file is damaged")
    elif extension == "pdf":
        if not data.startswith(b"%PDF-") or b"%%EOF" not in data[-1024:]:
            raise ValueError("PDF file is damaged")
    elif extension == "png":
        if not data.startswith(b"\x89PNG\r\n\x1a\n") or b"IEND" not in data[-32:]:
            raise ValueError("PNG file is damaged")
    elif extension in {"jpg", "jpeg"}:
        if not data.startswith(b"\xff\xd8") or not data.endswith(b"\xff\xd9"):
            raise ValueError("JPEG file is damaged")
    elif extension == "webp":
        if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
            raise ValueError("WebP file is damaged")
    elif extension == "bmp":
        if len(data) < 14 or data[:2] != b"BM" or int.from_bytes(data[2:6], "little") != len(data):
            raise ValueError("BMP file is damaged")
    else:
        raise ValueError("Unsupported file extension")
