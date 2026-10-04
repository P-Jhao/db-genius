"""Run the unchanged supplemental matrix only after explicit source-guard acceptance."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend/tests"))

from real_model_supplemental_effects import main

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:  # noqa: BLE001 - never print credential-bearing diagnostic text
        print(json.dumps({"scope": "python-only-supplemental-fixed-effects", "status": "failed",
                          "errorType": type(error).__name__}))
        raise SystemExit(1) from None
