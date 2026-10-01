"""Reject compressed document payloads that expand beyond parser limits."""

import io
import zipfile

MAX_UNCOMPRESSED_BYTES = 100 * 1024 * 1024
MAX_ZIP_ENTRIES = 10_000
MAX_RATIO = 1_000


def inspect_zip(data: bytes) -> None:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        if len(entries) > MAX_ZIP_ENTRIES:
            raise ValueError("Document archive has too many entries")
        total = 0
        for entry in entries:
            total += entry.file_size
            if total > MAX_UNCOMPRESSED_BYTES:
                raise ValueError("Document expands beyond size limit")
            if entry.file_size > MAX_RATIO * max(entry.compress_size, 1):
                raise ValueError("Document compression ratio exceeds limit")
            if entry.flag_bits & 1:
                raise ValueError("Encrypted document is unsupported")
