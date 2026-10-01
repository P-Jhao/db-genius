"""Column-aware, ordering-aware judgement of actual SQL tool output."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import cast

from real_model_cases import Cell, QueryOracle


def cell_equal(actual: object, expected: Cell) -> bool:
    if expected is None:
        return actual is None
    if isinstance(expected, (Decimal, int)) and not isinstance(expected, bool):
        if isinstance(actual, bool) or not isinstance(actual, (Decimal, int, float, str)):
            return False
        try:
            number = Decimal(str(actual))
        except InvalidOperation:
            return False
        return number.is_finite() and abs(number - Decimal(expected)) <= Decimal("0.000000001")
    return isinstance(actual, str) and actual == expected


def query_matches(oracle: QueryOracle, data: object) -> bool:
    if not isinstance(data, list) or len(data) != len(oracle.rows):
        return False
    expected_names = tuple(name.casefold() for name in oracle.columns)
    projected: list[tuple[object, ...]] = []
    for row in data:
        if not isinstance(row, dict) or not all(isinstance(key, str) for key in row):
            return False
        mapped = {key.casefold(): value for key, value in cast(dict[str, object], row).items()}
        if len(mapped) != len(row) or set(mapped) != set(expected_names):
            return False
        projected.append(tuple(mapped[name] for name in expected_names))

    def matches(actual: tuple[object, ...], expected: tuple[Cell, ...]) -> bool:
        return len(actual) == len(expected) and all(
            cell_equal(value, wanted) for value, wanted in zip(actual, expected, strict=True)
        )

    if oracle.ordered:
        return all(matches(row, wanted) for row, wanted in zip(projected, oracle.rows, strict=True))
    # Remove each matched occurrence; duplicates never collapse into a set.
    remaining = list(oracle.rows)
    for row in projected:
        index = next((i for i, wanted in enumerate(remaining) if matches(row, wanted)), None)
        if index is None:
            return False
        remaining.pop(index)
    return not remaining


def database_rows_match(oracle: QueryOracle, rows: list[tuple[object, ...]]) -> bool:
    data = [dict(zip(oracle.columns, row, strict=True)) for row in rows]
    return query_matches(oracle, data)
