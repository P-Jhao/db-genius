"""Acceptance judgement regressions; wrong facts must not appear successful."""

from __future__ import annotations

import os
from decimal import Decimal

import pytest
from real_model_cases import QueryOracle, fixed_cases
from real_model_database import DatabaseType, isolated_database
from real_model_oracles import database_rows_match, query_matches


def test_swapped_column_values_fail_but_reordered_column_display_passes() -> None:
    oracle = QueryOracle("", ((5, 50),), ("order_count", "total_amount"))
    assert query_matches(oracle, [{"total_amount": "50.00", "order_count": 5}])
    assert not query_matches(oracle, [{"total_amount": 5, "order_count": 50}])
    assert not query_matches(oracle, [{"order_count": 5, "wrong_name": 50}])


def test_explicit_order_by_is_checked() -> None:
    oracle = QueryOracle("", (("Ada", 30), ("Lin", 15)), ("customer_name", "total_amount"))
    assert query_matches(oracle, [{"customer_name": "Ada", "total_amount": 30},
                                  {"total_amount": 15, "customer_name": "Lin"}])
    assert not query_matches(oracle, [{"customer_name": "Lin", "total_amount": 15},
                                      {"customer_name": "Ada", "total_amount": 30}])


def test_unordered_results_preserve_duplicate_occurrences() -> None:
    oracle = QueryOracle("", ((1,), (1,), (2,)), ("id",), ordered=False)
    assert query_matches(oracle, [{"id": 2}, {"id": 1}, {"id": 1}])
    assert not query_matches(oracle, [{"id": 2}, {"id": 2}, {"id": 1}])
    assert not query_matches(oracle, [{"id": 2}, {"id": 1}])


def test_null_is_distinct_from_literal_text_false_and_zero() -> None:
    oracle = QueryOracle("", ((None, "<NULL>", 0, Decimal("57.5")),), ("empty", "text", "count", "amount"))
    assert query_matches(oracle, [{"empty": None, "text": "<NULL>", "count": 0, "amount": "57.5000000001"}])
    assert not query_matches(oracle, [{"empty": "<NULL>", "text": "<NULL>", "count": 0, "amount": "57.5"}])
    assert not query_matches(oracle, [{"empty": None, "text": "<NULL>", "count": False, "amount": "57.5"}])
    assert not query_matches(oracle, [{"empty": None, "text": "<NULL>", "count": 0, "amount": "NaN"}])


@pytest.mark.parametrize("db_type", ["postgresql", "mysql"])
def test_fixed_oracles_match_independent_real_database(db_type: DatabaseType) -> None:
    if os.environ.get("SQLCHAT_REAL_TARGET_CHECK") != "1":
        pytest.skip("Explicit dedicated PG/MySQL target verification is not enabled")
    with isolated_database(db_type, "py") as target:
        for case in fixed_cases():
            if case.uses_file:
                continue
            for turn in case.oracles:
                for oracle in turn:
                    assert database_rows_match(oracle, target.rows(oracle.statement)), case.code
        before = target.fingerprint()
        with isolated_database(db_type, "java") as equivalent:
            assert equivalent.fingerprint() == before
        with target.engine.begin() as connection:
            connection.exec_driver_sql("UPDATE orders SET note='<NULL>' WHERE id=1")
        assert target.fingerprint() != before
        with target.engine.begin() as connection:
            connection.exec_driver_sql("UPDATE orders SET note=NULL WHERE id=1")
        assert target.fingerprint() == before
        with isolated_database(db_type, "test", comparison_target=True) as different:
            assert different.fingerprint() != before
