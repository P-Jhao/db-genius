"""Actual API matrix runner; neither model text nor secrets enter its evidence."""

from __future__ import annotations

import re
import threading
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime
from time import monotonic, sleep

from dotenv import dotenv_values
from pydantic import SecretStr
from real_model_answers import redact_answer
from real_model_api import ROOT, ApiSession, Variant, api_session, runtime_identity
from real_model_cases import LOCALE, MODEL, REPETITIONS, EffectCase, fixed_cases
from real_model_database import TargetSnapshot, isolated_database
from real_model_evidence import judge_turn
from real_model_relay import RealProviderRelay, object_value
from real_model_report import aggregate, application_usage, pair_comparison, provider_summary


def provider_key() -> SecretStr:
    values = dotenv_values(ROOT / "backend/.env", interpolate=False)
    if values.get("SQLCHAT_DEFAULT_MODEL_NAME") != MODEL:
        raise ValueError("backend/.env must explicitly select the fixed acceptance model")
    if values.get("SQLCHAT_DEFAULT_MODEL_BASE_URL") != "https://api.deepseek.com":
        raise ValueError("backend/.env must select the fixed actual provider")
    value = values.get("SQLCHAT_DEFAULT_MODEL_API_KEY")
    if not value:
        raise ValueError("The actual provider key must be present in backend/.env")
    return SecretStr(value)


@contextmanager
def running_relay(*, calibration: bool = False) -> Iterator[RealProviderRelay]:
    relay = RealProviderRelay(SecretStr("unused-calibration-key") if calibration else provider_key(),
                             "http://127.0.0.1:9" if calibration else "https://api.deepseek.com")
    thread = threading.Thread(target=relay.serve_forever, daemon=True)
    thread.start()
    try:
        yield relay
    finally:
        relay.shutdown()
        relay.server_close()
        thread.join(3)


def _conversation(events: list[dict[str, object]]) -> int | None:
    ids = [event["content"] for event in events if event.get("type") == "conversation"]
    if not ids:
        return None
    if len(ids) != 1 or not isinstance(ids[0], int) or isinstance(ids[0], bool):
        raise ValueError("Expected one actual conversation ID")
    return ids[0]


def _finished_calls(relay: RealProviderRelay, offset: int) -> list[dict[str, object]]:
    deadline = monotonic() + 2
    while True:
        records = relay.evidence(offset)
        if all(row.get("elapsedSeconds") is not None for row in records) or monotonic() >= deadline:
            return records
        sleep(0.01)


def run_case(case: EffectCase, repetition: int, session: ApiSession, target: TargetSnapshot,
             relay: RealProviderRelay, comparison_target: TargetSnapshot | None = None) -> dict[str, object]:
    scope = "local-file-only" if case.uses_file else "paired"
    result: dict[str, object] = {"case": case.code, "repetition": repetition, "database": target.db_type,
                               "variant": session.variant, "scope": scope, "status": "failed", "turns": []}
    if case.uses_file and session.variant == "java":
        return {**result, "status": "environment-blocked", "errorType": "OriginalOssUnavailable"}
    turns: list[dict[str, object]] = []
    conversation_id: int | None = None
    stage = "connect"
    try:
        selected_id = session.connect(target)
        test_id = session.connect(comparison_target) if comparison_target is not None else None
        file_id = session.upload_csv() if case.uses_file else None
        for index, question in enumerate(case.questions):
            body: dict[str, object] = {"message": question, "dbConfigIds": [selected_id]}
            if case.intent is not None:
                body["confirmedIntent"] = case.intent
            if conversation_id is not None:
                body["conversationId"] = conversation_id
            if test_id is not None:
                body.update({"preDbConfigId": selected_id, "testDbConfigId": test_id})
            if file_id is not None:
                body["fileIds"] = [file_id]
            before = target.fingerprint(exclude_tables=("imported_contacts",) if case.uses_file else ())
            comparison_before = comparison_target.fingerprint() if comparison_target is not None else None
            label = f"{target.db_type}/{case.code}/{repetition}/{index + 1}"
            offset = relay.begin(label)
            stage = "chat"
            try:
                events, timing = session.chat(body)
                current_id = _conversation(events)
                if conversation_id is not None and current_id != conversation_id:
                    raise ValueError("Follow-up did not reuse its actual conversation")
                conversation_id = current_id
                stage = "history"
                history = session.messages(current_id) if current_id is not None else []
                if history and [row.get("content") for row in history if row.get("role") == "user"] != list(
                    case.questions[:index + 1]
                ):
                    raise ValueError("Persisted user turns differ from the fixed sequence")
                stage = "oracle"
                turn = judge_turn(case, index, events, history, target, before, comparison_target)
                review = object_value(turn["answerReview"])
                redact_answer(review, (relay.upstream_key.get_secret_value(), relay.access_key.get_secret_value(),
                                      session.token.get_secret_value(), target.password.get_secret_value()), case.questions)
                if turn["status"] == "passed" and review["status"] == "review-required":
                    turn.update({"status": "review-required", "errorType": "GroundedAnswerReviewRequired"})
                if comparison_target is not None and comparison_target.fingerprint() != comparison_before:
                    turn.update({"status": "failed", "errorType": "ComparisonTargetChanged"})
                provider = provider_summary(_finished_calls(relay, offset))
                turn.update({"turn": index + 1, **timing, "provider": provider,
                             "application": application_usage(events, provider),
                             "relayRequests": relay.request_evidence(label, session.variant)})
                calls = provider["calls"]
                if not isinstance(calls, list):
                    raise TypeError("Expected recorded provider calls")
                if not calls or any(object_value(call).get("httpStatus") != 200 or
                                    object_value(call).get("transportError") is not None or
                                    object_value(call).get("evidenceError") is not None or
                                    object_value(call).get("providerDone") is not True for call in calls):
                    turn.update({"status": "failed", "errorType": "ProviderIncomplete"})
                if object_value(turn["application"])["usageMatchesProvider"] is False:
                    turn.update({"status": "failed", "errorType": "UsageMismatch"})
                turns.append(turn)
            except Exception as error:  # noqa: BLE001 - redact diagnostics and preserve every prior result
                turns.append({"turn": index + 1, "status": "failed", "errorType": type(error).__name__,
                              "stage": stage, "provider": provider_summary(_finished_calls(relay, offset)),
                              "relayRequests": relay.request_evidence(label, session.variant)})
                break  # Never automatically resend a turn that might have committed a write.
        passed = len(turns) == len(case.questions) and all(turn["status"] == "passed" for turn in turns)
        failed = len(turns) != len(case.questions) or any(turn["status"] == "failed" for turn in turns)
        result.update({"status": "passed" if passed else "failed" if failed else "review-required", "turns": turns,
                       "errorType": None if passed else next(
                           (turn["errorType"] for turn in turns if turn["status"] != "passed"), "IncompleteCase")})
    except Exception as error:  # noqa: BLE001 - never persist exception messages or a traceback with locals
        result.update({"errorType": type(error).__name__, "stage": stage, "turns": turns})
    return result


