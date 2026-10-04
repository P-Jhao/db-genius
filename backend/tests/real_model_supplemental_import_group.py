"""Use existing owned fixtures and strict affected case; add file-import-only evidence."""

from __future__ import annotations

import csv
import hashlib
import io
from contextlib import ExitStack

from real_model_affected_effects import affected_case
from real_model_api import api_session
from real_model_cases import CSV, EffectCase
from real_model_database import DatabaseType, isolated_database
from real_model_import_structure import capture_structure, structure_evidence
from real_model_oracles import database_rows_match, query_matches
from real_model_relay import RealProviderRelay, object_value
from real_model_synthetic_evidence import scrub
from sqlglot import exp, parse_one


def _selects(turn: dict[str, object], database: object) -> list[dict[str, object]]:
    raw = turn.get("syntheticExecutedSql")
    if not isinstance(raw, list):
        return []
    results: list[dict[str, object]] = []
    for item in raw:
        call = object_value(item)
        arguments, result = call.get("arguments"), call.get("result")
        if call.get("name") != "executeSql" or not isinstance(arguments, dict) or not isinstance(result, dict):
            continue
        statement = arguments.get("statement")
        if not isinstance(statement, str) or result.get("success") is not True or "data" not in result:
            continue
        try:
            query = parse_one(statement, read="postgres" if database == "postgresql" else "mysql")
            order = query.args.get("order")
            ordered = order.expressions if isinstance(order, exp.Order) else []
            selects_import = isinstance(query, exp.Select) and any(
                table.name.casefold() == "imported_contacts" for table in query.find_all(exp.Table))
            orders_id = bool(ordered) and isinstance(ordered[0], exp.Ordered) and (
                isinstance(ordered[0].this, exp.Column) and ordered[0].this.name.casefold() == "id"
                and ordered[0].args.get("desc") is not True)
            results.append({"statement": statement, "data": result["data"],
                            "selectsImportedContacts": selects_import, "ordersByIdAscending": orders_id})
        except Exception as error:  # noqa: BLE001 - actual malformed SQL arguments never count as SELECT proof
            results.append({"statement": statement, "parseErrorType": type(error).__name__})
    return results


def file_content_evidence(case: EffectCase, row: dict[str, object], before_rows: list[tuple[object, ...]],
                          after_rows: list[tuple[object, ...]]) -> dict[str, object]:
    source = CSV.decode("utf-8")
    parsed = list(csv.reader(io.StringIO(source, newline=""), strict=True))
    oracle = case.oracles[0][0]
    if parsed[0] != list(oracle.columns) or len(parsed) - 1 != len(oracle.rows):
        raise ValueError("Fixed source and oracle no longer match")
    expected = [dict(zip(parsed[0], cells, strict=True)) for cells in parsed[1:]]
    if not query_matches(oracle, expected):
        raise ValueError("Fixed source does not match the unchanged oracle")
    turns = row.get("turns")
    observations: list[object] = []
    observed_turn: dict[str, object] = {}
    if isinstance(turns, list) and len(turns) == 1:
        observed_turn = object_value(turns[0])
        raw = observed_turn.get("syntheticToolResults")
        if isinstance(raw, list):
            observations = raw
    read_results: list[dict[str, object]] = []
    select_results: list[dict[str, object]] = []
    for raw in observations:
        observation = object_value(raw)
        result = observation.get("result")
        if not isinstance(result, dict) or result.get("success") is not True:
            continue
        if observation.get("name") == "readFile":
            read_results.append({key: result[key] for key in ("format", "headers", "totalRows", "data", "truncated")
                                 if key in result})
        if observation.get("name") == "executeSql" and "data" in result:
            select_results.append({"data": result["data"]})
    source_matches = bool(read_results) and all(
        result.get("format") == "csv" and result.get("headers") == parsed[0]
        and type(result.get("totalRows")) is int and result["totalRows"] == len(expected)
        and result.get("truncated") is False and result.get("data") == expected for result in read_results)
    select_calls = _selects(observed_turn, row.get("database"))
    checks = {"importStartedEmpty": not before_rows, "readFileParsedRowsMatchSource": source_matches,
              "readFileRowsMatchOracle": bool(read_results) and all(
                  query_matches(oracle, result.get("data")) for result in read_results),
              "importActualSelectMatchesOracle": any(query_matches(oracle, value["data"]) for value in select_results),
              "importSelectArgumentsAndResult": any(
                  value.get("selectsImportedContacts") is True and value.get("ordersByIdAscending") is True
                  and query_matches(oracle, value.get("data")) for value in select_calls),
              "importIndependentSelectMatchesOracle": database_rows_match(oracle, after_rows)}
    return {"sourceCsvSha256": hashlib.sha256(CSV).hexdigest(), "sourceLines": source.splitlines(),
            "sourceParsedRows": parsed, "actualReadFile": read_results, "actualSelectResults": select_results,
            "actualSelectCalls": select_calls,
            "independentBeforeRows": [list(value) for value in before_rows],
            "independentAfterRows": [list(value) for value in after_rows], "checks": checks,
            "status": "passed" if all(checks.values()) else "failed"}


