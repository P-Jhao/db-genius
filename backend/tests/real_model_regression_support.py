"""Runtime binding and exception-safe reports for opt-in affected-effect runs."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from real_model_api import ROOT, Variant
from real_model_cases import LOCALE, MODEL
from real_model_relay import RealProviderRelay, object_value
from real_model_runner import provider_key

SOURCE_FILES = (
    "backend/app/agent/prompts.py", "backend/app/agent/graph.py", "backend/app/agent/graph_sql.py",
    "backend/app/agent/report_rules.py", "backend/tests/real_model_classification_regression.py",
    "backend/tests/real_model_classification_effects.py",
    "backend/tests/real_model_affected_effects.py", "backend/tests/real_model_regression_support.py",
    "backend/tests/real_model_synthetic_evidence.py", "backend/tests/real_model_api.py",
    "backend/tests/real_model_database.py", "backend/tests/real_model_relay.py",
    "backend/tests/real_model_runner.py", "backend/tests/real_model_evidence.py",
    "backend/tests/real_model_answers.py", "backend/tests/real_model_report.py",
    "backend/tests/real_model_cases.py", "backend/tests/real_model_oracles.py",
    "scripts/acceptance/classification_regression.py", "scripts/acceptance/affected_effects.py",
    "backend/app/resources/prompts/intent-classifier_zh_CN.md",
    "backend/app/resources/prompts/intent-classifier_en.md",
)


def identity(variants: tuple[Variant, ...]) -> dict[str, object]:
    containers = ["sqlchat-s14-test-api-1", "sqlchat-migration-test-postgres", "sqlchat-migration-test-mysql"]
    if "java" in variants:
        containers.append("sqlchat-s15-java")
    runtime: dict[str, object] = {}
    for name in containers:
        inspected = subprocess.run(["docker", "inspect", "--format", "{{.Image}}|{{.State.StartedAt}}", name],
                                   capture_output=True, text=True, check=True)
        image, started = inspected.stdout.strip().split("|", 1)
        runtime[name] = {"image": image, "startedAt": started}
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True)
    hashes = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in SOURCE_FILES}
    original = ROOT / ".git/acceptance/original-73bb7e87cf32-manifest.json"
    return {"containers": runtime, "sourceHead": head.stdout.strip(), "sourceHashes": hashes,
            "originalSourceManifestSha256": hashlib.sha256(original.read_bytes()).hexdigest()
            if original.is_file() else None, "model": MODEL, "locale": LOCALE}


@contextmanager
def regression_relay() -> Iterator[RealProviderRelay]:
    relay = RealProviderRelay(provider_key(), capture_synthetic=True)
    thread = threading.Thread(target=relay.serve_forever, daemon=True)
    thread.start()
    try:
        yield relay
    finally:
        relay.shutdown()
        relay.server_close()
        thread.join(3)


def options(description: str | None, *, affected: bool = False) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--run", action="store_true", help="Explicitly allow real provider calls")
    parser.add_argument("--accepted-image", required=True, help="Reviewed running Python image SHA256")
    parser.add_argument("--output", type=Path, required=True)
    if affected:
        parser.add_argument("--python-only", action="store_true", help="Use explicitly unpaired Python scope")
    args = parser.parse_args()
    if not args.run:
        raise ValueError("Real-provider execution requires --run")
    if re.fullmatch(r"sha256:[0-9a-f]{64}", args.accepted_image) is None:
        raise ValueError("Expected an exact reviewed Docker image digest")
    directory = (ROOT / "docs/phase-15-classification-report-fix").resolve()
    destination = args.output.resolve()
    if not destination.is_relative_to(directory) or destination.suffix != ".json":
        raise ValueError("Evidence must be JSON in the dedicated existing phase directory")
    if not destination.parent.is_dir() or destination.exists() or destination.with_suffix(".jsonl").exists():
        raise FileExistsError("Choose a fresh evidence path; prior reports are immutable")
    args.output = destination
    return args


def report_run(args: argparse.Namespace, scope: str, variants: tuple[Variant, ...], expected_rows: int,
               execute: Callable[[RealProviderRelay, Callable[[dict[str, object]], None]], None]) -> int:
    rows: list[dict[str, object]] = []
    report: dict[str, object] = {"scope": scope, "createdAt": datetime.now(UTC).isoformat(),
                               "model": MODEL, "locale": LOCALE, "repetitions": 3,
                               "expectedRows": expected_rows, "variants": variants, "rows": rows,
                               "status": "failed", "runtimeBefore": None, "runtimeAfter": None,
                               "evidenceEncoding": "UTF-8", "evidenceNewlines": "LF",
                               "hashRule": "SHA-256 over exact saved bytes after file close"}

    def persist(row: dict[str, object]) -> None:
        rows.append(row)
        with args.output.with_suffix(".jsonl").open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
        print(json.dumps({key: row.get(key) for key in ("scope", "case", "database", "repetition", "variant", "status")}),
              flush=True)

    try:
        before = identity(variants)
        report["runtimeBefore"] = before
        containers = object_value(before["containers"])
        if object_value(containers["sqlchat-s14-test-api-1"])["image"] != args.accepted_image:
            raise ValueError("Python API image differs from the reviewed candidate")
        with regression_relay() as relay:
            execute(relay, persist)
        if len(rows) != expected_rows:
            raise ValueError("The expected case/repetition/variant matrix is incomplete")
        statuses = [row["status"] for row in rows]
        if len(variants) == 2:
            statuses.extend(object_value(row["pairedComparison"])["status"] for row in rows)
        if any(status not in {"passed", "review-required"} for status in statuses):
            report["status"] = "failed"
        elif "review-required" in statuses:
            report["status"] = "review-required"
        else:
            report["status"] = "passed"
    except Exception as error:  # noqa: BLE001 - do not persist exception messages or private locals
        report.update({"status": "failed", "errorType": type(error).__name__})
    finally:
        try:
            after = identity(variants)
            report["runtimeAfter"] = after
            report["runtimeStable"] = report["runtimeBefore"] == after
            if report["runtimeStable"] is not True:
                report.update({"status": "failed", "runtimeErrorType": "RuntimeOrSourcesChanged"})
        except Exception as error:  # noqa: BLE001 - preserve prior results even if runtime inspection fails
            report.update({"status": "failed", "runtimeErrorType": type(error).__name__, "runtimeStable": False})
        report["finishedAt"] = datetime.now(UTC).isoformat()
        with args.output.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
    jsonl = args.output.with_suffix(".jsonl")
    print(json.dumps({"scope": scope, "status": report["status"],
                      "evidenceSha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
                      "jsonlSha256": hashlib.sha256(jsonl.read_bytes()).hexdigest() if jsonl.is_file() else None}), flush=True)
    return 0 if report["status"] == "passed" else 1
