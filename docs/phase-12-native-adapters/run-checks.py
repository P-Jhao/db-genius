"""Run a gate while removing ignored runtime secrets before any output/log write."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BACKEND = REPO / "backend"
sys.path.insert(0, str(BACKEND))
from app.adapters.diagnostics import sanitize_diagnostic
from app.adapters.types import DbConnectionConfig


def redact(output: str) -> str:
    for name, value in os.environ.items():
        if value and any(part in name.upper() for part in ("PASSWORD", "TOKEN", "SECRET", "API_KEY")):
            output = sanitize_diagnostic(output, DbConnectionConfig("oracle", "localhost", 1521, "test", "test", value))
    output = sanitize_diagnostic(output, DbConnectionConfig("oracle", "localhost", 1521, "test", "test", ""))
    for variable in ("SQLCHAT_SQLSERVER_RUNTIME", "SQLCHAT_ORACLE_RUNTIME"):
        runtime = os.environ.get(variable)
        if runtime is None:
            continue
        for line in Path(runtime).read_text(encoding="utf-8-sig").splitlines():
            key, separator, value = line.partition("=")
            if separator and "PASSWORD" in key.upper():
                password = value.strip().strip('"').strip("'")
                config = DbConnectionConfig("oracle", "localhost", 1521, "test", "test", password)
                output = sanitize_diagnostic(output, config)
    return output


def main() -> int:
    if len(sys.argv) < 2:
        raise ValueError("Pass pytest test paths or -mypy or -ruff")
    if sys.argv[1] == "-mypy":
        command = [sys.executable, "-m", "mypy", "app"]
        name = "mypy"
    elif sys.argv[1] == "-ruff":
        command = [sys.executable, "-m", "ruff", "check", "app", "tests"]
        name = "ruff"
    else:
        command = [sys.executable, "-m", "pytest", *sys.argv[1:], "-q"]
        name = os.environ.get("NATIVE_GATE_NAME", "pytest")
    suffix = os.environ.get("NATIVE_EVIDENCE_SUFFIX")
    if suffix is not None:
        if not suffix or len(suffix) > 64 or any(not (char.isalnum() or char in "-_") for char in suffix):
            raise ValueError("Evidence suffix must be 1-64 letters/digits/hyphens/underscores")
        name += "-" + suffix
    destination = Path(__file__).parent / f"{name}.log"
    if destination.exists():
        raise FileExistsError(f"Gate evidence already exists: {destination.name}")
    result = subprocess.run(command, cwd=BACKEND, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    output = redact(result.stdout + result.stderr)
    destination.write_text(output, encoding="utf-8")
    print(output, end="")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
