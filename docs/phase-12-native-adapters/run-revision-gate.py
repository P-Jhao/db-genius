"""Only affected S13 API fixtures and Oracle CTE scopes; retain the first gate."""

import os
import subprocess
import sys
from pathlib import Path

PHASE = Path(__file__).resolve().parent
RUNTIME = Path("C:/Users/22126/Desktop/web/text2sql/sqlchat/.git/acceptance/s12-runtime")


def main() -> int:
    os.environ["SQLCHAT_SQLSERVER_RUNTIME"] = str(RUNTIME / "sqlserver.env")
    os.environ["SQLCHAT_ORACLE_RUNTIME"] = str(RUNTIME / "oracle-target.env")
    os.environ["NATIVE_GATE_NAME"] = "final-native-s13-revision"
    tests = ["tests/test_native_reads.py", "tests/test_oracle_read_catalog.py",
             "tests/test_oracle_sequences_real.py", "tests/test_native_api_real.py",
             "tests/test_native_adapters_safety.py", "-s"]
    for arguments in (tests, ["-ruff"], ["-mypy"]):
        result = subprocess.run([sys.executable, str(PHASE / "run-checks.py"), *arguments], check=False)
        if result.returncode:
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
