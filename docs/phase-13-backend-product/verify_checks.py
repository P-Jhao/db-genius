"""Durable, prompt-free S13 checks; only summaries leave the subprocess boundary."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from time import monotonic

STRICT_FILES = [
    "app/agent/dsml.py", "app/agent/streaming.py", "app/agent/model.py", "app/agent/product_locale.py",
    "app/core/request_locale.py", "app/services/trial.py", "app/api/trial.py",
    "app/services/db_config_common.py", "app/services/db_config_init.py", "app/tasks/db_config.py",
    "tests/test_dsml.py", "tests/test_dsml_revision.py", "tests/test_dsml_http.py",
    "tests/test_product_locale.py", "tests/test_queue_locale.py", "tests/test_trial.py",
    "tests/test_trial_targets.py", "tests/test_trial_api_matrix.py", "tests/test_trial_graph_targets.py",
    "tests/test_locale_concurrent_sse.py", "../docs/phase-13-backend-product/verify_real_targets.py",
    "../docs/phase-13-backend-product/verify_checks.py",
]
BRIDGE_FILES = [
    "tests/test_product_locale.py", "tests/test_locale_concurrent_sse.py", "tests/test_trial_api_matrix.py",
    "tests/test_queue_locale.py", "tests/test_model_parameters.py", "tests/test_chat_graph.py",
    "tests/test_chat_api.py", "tests/test_trial.py", "tests/test_dsml_http.py", "tests/test_dsml_revision.py",
    "tests/test_model_protocol.py", "tests/test_mongodb_config.py", "tests/test_db_config_partial.py",
    "tests/test_mongodb_credentials.py", "tests/test_output_guard_contract.py",
]


def run(group: str) -> int:
    root = Path(__file__).resolve().parents[2]
    backend = root / "backend"
    evidence_path = Path(__file__).with_name("checks.json")
    environment = {**os.environ, "PYTHONPATH": str(backend)}
    commands = []
    if group in {"all", "static"}:
        commands += [["-m", "ruff", "check", "app", "tests", "../docs/phase-13-backend-product"],
                     ["-m", "mypy", "app"],
                     ["-m", "mypy", *STRICT_FILES, "--strict", "--follow-imports=silent"]]
    if group in {"all", "bridge"}:
        commands.append(["-m", "pytest", *BRIDGE_FILES, "-q"])
    report: dict[str, object] = {"baseCommit": (root / "BASELINE").read_text().strip(),
        "kind": "deterministic source/HTTP/SQLite contract; no actual provider or external queue",
        "group": group, "complete": False, "stages": [],
        "ownedSourceSha256": {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in backend.rglob("*.py") if "__pycache__" not in path.parts}}
    stages: list[dict[str, object]] = []
    report["stages"] = stages
    def persist() -> None:
        evidence_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="")
    persist()
    for arguments in commands:
        started = monotonic()
        result = subprocess.run([sys.executable, *arguments], cwd=backend, env=environment,
                                capture_output=True, text=True, check=False)
        output = result.stdout + result.stderr
        summary = [line for line in output.splitlines() if re.match(
            r"^(Success:|All checks passed!|Found \d+ errors?|\d+ passed|=+.*(?:passed|failed|skipped))", line)]
        failed = re.findall(r"^FAILED (\S+)", output, re.MULTILINE)
        count = re.search(r"(\d+) passed", output)
        skip = re.search(r"(\d+) skipped", output)
        stage = {"command": "python " + " ".join(arguments), "exitCode": result.returncode,
                 "elapsedSeconds": round(monotonic() - started, 3), "summaries": summary,
                 "failedTestIds": failed, "passed": int(count[1]) if count else None,
                 "skipped": int(skip[1]) if skip else 0}
        stages.append(stage)
        persist()
        print(json.dumps(stage, ensure_ascii=False), flush=True)
        if result.returncode != 0:
            report["complete"] = True
            report["exitCode"] = result.returncode
            persist()
            return result.returncode
    report["complete"] = True
    report["exitCode"] = 0
    persist()
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--group", choices=("all", "static", "bridge"), default="all")
    raise SystemExit(run(parser.parse_args().group))
