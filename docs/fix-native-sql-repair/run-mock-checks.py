"""No target-instance access: driver objects and local controlled HTTP only."""

import subprocess
import sys
from pathlib import Path

PHASE = Path(__file__).resolve().parent
BACKEND = PHASE.parents[1] / "backend"


def main() -> int:
    commands = {
        "mock": ["pytest", "-q", "tests/test_native_sql_repair_policy.py",
                 "tests/test_native_sql_repair_graph.py", "tests/test_sql_repair.py"],
        "ruff": ["ruff", "check", "app", "tests"],
        "mypy-app": ["mypy", "app"],
        "mypy-owned-strict": ["mypy", "--strict", "app/agent/sql_errors.py"],
    }
    for name, arguments in commands.items():
        destination = PHASE / f"{name}.log"
        if destination.exists():
            raise FileExistsError("Existing gate evidence cannot be overwritten: " + destination.name)
        result = subprocess.run([sys.executable, "-m", *arguments], cwd=BACKEND,
                                capture_output=True, encoding="utf-8", errors="replace", check=False)
        output = result.stdout + result.stderr
        destination.write_text(output, encoding="utf-8")
        print(output, end="")
        if result.returncode:
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
