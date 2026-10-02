"""Root-only trace runner: subprocess isolation and fixed, protected diagnostics."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import FrameType
from typing import cast

import pytest

CASE = "test_real_http_worker_parent_chain_and_locale_reset"
NODE = "tests/test_s14_runtime_tracing.py::" + CASE
SOURCES = {
    "test_s14_runtime_support.py": "cbda0a11782a801986666782b40b387966757d9b3485cdf4b530c69806792ada",
    "test_s14_runtime_metrics.py": "3e5822ca478cec7f9faf109752cf5dd9a3ef3340cbf87cdcbf237e6ba70232f3",
    "test_s14_runtime_tracing.py": "4aa4ac9f0086fded3d827ac1e45603f06662abc51b6a9feaaf94e2f741f14eeb",
    "test_s14_runtime_trace_schedule.py": "15ee5efe0f361c4495d02bdbfd38398621c8ba38e6f2d89137140f333f624349",
}
STAGES = {
    200: "endpoint", 204: "transport", 208: "capture_preflight", 211: "target_provision",
    212: "concurrent_create", 216: "worker_completion", 217: "parent_chain",
    225: "locale_resource", 228: "same_channel_reset", 231: "privacy", 236: "case_report",
}
Json = dict[str, object]
type Trace = Callable[[FrameType, str, object], Trace | None]


def protected(error: BaseException) -> Json:
    seen: set[int] = set()
    for _ in range(12):
        seen.add(id(error))
        cause = error.__cause__ if error.__cause__ is not None else error.__context__
        if cause is None or id(cause) in seen:
            break
        error = cause
    source, line = "unknown.py", 0
    frame = error.__traceback__
    while frame is not None:
        source, line = Path(frame.tb_frame.f_code.co_filename).name, frame.tb_lineno
        frame = frame.tb_next
    name = type(error).__name__
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,79}", name) is None:
        name = "UnknownError"
    if re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", source) is None:
        source = "unknown.py"
    return {"errorType": name, "source": source, "line": line}


def save(path: Path, values: Json) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(values, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


class Diagnostics:
    def __init__(self, path: Path, tracing: Path) -> None:
        self.path, self.tracing = path, tracing
        self.state: Json = {"stage": "child_boot", "setupPassed": False, "callPassed": False,
                            "teardownPassed": False, "sessionFinished": False, "skipped": False}
        self.case_line = 0
        self.previous_trace: Trace | None = None
        self.checkpoint("child_boot")

    def checkpoint(self, stage: str) -> None:
        self.state["stage"] = stage
        save(self.path, self.state)

    def failure(self, error: BaseException) -> None:
        details = protected(error)
        stage = self.state["stage"]
        if details["source"] == "test_s14_runtime_trace_schedule.py":
            stage = "same_channel_reset"
        elif details["source"] == "test_s14_runtime_tracing.py":
            line = details["line"]
            if isinstance(line, int) and 200 <= line <= 242:
                stage = STAGES[max(start for start in STAGES if start <= line)]
        details["stage"] = stage
        self.state["failure"] = details
        save(self.path, self.state)

    def trace(self, frame: FrameType, event: str, argument: object) -> Trace | None:
        if frame.f_code.co_name != CASE or Path(frame.f_code.co_filename).resolve() != self.tracing:
            return None
        if event == "line" and frame.f_lineno in STAGES and frame.f_lineno >= self.case_line:
            self.case_line = frame.f_lineno
            self.checkpoint(STAGES[frame.f_lineno])
        if event == "exception" and isinstance(argument, tuple) and len(argument) == 3:
            error = argument[1]
            if isinstance(error, BaseException):
                self.failure(error)
        return self.trace

    def pytest_configure(self, config: pytest.Config) -> None:
        self.previous_trace = cast(Trace | None, sys.gettrace())
        sys.settrace(self.trace)

    def pytest_runtest_setup(self, item: pytest.Item) -> None:
        self.checkpoint("setup")

    def pytest_runtest_teardown(self, item: pytest.Item, nextitem: pytest.Item | None) -> None:
        self.checkpoint("owner_cleanup")

    def pytest_runtest_makereport(self, item: pytest.Item, call: pytest.CallInfo[None]) -> None:
        if call.when not in {"setup", "call", "teardown"}:
            return
        self.state[call.when + "Passed"] = call.excinfo is None
        if call.excinfo is not None:
            if issubclass(call.excinfo.type, pytest.skip.Exception):
                self.state["skipped"] = True
            self.failure(call.excinfo.value)
        else:
            save(self.path, self.state)

    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:
        self.state.update(sessionFinished=True, pytestExitCode=int(exitstatus))
        save(self.path, self.state)

    def pytest_unconfigure(self, config: pytest.Config) -> None:
        sys.settrace(self.previous_trace)


def child(backend: Path, report: Path) -> int:
    sys.path.insert(0, str(backend))
    sys.path.insert(0, str(backend / "tests"))
    diagnostics = Diagnostics(report / "trace_diagnostic_child.json", backend / NODE.split("::")[0])
    try:
        return int(pytest.main(["-p", "no:cacheprovider", "-q", "--tb=no", "-rN", NODE],
                               plugins=[diagnostics]))
    except BaseException as error:  # noqa: BLE001 - contain SystemExit without original diagnostics
        diagnostics.failure(error)
        return 1
    finally:
        sys.settrace(diagnostics.previous_trace)


def configured(backend: Path) -> Path:
    if os.environ.get("SQLCHAT_S14_RUNTIME_LIVE") != "1":
        raise RuntimeError("Explicit live opt-in required")
    env_value = os.environ.get("SQLCHAT_S14_RUNTIME_ENV_FILE")
    report_value = os.environ.get("SQLCHAT_S14_RUNTIME_REPORT_DIR")
    if env_value is None or report_value is None:
        raise RuntimeError("Explicit root paths required")
    env = Path(env_value).resolve(strict=True)
    report = Path(report_value).resolve()
    if (env.name != ".env.s14" or not (env.parent / ".git").is_dir()
            or not report.is_relative_to(env.parent / ".git/acceptance")
            or report.is_relative_to(backend.parent)):
        raise RuntimeError("Reports require independent root acceptance directory")
    for name, digest in SOURCES.items():
        if hashlib.sha256((backend / "tests" / name).read_bytes()).hexdigest() != digest:
            raise RuntimeError("Frozen fixture SHA mismatch")
    report.mkdir(parents=True, exist_ok=True)
    for name in ("trace_diagnostic_parent.json", "trace_diagnostic_child.json", "worker_trace_locale.json",
                 "owner_cleanup_" + CASE + ".json"):
        if (report / name).exists():
            raise RuntimeError("Fresh trace report directory required")
    return report


def evidence(report: Path) -> bool:
    for name, key in (("worker_trace_locale.json", "passed"),
                      ("owner_cleanup_" + CASE + ".json", "owner_cleanup")):
        path = report / name
        if not path.is_file():
            return False
        packet: object = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(packet, dict) or packet.get(key) is not True:
            return False
    return True


def parent(backend: Path, report: Path) -> int:
    result_path = report / "trace_diagnostic_parent.json"
    result: Json = {"stage": "process_start", "completed": False, "passed": False}
    save(result_path, result)
    environment = dict(os.environ)
    environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--child", str(backend)],
                               cwd=backend, env=environment, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
    try:
        code = process.wait(timeout=300)
    except subprocess.TimeoutExpired:
        process.kill()
        code = process.wait(timeout=30)
        result["timedOut"] = True
    except BaseException:  # terminate only this runner-owned test process, then fail
        process.kill()
        process.wait(timeout=30)
        raise
    child_path = report / "trace_diagnostic_child.json"
    state: object = json.loads(child_path.read_text(encoding="utf-8")) if child_path.is_file() else {}
    if not isinstance(state, dict):
        raise TypeError("Protected child report must be object")
    result.update(childExitCode=code, completed=state.get("sessionFinished") is True,
                  lastStage=state.get("stage", "child_boot"), skipped=state.get("skipped") is True)
    failure = state.get("failure")
    passed = (code == 0 and state.get("sessionFinished") is True
              and all(state.get(phase + "Passed") is True for phase in ("setup", "call", "teardown"))
              and state.get("skipped") is not True and evidence(report))
    if isinstance(failure, dict):
        result.update(failure)
    elif not passed:
        result.update(stage=state.get("stage", "child_boot"), errorType="ProcessExit" if code != 0 else
                      "EvidenceIncomplete", source=Path(__file__).name, line=0)
    else:
        result["stage"] = "finished"
    result["passed"] = passed
    save(result_path, result)
    print(json.dumps(result, sort_keys=True))
    return 0 if passed else 1


def main() -> int:
    stage = "configuration"
    try:
        if len(sys.argv) != 3 or sys.argv[1] not in {"--backend", "--child"}:
            raise ValueError("Explicit backend mode required")
        backend = Path(sys.argv[2]).resolve(strict=True)
        if sys.argv[1] == "--child":
            value = os.environ.get("SQLCHAT_S14_RUNTIME_REPORT_DIR")
            if value is None:
                raise RuntimeError("Explicit report directory required")
            return child(backend, Path(value).resolve())
        report = configured(backend)
        stage = "process_control"
        return parent(backend, report)
    except BaseException as error:  # noqa: BLE001 - contain SystemExit without original diagnostics
        result = protected(error)
        result.update(stage=stage, passed=False)
        print(json.dumps(result, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
