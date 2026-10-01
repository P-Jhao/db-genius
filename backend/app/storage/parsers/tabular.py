"""Spreadsheet and CSV parsing with an exact row count and bounded preview."""

import csv
import io
import math
from collections.abc import Iterable, Iterator, Sequence
from datetime import date, datetime, time
from decimal import Decimal

import openpyxl  # type: ignore[import-untyped]
import xlrd  # type: ignore[import-untyped]

from app.storage.parsers.zip_guard import inspect_zip

MAX_ROWS = 200
MAX_COLUMNS = 2_000
def _value(value: object) -> str | int | float | bool | None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Spreadsheet contains a non-finite number")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (date, datetime, time, Decimal)):
        return str(value)
    return str(value)


def _headers(values: Sequence[object]) -> list[str]:
    if len(values) > MAX_COLUMNS:
        raise ValueError("Spreadsheet exceeds column limit")
    names: list[str] = []
    seen: set[str] = set()
    for index, value in enumerate(values):
        base = str(value).strip() if value is not None else ""
        base = base or f"column_{index}"
        name = base
        suffix = 2
        while name in seen:
            name = f"{base}_{suffix}"
            suffix += 1
        names.append(name)
        seen.add(name)
    return names


def _parse_rows(rows: Iterable[Sequence[object]]) -> dict[str, object]:
    iterator = iter(rows)
    try:
        first = next(iterator)
    except StopIteration as error:
        raise ValueError("Tabular file is empty") from error
    headers = _headers(first)
    if not headers:
        raise ValueError("Tabular file has no header")
    preview: list[dict[str, object]] = []
    total = 0
    for cells in iterator:
        if len(cells) > MAX_COLUMNS:
            raise ValueError("Spreadsheet exceeds column limit")
        if len(cells) > len(headers) and any(value is not None and value != "" for value in cells[len(headers):]):
            raise ValueError("Data row contains values beyond the header")
        if not any(value is not None and value != "" for value in cells):
            continue
        total += 1
        if total <= MAX_ROWS:
            preview.append({header: _value(cells[index]) if index < len(cells) else None
                            for index, header in enumerate(headers)})
    result: dict[str, object] = {"headers": headers, "totalRows": total, "data": preview,
                                 "truncated": total > MAX_ROWS}
    if total > MAX_ROWS:
        result["message"] = f"Only first {MAX_ROWS} rows returned. Total: {total}"
    return result


def parse_csv(data: bytes) -> dict[str, object]:
    text = data.decode("utf-8-sig")
    with io.StringIO(text, newline="") as stream:
        return _parse_rows(list(row) for row in csv.reader(stream, strict=True))


def parse_xlsx(data: bytes) -> dict[str, object]:
    inspect_zip(data)
    workbook = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        if not workbook.worksheets:
            raise ValueError("Spreadsheet has no sheet")
        sheet = workbook.worksheets[0]
        return _parse_rows(sheet.iter_rows(values_only=True))
    finally:
        workbook.close()


def _xls_rows(sheet: xlrd.sheet.Sheet) -> Iterator[list[object]]:
    for row_index in range(sheet.nrows):
        yield [sheet.cell_value(row_index, column) for column in range(sheet.ncols)]


def parse_xls(data: bytes) -> dict[str, object]:
    workbook = xlrd.open_workbook(file_contents=data, on_demand=True)
    try:
        if workbook.nsheets == 0:
            raise ValueError("Spreadsheet has no sheet")
        return _parse_rows(_xls_rows(workbook.sheet_by_index(0)))
    finally:
        workbook.release_resources()
