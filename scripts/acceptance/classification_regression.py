"""Run the opt-in Python-only classifier regression without touching the fixed S15 matrix."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend/tests"))

from real_model_classification_regression import main

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:  # noqa: BLE001 - never print provider or credential-bearing exception text
        print(json.dumps({"scope": "python-only-classification-regression", "status": "failed",
                          "errorType": type(error).__name__}))
        raise SystemExit(1) from None
