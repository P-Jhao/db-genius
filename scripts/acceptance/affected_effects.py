"""Run unchanged affected fixed cases under a clearly labeled fresh evidence scope."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend/tests"))

from real_model_affected_effects import main

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:  # noqa: BLE001 - keep credential-bearing exception text private
        print(json.dumps({"status": "failed", "errorType": type(error).__name__}))
        raise SystemExit(1) from None
