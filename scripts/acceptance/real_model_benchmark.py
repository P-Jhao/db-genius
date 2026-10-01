"""Calibrate isolated APIs or run the fixed, credential-free S15 effect matrix."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend/tests"))

from real_model_runner import benchmark, calibrate, diagnose_java


def output_path(value: Path | None, mode: str) -> Path:
    directory = (ROOT / "docs/phase-15-real-model").resolve()
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    target = (value if value is not None else directory / f"{mode}-{timestamp}.json").resolve()
    if not target.is_relative_to(directory) or target.suffix != ".json":
        raise ValueError("Evidence output must be a JSON file inside docs/phase-15-real-model")
    if not target.parent.is_dir():
        raise FileNotFoundError("The evidence parent directory must already exist")
    if target.exists() or target.with_suffix(".jsonl").exists():
        raise FileExistsError("Keep prior evidence; choose a fresh output name")
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--calibrate", action="store_true", help="Actual auth/worker/PG/MySQL checks; zero model calls")
    modes.add_argument("--diagnose-java", action="store_true", help="Actual original aggregate/classification diagnostics")
    modes.add_argument("--benchmark", action="store_true", help="Both variants, both databases, ten cases, three repetitions")
    parser.add_argument("--accepted-python-image", help="Exact accepted rebuilt deployment image sha256 required by benchmark")
    parser.add_argument("--diagnostic-case", choices=("aggregate", "ambiguity"), help="Limit original diagnostic only")
    parser.add_argument("--output", type=Path, help="Fresh numeric evidence file under docs/phase-15-real-model")
    options = parser.parse_args()
    mode = "calibration" if options.calibrate else "java-diagnostic" if options.diagnose_java else "benchmark"
    target: Path | None = None
    try:
        target = output_path(options.output, mode)
        if options.benchmark and options.accepted_python_image is None:
            raise ValueError("An accepted rebuilt Python image SHA is required")
        if options.diagnostic_case is not None and not options.diagnose_java:
            raise ValueError("A diagnostic case filter requires --diagnose-java")

        def persist(row: dict[str, object]) -> None:
            if target is None:
                raise RuntimeError("Evidence destination has not been selected")
            with target.with_suffix(".jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
            safe = {key: row.get(key) for key in ("case", "database", "repetition", "variant", "status", "errorType")}
            print(json.dumps(safe, ensure_ascii=False), flush=True)

        if options.calibrate:
            report = calibrate()
        elif options.diagnose_java:
            report = diagnose_java(persist, options.diagnostic_case)
        else:
            report = benchmark(options.accepted_python_image, persist)
        with target.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
        print(json.dumps({"mode": mode, "status": report["status"], "evidence": str(target)}, ensure_ascii=False))
        return 0 if report["status"] in {"passed", "diagnostic"} else 1
    except Exception as error:  # noqa: BLE001 - keep all credential-bearing exception messages private
        print(json.dumps({"mode": mode, "status": "failed", "errorType": type(error).__name__,
                          "partialEvidence": str(target.with_suffix(".jsonl")) if target is not None else None}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
