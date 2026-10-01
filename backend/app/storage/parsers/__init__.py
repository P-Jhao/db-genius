"""Bounded parsers for user-owned uploaded documents."""

from app.storage.parsers.documents import parse_docx, parse_markdown, parse_pdf
from app.storage.parsers.tabular import parse_csv, parse_xls, parse_xlsx

PARSERS = {
    "xlsx": parse_xlsx,
    "xls": parse_xls,
    "csv": parse_csv,
    "docx": parse_docx,
    "pdf": parse_pdf,
    "md": parse_markdown,
}
