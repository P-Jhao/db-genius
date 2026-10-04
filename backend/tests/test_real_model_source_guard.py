"""Offline source binding detects final-report changes without runtime commands."""

import argparse
import hashlib
import json
import subprocess
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import cast

import pytest
import real_model_regression_support as support
from real_model_relay import RealProviderRelay

FINAL_REPORT_SOURCES = {
    "backend/app/agent/final_report.py", "backend/app/agent/streaming.py",
    "backend/app/agent/model.py", "backend/app/agent/dsml.py",
    "backend/app/agent/product_locale.py", "backend/app/api/chat.py",
    "backend/app/core/observability_runtime.py", "backend/tests/real_model_observations.py",
    "backend/app/agent/compare_preflight.py",
    "backend/app/agent/protocol_errors.py", "backend/app/core/observability_logging.py",
    "backend/tests/real_model_relay.py", "backend/tests/real_model_metadata_evidence.py",
    "backend/app/core/config.py", "backend/app/agent/json_capabilities.py",
    "backend/app/agent/json_shape_diagnostics.py",
}
IMAGE = "sha256:" + "a" * 64


def test_source_binding_covers_final_report_and_comparison_preflight() -> None:
    assert FINAL_REPORT_SOURCES.issubset(support.SOURCE_FILES)
    assert len(support.SOURCE_FILES) == len(set(support.SOURCE_FILES))


def install_sources(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for index, name in enumerate(support.SOURCE_FILES):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = f"synthetic-source-{index}\r\n".encode()
        path.write_bytes(payload)
        hashes[name] = hashlib.sha256(payload).hexdigest()
    monkeypatch.setattr(support, "ROOT", tmp_path)
    return hashes


def install_runtime_mock(monkeypatch: pytest.MonkeyPatch, commands: list[list[str]]) -> None:
    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        if command[:2] == ["docker", "inspect"]:
            output = IMAGE + "|synthetic-started\n"
        elif command == ["git", "rev-parse", "HEAD"]:
            output = "synthetic-head\n"
        else:
            raise AssertionError("Unexpected external command requested")
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

    monkeypatch.setattr(subprocess, "run", run)


@pytest.mark.parametrize("variants", [("python",), ("java", "python")])
def test_identity_binds_exact_bytes_for_every_source_without_real_commands(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, variants: tuple[str, ...],
) -> None:
    from real_model_api import Variant

    hashes = install_sources(monkeypatch, tmp_path)
    commands: list[list[str]] = []
    install_runtime_mock(monkeypatch, commands)
    observed = support.identity(cast(tuple[Variant, ...], variants))
    assert observed["sourceHashes"] == hashes
    assert observed["sourceHead"] == "synthetic-head"
    assert observed["originalSourceManifestSha256"] is None
    assert len(commands) == (5 if "java" in variants else 4)
    containers = cast(dict[str, object], observed["containers"])
    assert ("sqlchat-s15-java" in containers) == ("java" in variants)


@pytest.mark.parametrize("changed_source", sorted(FINAL_REPORT_SOURCES))
def test_changed_final_report_source_fails_runtime_guard_and_retains_row_status(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, changed_source: str,
) -> None:
    install_sources(monkeypatch, tmp_path)
    commands: list[list[str]] = []
    install_runtime_mock(monkeypatch, commands)

    @contextmanager
    def relay() -> Iterator[RealProviderRelay]:
        yield cast(RealProviderRelay, object())

    monkeypatch.setattr(support, "regression_relay", relay)
    args = argparse.Namespace(output=tmp_path / "synthetic-evidence.json", accepted_image=IMAGE)

    def execute(_relay: RealProviderRelay, persist: Callable[[dict[str, object]], None]) -> None:
        persist({"status": "review-required", "turns": [{"finalAnswer": "retained synthetic answer"}]})
        path = tmp_path / changed_source
        path.write_bytes(path.read_bytes() + b"synthetic-mutated\n")

    assert support.report_run(args, "offline-source-guard", ("python",), 1, execute) == 1
    report = json.loads(args.output.read_text(encoding="utf-8"))
    assert report["status"] == "failed" and report["runtimeStable"] is False
    assert report["runtimeErrorType"] == "RuntimeOrSourcesChanged"
    assert report["rows"][0]["status"] == "review-required"
    assert report["rows"][0]["turns"][0]["finalAnswer"] == "retained synthetic answer"
    before = report["runtimeBefore"]["sourceHashes"]
    after = report["runtimeAfter"]["sourceHashes"]
    assert {name for name in before if before[name] != after[name]} == {changed_source}
    assert len(commands) == 8
