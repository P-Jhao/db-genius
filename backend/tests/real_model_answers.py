"""Strict grounded final answers, with explicit review gates for free-form prose."""

from __future__ import annotations

import json
import math
import re
from decimal import Decimal

from real_model_cases import EffectCase, QueryOracle
from real_model_oracles import query_matches


def _json_results(answer: str, oracles: tuple[QueryOracle, ...]) -> list[object] | None:
    fenced = re.fullmatch(r"```(?:json)?\s*\n(.*?)\n```", answer, re.DOTALL)
    text = fenced[1] if fenced is not None else answer
    try:
        value: object = json.loads(text)
    except ValueError:
        return None
    if isinstance(value, dict) and set(value) == {"results"}:
        raw = value["results"]
        if not isinstance(raw, list):
            return []
        results: list[object] = []
        for index, result in enumerate(raw):
            if isinstance(result, dict) and set(result) == {"data"}:
                results.append(result["data"])
            elif isinstance(result, dict) and set(result) == {"columns", "rows"}:
                columns, rows = result["columns"], result["rows"]
                if (index >= len(oracles) or not isinstance(columns, list) or not isinstance(rows, list)
                        or not all(isinstance(name, str) for name in columns)):
                    return []
                if len({str(name).casefold() for name in columns}) != len(columns):
                    return []
                if any(not isinstance(row, list) or len(row) != len(columns) for row in rows):
                    return []
                results.append([dict(zip(columns, row, strict=True)) for row in rows])
            else:
                results.append(result)
        return results
    if len(oracles) == 1:
        rows = value if isinstance(value, list) else [value]
        known_names = {name.casefold() for name in oracles[0].columns}
        if not all(isinstance(row, dict) and any(str(key).casefold() in known_names for key in row) for row in rows):
            return None
        return [rows]
    return None


def _markdown_results(answer: str) -> list[object] | None:
    blocks = re.split(r"\n\s*\n", answer)
    results: list[object] = []
    for block in blocks:
        lines = block.strip().splitlines()
        if len(lines) < 2 or any(not line.strip().startswith("|") or not line.strip().endswith("|") for line in lines):
            return None
        header = [cell.strip().strip("`") for cell in lines[0].strip()[1:-1].split("|")]
        separator = [cell.strip() for cell in lines[1].strip()[1:-1].split("|")]
        if len(header) != len(separator) or any(re.fullmatch(r":?-{3,}:?", cell) is None for cell in separator):
            return None
        if len({name.casefold() for name in header}) != len(header):
            return []
        rows: list[dict[str, object]] = []
        for line in lines[2:]:
            cells = [cell.strip().strip("`") for cell in line.strip()[1:-1].split("|")]
            if len(cells) != len(header):
                return []
            rows.append(dict(zip(header, [None if cell == "NULL" else cell for cell in cells], strict=True)))
        results.append(rows)
    return results


def _expected(oracle: QueryOracle) -> list[dict[str, object]]:
    return [dict(zip(oracle.columns, [str(cell) if isinstance(cell, Decimal) else cell for cell in row], strict=True))
            for row in oracle.rows]


def observed_results(oracles: tuple[QueryOracle, ...], data: object) -> dict[str, object]:
    """Keep only fixed synthetic column names, numeric values and known entities."""
    if not isinstance(data, list):
        return {"data": None, "rowCount": None, "errorType": "UnexpectedResultShape"}
    columns = {name.casefold() for oracle in oracles for name in oracle.columns}
    entities = {cell for oracle in oracles for row in oracle.rows for cell in row if isinstance(cell, str)}
    rows: list[dict[str, object]] = []
    unexpected = 0
    for row in data[:32]:
        if not isinstance(row, dict):
            return {"data": None, "rowCount": len(data), "errorType": "UnexpectedRowShape"}
        projected: dict[str, object] = {}
        for name, cell in row.items():
            if not isinstance(name, str) or name.casefold() not in columns:
                unexpected += 1
                continue
            if isinstance(cell, float) and not math.isfinite(cell):
                projected[name.casefold()] = {"invalidNumber": True}
            elif (cell is None or isinstance(cell, (int, float, bool)) or
                    isinstance(cell, str) and (cell in entities or re.fullmatch(r"[-+]?\d+(?:\.\d+)?", cell))):
                projected[name.casefold()] = cell
            else:
                projected[name.casefold()] = {"unexpectedTextOrType": True}
        rows.append(projected)
    return {"data": rows, "rowCount": len(data), "truncated": len(data) > 32,
            "unexpectedColumnCount": unexpected}


def answer_review(case: EffectCase, turn: int, answer: str) -> dict[str, object]:
    oracles = case.oracles[turn]
    if not oracles:
        return {"status": "review-required", "expectedResults": [], "finalAnswer": answer,
                "answerTruncated": len(answer) > 8192, "parsedResults": None}
    parsed = _json_results(answer.strip(), oracles) if len(answer) <= 8192 else None
    if parsed is None and len(answer) <= 8192:
        parsed = _markdown_results(answer.strip())
    if parsed is None:
        status = "review-required"
    else:
        status = "validated" if len(parsed) == len(oracles) and all(
            query_matches(oracle, data) for oracle, data in zip(oracles, parsed, strict=True)) else "failed"
    return {"status": status, "expectedResults": [_expected(oracle) for oracle in oracles],
            "parsedResults": parsed, "finalAnswer": answer, "answerTruncated": len(answer) > 8192}


def redact_answer(review: dict[str, object], secrets: tuple[str, ...], questions: tuple[str, ...]) -> None:
    answer = review.get("finalAnswer")
    if not isinstance(answer, str):
        raise TypeError("Expected a synthetic final answer for review")
    if re.search(r"<think|reasoning_content|[｜|]DSML[｜|]", answer, re.IGNORECASE):
        review["finalAnswer"] = None
        review["status"] = "review-required"
        review["reasoningOmitted"] = True
        review["parsedResults"] = None
        return
    for value in secrets + questions:
        if value:
            answer = answer.replace(value, "[omitted]")
    review["finalAnswer"] = answer[:8192]

    def scrub(value: object) -> object:
        if isinstance(value, str):
            for secret in secrets + questions:
                if secret:
                    value = value.replace(secret, "[omitted]")
            return value
        if isinstance(value, list):
            return [scrub(item) for item in value]
        if isinstance(value, float) and not math.isfinite(value):
            return {"invalidNumber": True}
        if isinstance(value, dict):
            return {str(scrub(key)): scrub(item) for key, item in value.items()}
        return value

    review["parsedResults"] = scrub(review.get("parsedResults"))
    review["executedResults"] = scrub(review.get("executedResults"))
