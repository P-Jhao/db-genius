"""Stable opt-in classifier entry point; execution is isolated from pytest."""

from real_model_classification_effects import main

if __name__ == "__main__":
    raise SystemExit(main())
