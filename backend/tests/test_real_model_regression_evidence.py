"""Offline evidence failures; this module never calls a provider or Docker."""

from __future__ import annotations

import argparse
import json
import subprocess
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import cast

import pytest
import real_model_affected_effects as affected
import real_model_api as sessions
import real_model_classification_effects as classification
import real_model_regression_support as support
from pydantic import SecretStr
from real_model_api import ApiSession, Variant
from real_model_cases import EffectCase
from real_model_database import DatabaseType, TargetSnapshot
from real_model_relay import RealProviderRelay
from real_model_synthetic_evidence import executed_sql, executed_tools, turn_evidence


def test_final_answer_contradiction_and_missing_done_are_visible() -> None:
    case = classification.CASES[0].effect()
    events: list[dict[str, object]] = [
        {"type": "step", "content": 'executeSql: {"success":true,"data":[{"order_count":6}]}'},
        {"type": "summary", "content": '[{"order_count":999}]'}, {"type": "done", "content": None},
    ]
    evidence = turn_evidence(case, 0, events, ())
    assert cast(dict[str, object], evidence["answerReview"])["status"] == "failed"
    assert cast(dict[str, object], evidence["sse"])["ended"] is True
    assert cast(dict[str, object], turn_evidence(case, 0, events[:-1], ())["sse"])["ended"] is False
    assert cast(dict[str, object], turn_evidence(case, 0, [*events, events[-1]], ())["sse"])["ended"] is False


def test_executed_sql_pairs_actual_observation_and_scrubs_secrets() -> None:
    secret = "synthetic-private-value"
    request: dict[str, object] = {"messages": [
        {"role": "system", "content": secret},
        {"role": "assistant", "reasoning_content": "unretained private reasoning", "tool_calls": [
            {"id": "sql1", "function": {"name": "executeSql", "arguments": json.dumps({
                "db_id": 12, "statement": f"SELECT '{secret}' AS value"})}}]},
        {"role": "tool", "tool_call_id": "sql1", "content": json.dumps({
            "success": True, "data": [{"value": secret}], "apiKey": secret})},
    ]}
    observed = executed_tools(request, (secret,))
    text = json.dumps(observed)
    assert secret not in text and "reasoning" not in text
    assert observed[0]["toolCallId"] == "sql1"
    assert cast(dict[str, object], observed[0]["arguments"])["statement"] == "SELECT '[omitted]' AS value"
    assert cast(dict[str, object], observed[0]["result"])["success"] is True
    assert len(executed_sql({"calls": [{"syntheticExecutedTools": observed},
                                       {"syntheticExecutedTools": observed}]}, (secret,))) == 1


class FakeSession:
    token = SecretStr("synthetic-user-token")
    event_capture: list[dict[str, object]] | None = None

    def chat(self, _body: dict[str, object]) -> tuple[list[dict[str, object]], dict[str, object]]:
        if self.event_capture is None:
            raise ValueError("Test requires partial SSE capture")
        self.event_capture.append({"type": "classified", "content": {
            "intent": "sql_query", "confidence": 0.98, "reasoning": "grounded", "needsClarification": False}})
        raise ConnectionError("synthetic-user-token must not enter evidence")


class FakeTarget:
    password = SecretStr("synthetic-database-password")

    def fingerprint(self, *, exclude_tables: tuple[str, ...] = ()) -> str:
        return "fixed-fingerprint"


class FakeRelay:
    upstream_key = SecretStr("synthetic-upstream-key")
    access_key = SecretStr("synthetic-relay-key")

    def begin(self, _label: str) -> int:
        return 0

    def request_evidence(self, _label: str, _variant: str) -> list[dict[str, object]]:
        return [{"httpStatus": 200}]


