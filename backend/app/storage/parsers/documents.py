"""Text document extraction matching the original tool's visible bounds."""

import io

from docx import Document
from docx.table import Table
from pypdf import PdfReader

from app.storage.parsers.zip_guard import inspect_zip

MAX_TEXT_CHARS = 30_000
MAX_PDF_PAGES = 50


def _text_result(text: str) -> dict[str, object]:
    result: dict[str, object] = {"content": text[:MAX_TEXT_CHARS], "totalChars": len(text),
                                 "truncated": len(text) > MAX_TEXT_CHARS}
    if len(text) > MAX_TEXT_CHARS:
        result["message"] = f"Only first {MAX_TEXT_CHARS} chars returned. Total: {len(text)}"
    return result


def parse_markdown(data: bytes) -> dict[str, object]:
    return _text_result(data.decode("utf-8-sig"))


def parse_docx(data: bytes) -> dict[str, object]:
    inspect_zip(data)
    document = Document(io.BytesIO(data))
    lines: list[str] = []
    for block in document.iter_inner_content():
        if isinstance(block, Table):
            lines.extend("\t".join(cell.text for cell in row.cells) for row in block.rows)
        else:
            lines.append(block.text)
    text = "\n".join(lines)
    return _text_result(text)


def parse_pdf(data: bytes) -> dict[str, object]:
    reader = PdfReader(io.BytesIO(data), strict=True)
    if reader.is_encrypted:
        raise ValueError("Encrypted PDF is unsupported")
    pages = len(reader.pages)
    if pages == 0:
        raise ValueError("PDF contains no pages")
    text = "\n".join(reader.pages[index].extract_text() or "" for index in range(min(pages, MAX_PDF_PAGES)))
    result = _text_result(text)
    result["totalPages"] = pages
    if pages > MAX_PDF_PAGES:
        result["truncated"] = True
        result["message"] = f"Only first {MAX_PDF_PAGES} pages extracted. Total pages: {pages}"
    if not text.strip():
        result["message"] = "No text extracted from PDF; scanned pages may require image OCR"
    return result
