"""Opt-in Python-only original fixed cases, with independently observed import structure."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from real_model_affected_effects import _group
from real_model_cases import REPETITIONS, EffectCase, fixed_cases
from real_model_regression_support import SOURCE_FILES, options, report_run
from real_model_supplemental_import_group import import_group

if TYPE_CHECKING:
    from real_model_api import Variant
    from real_model_database import DatabaseType
    from real_model_relay import RealProviderRelay

SCOPE = "python-only-supplemental-fixed-effects"
SUPPLEMENTAL_CODES = frozenset({"file_import", "reject", "followup"})
ENTRY_SOURCES = frozenset({
    "backend/tests/real_model_supplemental_effects.py",
    "backend/tests/real_model_import_structure.py",
    "backend/tests/real_model_supplemental_import_group.py",
    "scripts/acceptance/supplemental_effects.py",
})


def selected_cases() -> tuple[EffectCase, ...]:
    cases = tuple(case for case in fixed_cases() if case.code in SUPPLEMENTAL_CODES)
    if REPETITIONS != 3 or len(cases) != 3 or {case.code for case in cases} != SUPPLEMENTAL_CODES:
        raise ValueError("Supplemental effects require the unchanged three cases and three repetitions")
    return cases


def main() -> int:
    args = options(__doc__, affected=True)
    if not args.python_only:
        raise ValueError("Supplemental effects require --python-only")
    if not ENTRY_SOURCES.issubset(SOURCE_FILES):
        raise RuntimeError("Supplemental entry sources are not included in the accepted source guard")
    cases = selected_cases()
    variants: tuple[Variant, ...] = ("python",)
    databases: tuple[DatabaseType, ...] = ("postgresql", "mysql")

    def execute(relay: RealProviderRelay, persist: Callable[[dict[str, object]], None]) -> None:
        for database in databases:
            for repetition in range(1, REPETITIONS + 1):
                for case in cases:
                    rows = import_group(case, repetition, database, relay, SCOPE) if case.code == "file_import" else (
                        _group(case, repetition, database, variants, relay, SCOPE))
                    for row in rows:
                        persist(row)
                    if any(row.get("cleanupIncomplete") is True for row in rows):
                        raise RuntimeError("Stop after incomplete fixture cleanup")

    return report_run(args, SCOPE, variants, len(cases) * len(databases) * REPETITIONS, execute)


if __name__ == "__main__":
    raise SystemExit(main())