def test_transport_failure_retains_partial_classifier_and_failed_stage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(classification, "_shape", lambda _target: [])
    monkeypatch.setattr(classification, "_finished_calls", lambda _relay, _offset: [{
        "httpStatus": 200, "providerDone": True, "transportError": None, "evidenceError": None,
        "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5}}])
    row, conversation = classification._turn(
        classification.CASES[0], 0, 1, cast(ApiSession, FakeSession()), cast(TargetSnapshot, FakeTarget()),
        cast(RealProviderRelay, FakeRelay()), 12, None, None)
    assert row["status"] == "failed" and row["stage"] == "chat" and row["errorType"] == "ConnectionError"
    assert conversation is None and len(cast(list[object], row["classification"])) == 1
    assert "synthetic-user-token" not in json.dumps(row)
    assert cast(dict[str, object], row["sse"])["doneCount"] == 0


def test_final_failed_report_keeps_prior_rows_and_lf_bytes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    digest = "sha256:" + "a" * 64
    monkeypatch.setattr(support, "identity", lambda _variants: {
        "containers": {"sqlchat-s14-test-api-1": {"image": digest, "startedAt": "synthetic"}},
        "sourceHead": "synthetic-head"})

    @contextmanager
    def relay() -> Iterator[RealProviderRelay]:
        yield cast(RealProviderRelay, FakeRelay())

    monkeypatch.setattr(support, "regression_relay", relay)
    args = argparse.Namespace(output=tmp_path / "evidence.json", accepted_image=digest)

    def execute(_relay: RealProviderRelay, persist: object) -> None:
        cast(Callable[[dict[str, object]], None], persist)({"status": "passed", "turns": [{"turn": 1}]})
        raise RuntimeError("private exception body")

    assert support.report_run(args, "offline-test", ("python",), 2, execute) == 1
    report = json.loads(args.output.read_text(encoding="utf-8"))
    assert report["status"] == "failed" and report["errorType"] == "RuntimeError" and len(report["rows"]) == 1
    for path in (args.output, args.output.with_suffix(".jsonl")):
        assert b"\r\n" not in path.read_bytes() and b"private exception body" not in path.read_bytes()


def test_api_provisioning_failure_still_records_exact_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    class Client:
        headers: dict[str, str]
        closed = False

        def __init__(self, *args: object, **kwargs: object) -> None:
            self.headers = {}

        def close(self) -> None:
            self.closed = True

    client = Client()
    monkeypatch.setattr(sessions.httpx, "Client", lambda *args, **kwargs: client)
    monkeypatch.setattr(sessions, "_admin", lambda _variant: ("synthetic-admin", SecretStr("synthetic-password")))

    def api(_client: object, _method: str, path: str, *, body: object = None) -> object:
        if path == "auth/login":
            return {"token": "synthetic-admin-token"}
        raise RuntimeError("synthetic provisioning failed")

    monkeypatch.setattr(sessions, "api", api)
    cleaned: list[str] = []

    def cleanup(_variant: str, username: str) -> dict[str, object]:
        cleaned.append(username)
        return {"status": "passed", "userCount": 0}

    monkeypatch.setattr(sessions, "_cleanup", cleanup)
    evidence: dict[str, object] = {}
    with (pytest.raises(RuntimeError),
          sessions.api_session("python", cast(RealProviderRelay, FakeRelay()), cleanup_evidence=evidence)):
        pytest.fail("Provisioning must fail before yielding")
    assert client.closed and len(cleaned) == 1 and cleaned[0].startswith("s15_real_")
    assert evidence["status"] == "passed" and evidence["userCount"] == 0


def test_cleanup_subprocess_python_is_valid_and_zero_counts_are_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[list[str]] = []

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout='{"userCount":0,"messageCount":0}', stderr="")

    monkeypatch.setattr(sessions.subprocess, "run", run)
    username = "s15_real_" + "a" * 20
    assert sessions._cleanup("python", username)["status"] == "passed"
    compile(commands[0][-2], "owned-cleanup.py", "exec")
    assert commands[0][-1] == username

    monkeypatch.setattr(sessions.subprocess, "run", lambda command, **kwargs:
                        subprocess.CompletedProcess(command, 0, stdout='{"userCount":1}', stderr=""))
    with pytest.raises(RuntimeError, match="resources remain"):
        sessions._cleanup("python", username)


@pytest.mark.parametrize(("java_status", "mismatch", "comparison_error", "pair_error"), [
    ("failed", False, False, "VariantFailed"),
    ("passed", True, False, "GenerationParameterMismatch"),
    ("passed", False, True, "RuntimeError"),
])
def test_pair_failure_preserves_single_variant_verdict_and_evidence(
        monkeypatch: pytest.MonkeyPatch, java_status: str, mismatch: bool,
        comparison_error: bool, pair_error: str) -> None:
    case = next(case for case in affected.fixed_cases() if case.code == "aggregate")
    rows: dict[Variant, dict[str, object]] = {}
    for variant in ("java", "python"):
        rows[cast(Variant, variant)] = {"variant": variant, "status": java_status if variant == "java" else "passed",
                                     "turns": [{"finalAnswer": variant + " retained answer", "provider": {"calls": [
                                         {"parameters": {"model": "other" if mismatch and variant == "java" else "fixed"}}]}}]}

    @contextmanager
    def database(_database: DatabaseType, _prefix: str, *, cleanup_evidence: dict[str, object]) -> Iterator[TargetSnapshot]:
        try:
            yield cast(TargetSnapshot, FakeTarget())
        finally:
            cleanup_evidence["status"] = "passed"

    @contextmanager
    def session(variant: Variant, _relay: RealProviderRelay, *, cleanup_evidence: dict[str, object]) -> Iterator[ApiSession]:
        from types import SimpleNamespace

        try:
            yield cast(ApiSession, SimpleNamespace(variant=variant))
        finally:
            cleanup_evidence["status"] = "passed"

    def execute(_case: EffectCase, _repetition: int, current: ApiSession, _target: TargetSnapshot,
                _relay: RealProviderRelay, _scope: str, _comparison: TargetSnapshot | None) -> dict[str, object]:
        return rows[current.variant]

    def broken_comparison(_left: dict[str, object], _right: dict[str, object]) -> dict[str, object]:
        raise RuntimeError("private comparison diagnostic")

    monkeypatch.setattr(affected, "isolated_database", database)
    monkeypatch.setattr(affected, "api_session", session)
    monkeypatch.setattr(affected, "affected_case", execute)
    if comparison_error:
        monkeypatch.setattr(affected, "pair_comparison", broken_comparison)
    result = affected._group(case, 1, "postgresql", ("java", "python"), cast(RealProviderRelay, FakeRelay()), "paired-affected-effects")
    assert [row["status"] for row in result] == [java_status, "passed"]
    assert [cast(list[dict[str, object]], row["turns"])[0]["finalAnswer"] for row in result] == [
        "java retained answer", "python retained answer"]
    assert all(cast(dict[str, object], row["pairedComparison"])["errorType"] == pair_error for row in result)
    assert "private comparison diagnostic" not in json.dumps(result)


def test_unaligned_pair_fails_report_without_overwriting_variant_status(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    digest = "sha256:" + "a" * 64
    monkeypatch.setattr(support, "identity", lambda _variants: {
        "containers": {"sqlchat-s14-test-api-1": {"image": digest}}, "sourceHead": "synthetic-head"})

    @contextmanager
    def relay() -> Iterator[RealProviderRelay]:
        yield cast(RealProviderRelay, FakeRelay())

    monkeypatch.setattr(support, "regression_relay", relay)
    args = argparse.Namespace(output=tmp_path / "paired.json", accepted_image=digest)

    def execute(_relay: RealProviderRelay, persist: Callable[[dict[str, object]], None]) -> None:
        for variant in ("java", "python"):
            persist({"variant": variant, "status": "passed", "turns": [{"finalAnswer": variant}],
                     "pairedComparison": {"status": "not-comparable", "sameParameters": False}})

    assert support.report_run(args, "paired-affected-effects", ("java", "python"), 2, execute) == 1
    report = json.loads(args.output.read_text(encoding="utf-8"))
    assert report["status"] == "failed" and [row["status"] for row in report["rows"]] == ["passed", "passed"]