def _attach(row: dict[str, object], key: str, evidence: dict[str, object]) -> None:
    row[key] = evidence
    checks = object_value(evidence["checks"])
    turns = row.get("turns")
    if isinstance(turns, list):
        for raw in turns:
            turn = object_value(raw)
            original = object_value(turn.get("checks", {}))
            original.update(checks)
            turn["checks"] = original
            if evidence["status"] != "passed":
                turn["status"] = "failed"
                turn[f"{key}ErrorType"] = "SupplementalEvidenceFailed"
    if evidence["status"] != "passed":
        row.update({"status": "failed", f"{key}ErrorType": "SupplementalEvidenceFailed"})
        if row.get("errorType") is None:
            row["errorType"] = f"{key}SupplementalEvidenceFailed"


def import_group(case: EffectCase, repetition: int, database: DatabaseType,
                 relay: RealProviderRelay, scope: str) -> list[dict[str, object]]:
    if case.code != "file_import" or not case.uses_file or case.uses_compare or len(case.questions) != 1:
        raise ValueError("Structure group only accepts the unchanged one-turn file-import case")
    if database not in {"postgresql", "mysql"} or repetition not in {1, 2, 3}:
        raise ValueError("Unexpected supplemental fixture matrix")
    cleanup: dict[str, dict[str, object]] = {"target": {}, "comparison": {}, "api": {}}
    row: dict[str, object] = {"case": case.code, "database": database, "repetition": repetition,
                              "variant": "python", "scope": scope, "status": "failed", "turns": []}
    stage, same_snapshots = "provision", False
    before: dict[str, object] | None = None
    after: dict[str, object] | None = None
    secrets: tuple[str, ...] = ()
    try:
        with ExitStack() as fixtures:
            target = fixtures.enter_context(isolated_database(database, "py", cleanup_evidence=cleanup["target"]))
            same_snapshots = len({target.fingerprint()}) == 1  # Single variant, never paired evidence.
            secrets = (relay.upstream_key.get_secret_value(), relay.access_key.get_secret_value(),
                       target.password.get_secret_value())
            stage = "pre-import-structure"
            before = capture_structure(target)
            row["importStructureBefore"] = before
            if before["status"] != "observed":
                raise RuntimeError("Cannot execute import without supported structure observation")
            statement = case.oracles[0][0].statement
            before_rows = target.rows(statement)
            if before_rows:
                raise ValueError("Owned import target is not empty before import")
            session = fixtures.enter_context(api_session("python", relay, cleanup_evidence=cleanup["api"]))
            secrets += (session.token.get_secret_value(),)
            stage = "execute"
            try:
                row = affected_case(case, repetition, session, target, relay, scope, None)
            finally:
                after = capture_structure(target)  # Fresh Inspector, before any owned fixture cleanup.
                _attach(row, "importStructure", structure_evidence(before, after))
            stage = "post-import-content"
            _attach(row, "importContent", file_content_evidence(case, row, before_rows, target.rows(statement)))
            stage = "cleanup"
    except Exception as error:  # noqa: BLE001 - ExitStack still runs exact existing owned cleanup
        row.update({"status": "failed", "errorType": type(error).__name__, "groupErrorStage": stage})
    if before is not None:
        row.setdefault("importStructureBefore", before)
    if after is not None:
        row.setdefault("importStructureAfter", after)
    row.update({"cleanup": cleanup, "sameSnapshots": same_snapshots, "attachmentScope": "python-local-csv-only"})
    if any(cleanup[key].get("status") != "passed" for key in ("target", "api")):
        row.update({"status": "failed", "cleanupIncomplete": True})
    return [object_value(scrub(row, secrets))]
