"""Opt-in subset of unchanged fixed cases; defaults to Java/Python paired effects."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import ExitStack

from real_model_api import ApiSession, Variant, api_session
from real_model_cases import EffectCase, fixed_cases
from real_model_database import DatabaseType, TargetSnapshot, isolated_database
from real_model_evidence import tool_results
from real_model_regression_support import options, report_run
from real_model_relay import RealProviderRelay, object_value
from real_model_report import pair_comparison
from real_model_runner import run_case
from real_model_synthetic_evidence import executed_sql, scrub, turn_evidence

AFFECTED_CODES = {"aggregate", "join", "null", "date", "repair", "compare"}


class CapturedSession(ApiSession):
    def __init__(self, session: ApiSession) -> None:
        super().__init__(session.variant, session.username, session.client, session.token)
        self.turn_events: list[list[dict[str, object]]] = []

    def chat(self, body: dict[str, object]) -> tuple[list[dict[str, object]], dict[str, object]]:
        self.event_capture = []
        try:
            return super().chat(body)
        finally:
            self.turn_events.append(self.event_capture)


def affected_case(case: EffectCase, repetition: int, session: ApiSession, target: TargetSnapshot,
                  relay: RealProviderRelay, scope: str,
                  comparison: TargetSnapshot | None) -> dict[str, object]:
    captured = CapturedSession(session)
    row = run_case(case, repetition, captured, target, relay, comparison)
    row["scope"] = scope
    secrets: tuple[str, ...] = (relay.upstream_key.get_secret_value(), relay.access_key.get_secret_value(),
                                session.token.get_secret_value(), target.password.get_secret_value())
    if comparison is not None:
        secrets += (comparison.password.get_secret_value(),)
    turns = row["turns"]
    if not isinstance(turns, list):
        raise TypeError("Expected affected-case turn evidence")
    for index, raw in enumerate(turns):
        turn = object_value(raw)
        try:
            events = captured.turn_events[index]
            evidence = turn_evidence(case, index, events, secrets)
            turn.update(evidence)
            sql = executed_sql(object_value(turn["provider"]), secrets)
            turn["syntheticExecutedSql"] = sql
            checks = object_value(turn.get("checks", {}))
            sse = object_value(evidence["sse"])
            checks.update({"interactionEnded": sse["ended"] is True, "usageExactlyOnce": sse["usageCount"] == 1,
                           "noAbortedOrError": sse["abortedCount"] == sse["errorCount"] == 0})
            checks["sqlArgumentsObserved"] = len(sql) >= len([tool for tool in tool_results(events)
                                                            if tool.name == "executeSql"])
            turn["checks"] = checks
            review = object_value(evidence["answerReview"])
            if turn["status"] == "failed" or not all(checks.values()) or review["status"] == "failed":
                turn["status"] = "failed"
            else:
                turn["status"] = "review-required" if review["status"] == "review-required" else "passed"
        except Exception as error:  # noqa: BLE001 - retain earlier evidence without private diagnostics
            turn.update({"status": "failed", "evidenceErrorType": type(error).__name__})
    if row["status"] == "failed" or len(turns) != len(case.questions) or any(
            object_value(turn)["status"] == "failed" for turn in turns):
        row["status"] = "failed"
    else:
        row["status"] = "review-required" if any(object_value(turn)["status"] == "review-required"
                                                 for turn in turns) else "passed"
    return object_value(scrub(row, secrets))


def _group(case: EffectCase, repetition: int, database: DatabaseType, variants: tuple[Variant, ...],
           relay: RealProviderRelay, scope: str) -> list[dict[str, object]]:
    cleanup: dict[Variant, dict[str, dict[str, object]]] = {
        variant: {"target": {}, "comparison": {}, "api": {}} for variant in variants}
    current: dict[Variant, dict[str, object]] = {}
    same_snapshots = False
    stage = "provision"
    try:
        with ExitStack() as fixtures:
            targets = {variant: fixtures.enter_context(isolated_database(
                database, "py" if variant == "python" else "java",
                cleanup_evidence=cleanup[variant]["target"])) for variant in variants}
            comparisons = {variant: fixtures.enter_context(isolated_database(
                database, "test", comparison_target=True, cleanup_evidence=cleanup[variant]["comparison"]))
                for variant in variants} if case.uses_compare else {}
            fingerprints = {target.fingerprint() for target in targets.values()}
            comparison_fingerprints = {target.fingerprint() for target in comparisons.values()}
            same_snapshots = len(fingerprints) == 1 and (not comparisons or len(comparison_fingerprints) == 1)
            if not same_snapshots:
                raise ValueError("Affected paired fixture snapshots differ")
            stage = "execute"
            order = variants if repetition % 2 else tuple(reversed(variants))
            for variant in order:
                session = fixtures.enter_context(api_session(variant, relay, cleanup_evidence=cleanup[variant]["api"]))
                current[variant] = affected_case(case, repetition, session, targets[variant], relay, scope,
                                                comparisons.get(variant))
            stage = "cleanup"
    except Exception as error:  # noqa: BLE001 - all exact owned cleanup still executes through ExitStack
        for variant in variants:
            row = current.setdefault(variant, {"case": case.code, "database": database, "repetition": repetition,
                                               "variant": variant, "scope": scope, "turns": []})
            row.update({"status": "failed", "errorType": type(error).__name__, "groupErrorStage": stage})
    for variant in variants:
        row = current[variant]
        required = [cleanup[variant][key] for key in ("target", "api")]
        if case.uses_compare:
            required.append(cleanup[variant]["comparison"])
        row.update({"cleanup": cleanup[variant], "sameSnapshots": same_snapshots})
        if any(value.get("status") != "passed" for value in required):
            row.update({"status": "failed", "cleanupIncomplete": True})
    if len(variants) == 2:
        try:
            comparison = pair_comparison({**current["java"], "scope": "paired"},
                                         {**current["python"], "scope": "paired"})
        except Exception as error:  # noqa: BLE001 - pair failure must preserve each variant's evidence
            comparison = {"status": "failed", "errorType": type(error).__name__, "sameParameters": False}
        for row in current.values():
            row["pairedComparison"] = comparison
    return [current[variant] for variant in variants]


def main() -> int:
    args = options(__doc__, affected=True)
    variants: tuple[Variant, ...] = ("python",) if args.python_only else ("java", "python")
    scope = "python-only-affected-effects" if args.python_only else "paired-affected-effects"
    cases = tuple(case for case in fixed_cases() if case.code in AFFECTED_CODES)
    if {case.code for case in cases} != AFFECTED_CODES:
        raise ValueError("Affected cases no longer match the unchanged fixed matrix")

    def execute(relay: RealProviderRelay, persist: Callable[[dict[str, object]], None]) -> None:
        databases: tuple[DatabaseType, ...] = ("postgresql", "mysql")
        for database in databases:
            for repetition in range(1, 4):
                for case in cases:
                    rows = _group(case, repetition, database, variants, relay, scope)
                    for row in rows:
                        persist(row)
                    if any(row.get("cleanupIncomplete") is True for row in rows):
                        raise RuntimeError("Stop after incomplete fixture cleanup")

    return report_run(args, scope, variants, len(cases) * 2 * 3 * len(variants), execute)


if __name__ == "__main__":
    raise SystemExit(main())
