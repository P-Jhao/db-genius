"""Private fixture paths, redacted evidence, and explicitly scoped type checks."""

import os
import subprocess
import sys
from pathlib import Path

PHASE = Path(__file__).resolve().parent
BACKEND = PHASE.parents[1] / "backend"
RUNTIME = Path("C:/Users/22126/Desktop/web/text2sql/sqlchat/.git/acceptance/s12-runtime")
sys.path.insert(0, str(BACKEND))
from app.adapters.diagnostics import sanitize_diagnostic
from app.adapters.types import DbConnectionConfig


def redact(output: str) -> str:
    for path in (RUNTIME / "oracle-target.env", RUNTIME / "sqlserver.env"):
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            key, separator, value = line.partition("=")
            if separator and "PASSWORD" in key:
                output = sanitize_diagnostic(output, DbConnectionConfig(
                    "oracle", "localhost", 1521, "fixture", "fixture", value.strip().strip('"').strip("'")))
    return sanitize_diagnostic(output, DbConnectionConfig("oracle", "localhost", 1521, "fixture", "fixture", ""))


def main() -> int:
    if sys.argv[1:] not in ([], ["--static-only"], ["--all-real"]):
        raise ValueError("Supported flags: --static-only or --all-real")
    os.environ["SQLCHAT_ORACLE_RUNTIME"] = str(RUNTIME / "oracle-target.env")
    os.environ["SQLCHAT_SQLSERVER_RUNTIME"] = str(RUNTIME / "sqlserver.env")
    commands = {
        "real-last-local": ["pytest", "-q", "-s",
            "tests/test_native_sql_repair_real.py::test_actual_native_select_error_is_rolled_back_and_model_corrected[oracle-order-904]"],
        "ruff-verified": ["ruff", "check", "app", "tests"],
        "mypy-app-verified": ["mypy", "app"],
        "mypy-owned-strict-verified": ["mypy", "--strict", "app/agent/sql_errors.py"],
    }
    if sys.argv[1:] == ["--all-real"]:
        first = next(iter(commands))
        commands[first] = ["pytest", "-q", "-s", "tests/test_native_sql_repair_policy.py",
                           "tests/test_native_sql_repair_graph.py", "tests/test_native_sql_repair_real.py"]
    suffix = os.environ.get("REPAIR_EVIDENCE_SUFFIX", "")
    if any(not (character.isalnum() or character in "-_") for character in suffix):
        raise ValueError("Invalid evidence suffix")
    for name, arguments in commands.items():
        if sys.argv[1:] == ["--static-only"] and arguments[0] == "pytest":
            continue
        if suffix:
            name += "-" + suffix
        destination = PHASE / f"{name}.log"
        if destination.exists():
            raise FileExistsError("Cannot overwrite evidence: " + destination.name)
        result = subprocess.run([sys.executable, "-m", *arguments], cwd=BACKEND,
                                capture_output=True, encoding="utf-8", errors="replace", check=False)
        output = redact(result.stdout + result.stderr)
        destination.write_text(output, encoding="utf-8")
        print(output, end="")
        if result.returncode:
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
