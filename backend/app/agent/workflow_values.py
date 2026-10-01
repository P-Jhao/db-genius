"""Typed row evidence: SQL NULL, text identifiers and decimal values stay distinct."""

import json
import re
from decimal import Decimal, InvalidOperation

Row = dict[str, object]
ValueKey = tuple[str, str]
RowKey = tuple[tuple[str, ValueKey], ...]
ColumnTypes = dict[str, str]
_NUMERIC = re.compile(
    r"^(?:TINYINT|SMALLINT|MEDIUMINT|INT|INTEGER|BIGINT|DECIMAL|NUMERIC|NUMBER|"
    r"REAL|FLOAT|DOUBLE|DOUBLE PRECISION|MONEY)(?:\b|\()", re.IGNORECASE,
)
_TEXT = re.compile(r"^(?:CHAR|VARCHAR|TEXT|TINYTEXT|MEDIUMTEXT|LONGTEXT|NCHAR|NVARCHAR)\b", re.IGNORECASE)


def value_key(value: object, column_type: str | None = None) -> ValueKey:
    if value is None:
        return "null", ""
    if isinstance(value, bool):
        return "boolean", str(value)
    if (column_type is not None and _TEXT.match(column_type) and
            isinstance(value, (str, int, float, Decimal))):
        return "text", str(value)
    numeric_column = column_type is not None and _NUMERIC.match(column_type) is not None
    if isinstance(value, (int, float, Decimal)) or (numeric_column and isinstance(value, str)):
        try:
            number = Decimal(str(value))
        except InvalidOperation:
            return "text", str(value)
        if not number.is_finite():
            raise ValueError("Workflow evidence contains a non-finite number")
        return "number", "0" if number == 0 else format(number.normalize(), "f")
    if isinstance(value, str):
        return "text", value
    return type(value).__name__, json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)


def key(row: Row, column_types: ColumnTypes | None = None) -> RowKey:
    types = {} if column_types is None else column_types
    return tuple(sorted((name, value_key(value, types.get(name)))
                        for name, value in row.items()))


def covers(expected: list[Row], actual: list[Row], column_types: ColumnTypes | None = None) -> bool:
    remaining = actual.copy()
    for row in expected:
        match = next((index for index, candidate in enumerate(remaining)
                      if all(name in candidate and key({name: candidate[name]}, column_types) ==
                             key({name: value}, column_types) for name, value in row.items())), None)
        if match is None:
            return False
        remaining.pop(match)
    return True