def calibrate() -> dict[str, object]:
    rows: list[dict[str, object]] = []
    with running_relay(calibration=True) as relay:
        for db_type in ("postgresql", "mysql"):
            fingerprints: list[str] = []
            for variant in ("java", "python"):
                with (isolated_database(db_type, "java" if variant == "java" else "py") as target,
                      api_session(variant, relay) as session):
                    fingerprints.append(target.fingerprint())
                    session.connect(target)
                    rows.append({"database": db_type, "variant": variant, "status": "passed",
                                 "role": "user", "workerConnected": True, "metadataGenerated": True})
            if len(set(fingerprints)) != 1:
                raise ValueError("Original/Python synthetic snapshots differ")
        if relay.evidence(0):
            raise RuntimeError("Calibration unexpectedly called a provider")
    return {"mode": "api-fixture-calibration", "status": "passed", "modelCallCount": 0,
            "sameSnapshots": True, "rows": rows}


def benchmark(accepted_image: str, on_result: Callable[[dict[str, object]], None]) -> dict[str, object]:
    if re.fullmatch(r"sha256:[0-9a-f]{64}", accepted_image) is None:
        raise ValueError("Supply the exact accepted and rebuilt Python image SHA")
    identity = runtime_identity()
    if object_value(identity["sqlchat-s14-test-api-1"])["image"] != accepted_image:
        raise ValueError("The running Python deployment differs from the accepted image")
    rows: list[dict[str, object]] = []
    pairs: list[dict[str, object]] = []
    with running_relay() as relay, ExitStack() as sessions:
        apis = {variant: sessions.enter_context(api_session(variant, relay)) for variant in ("java", "python")}
        for db_type in ("postgresql", "mysql"):
            for repetition in range(1, REPETITIONS + 1):
                for case in fixed_cases():
                    with ExitStack() as fixtures:
                        targets = {variant: fixtures.enter_context(isolated_database(
                            db_type, "java" if variant == "java" else "py")) for variant in ("java", "python")}
                        comparisons = {variant: fixtures.enter_context(isolated_database(
                            db_type, "test", comparison_target=True)) for variant in targets} if case.uses_compare else {}
                        if targets["java"].fingerprint() != targets["python"].fingerprint():
                            raise ValueError("Paired fixture snapshots differ")
                        if comparisons and comparisons["java"].fingerprint() != comparisons["python"].fingerprint():
                            raise ValueError("Paired comparison target snapshots differ")
                        current: dict[str, dict[str, object]] = {}
                        order: tuple[Variant, ...] = ("java", "python") if repetition % 2 else ("python", "java")
                        for variant in order:
                            row = run_case(case, repetition, apis[variant], targets[variant], relay, comparisons.get(variant))
                            rows.append(row)
                            current[variant] = row
                            on_result(row)
                        pairs.append({"case": case.code, "database": db_type, "repetition": repetition,
                                      **pair_comparison(current["java"], current["python"])})
    return {"mode": "actual-provider-comparison", "createdAt": datetime.now(UTC).isoformat(),
            "model": MODEL, "provider": "https://api.deepseek.com", "locale": LOCALE,
            "repetitions": REPETITIONS, "runtime": identity, "rows": rows, "pairs": pairs,
            "summary": aggregate(rows), "status": "incomplete" if any(pair["status"] != "passed" for pair in pairs)
            else "passed"}


def diagnose_java(on_result: Callable[[dict[str, object]], None], selected_case: str | None = None) -> dict[str, object]:
    if selected_case is not None and selected_case not in {"aggregate", "ambiguity"}:
        raise ValueError("Unknown original diagnostic case")
    rows: list[dict[str, object]] = []
    with running_relay() as relay, api_session("java", relay) as session:
        for case in fixed_cases():
            if case.code not in {"aggregate", "ambiguity"}:
                continue
            if selected_case is not None and case.code != selected_case:
                continue
            with isolated_database("postgresql", "java") as target:
                row = run_case(case, 1, session, target, relay)
                row["scope"] = "original-diagnostic"
                rows.append(row)
                on_result(row)
    return {"mode": "original-diagnostic", "status": "diagnostic", "model": MODEL, "locale": LOCALE,
            "rows": rows, "summary": aggregate(rows), "runtime": runtime_identity()}
