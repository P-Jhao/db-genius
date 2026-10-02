"""Run the existing local regressions or reproduce all checks without overwriting evidence."""

import os
import subprocess
import sys
from pathlib import Path

PHASE = Path(__file__).resolve().parent
BACKEND = PHASE.parents[1] / "backend"
TESTS = [
    "tests/test_ocr_boundaries.py", "tests/test_model_parameters.py",
    "tests/test_chat_graph.py", "tests/test_workflow_graph.py",
    "tests/test_compare_graph.py", "tests/test_trial_graph_targets.py",
    "tests/test_chat_abort.py", "tests/test_chat_abort_api.py",
]


def main() -> int:
    if sys.argv[1:] not in ([], ["--all"], ["--integration"]):
        raise ValueError("Supported flags: --all or --integration")
    commands = {"regression": ["pytest", "-q", "-ra", *TESTS]}
    if sys.argv[1:] == ["--all"]:
        commands.update({"ruff": ["ruff", "check", "app", "tests"],
                         "mypy-strict": ["mypy", "--strict", "app"]})
    if sys.argv[1:] == ["--integration"]:
        commands = {
            "integration-regression": ["pytest", "-q", "-ra", "tests/test_ocr_boundaries.py",
                                       "tests/test_chat_graph.py", "tests/test_chat_abort.py"],
            "integration-ruff": ["ruff", "check", "app", "tests"],
            "integration-mypy-strict": ["mypy", "--strict", "app"],
        }
    suffix = os.environ.get("TYPE_EVIDENCE_SUFFIX", "")
    if any(not (character.isalnum() or character in "-_") for character in suffix):
        raise ValueError("Invalid evidence suffix")
    for name, arguments in commands.items():
        if suffix:
            name += "-" + suffix
        destination = PHASE / (name + ".log")
        if destination.exists():
            raise FileExistsError("Cannot overwrite evidence: " + destination.name)
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
