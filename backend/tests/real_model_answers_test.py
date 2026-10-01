"""Final summary must preserve result relations and ordering, or require review."""

from __future__ import annotations

import json
from typing import cast

from real_model_answers import answer_review, observed_results, redact_answer
from real_model_cases import EffectCase, fixed_cases
from real_model_database import TargetSnapshot
from real_model_evidence import judge_turn
from real_model_evidence_test import IndependentTarget


def case(code: str) -> EffectCase:
    return next(value for value in fixed_cases() if value.code == code)


def test_correct_tool_output_with_wrong_free_form_summary_requires_review() -> None:
    selected = case("aggregate")
    answer = "共有 5 单，金额合计 500。"
    events: list[dict[str, object]] = [
        {"type": "conversation", "content": 7},
        {"type": "step", "content": 'executeSql: {"success":true,"data":[{"order_count":5,"total_amount":50}]}'},
        {"type": "summary", "content": answer}, {"type": "done"},
    ]
    history: list[dict[str, object]] = [{"role": "user", "content": selected.questions[0]},
                                       {"role": "assistant", "type": "summary", "content": answer}]
    value = judge_turn(selected, 0, events, history, cast(TargetSnapshot, IndependentTarget()), "unchanged")
    assert value["status"] == "review-required" and value["errorType"] == "GroundedAnswerReviewRequired"
    assert cast(dict[str, bool], value["checks"])["queryResults"]
    review = cast(dict[str, object], value["answerReview"])
    assert review["finalAnswer"] == answer and review["expectedResults"] == [[{"order_count": 5, "total_amount": 50}]]
    assert review["executedResults"] == [{"data": [{"order_count": 5, "total_amount": 50}],
                                          "rowCount": 1, "truncated": False, "unexpectedColumnCount": 0}]


def test_wrong_structured_summary_fails_even_with_correct_counts_in_other_cells() -> None:
    selected = case("aggregate")
    assert answer_review(selected, 0, '{"order_count":5,"total_amount":50}')["status"] == "validated"
    assert answer_review(selected, 0, '{"order_count":5,"total_amount":500}')["status"] == "failed"
    assert answer_review(selected, 0, '{"order_count":50,"total_amount":5}')["status"] == "failed"
    assert answer_review(selected, 0, '{"订单数":5,"金额":50}')["status"] == "review-required"
    duplicate = {"results": [{"columns": ["order_count", "order_count", "total_amount"], "rows": [[5, 5, 50]]}]}
    assert answer_review(selected, 0, json.dumps(duplicate))["status"] == "failed"


def test_entity_amount_relation_and_requested_order_are_checked() -> None:
    selected = case("followup")
    correct = [{"customer_name": "Ada", "total_amount": 30}, {"customer_name": "Lin", "total_amount": 15}]
    assert answer_review(selected, 1, json.dumps(correct))["status"] == "validated"
    assert answer_review(selected, 1, json.dumps(list(reversed(correct))))["status"] == "failed"
    wrong = [{"customer_name": "Ada", "total_amount": 15}, {"customer_name": "Lin", "total_amount": 30}]
    assert answer_review(selected, 1, json.dumps(wrong))["status"] == "failed"
    table = "| customer_name | total_amount |\n|---|---|\n|Ada|30|\n|Lin|15|"
    assert answer_review(selected, 1, table)["status"] == "validated"
    assert answer_review(selected, 1, table.replace("|Ada|30|", "|Ada|15|"))["status"] == "failed"
    assert answer_review(selected, 1, "Ada 金额 500。\n\n" + table)["status"] == "review-required"


def test_reasoning_prompt_and_secrets_are_omitted_before_clipping_or_persisting() -> None:
    selected = case("aggregate")
    secret = "synthetic-auth-token"
    review = answer_review(selected, 0, 'x' * 8190 + secret + selected.questions[0])
    redact_answer(review, (secret,), selected.questions)
    assert "synthetic-auth-token" not in str(review) and "synthetic-auth" not in str(review["finalAnswer"])
    assert selected.questions[0] not in str(review) and review["answerTruncated"] is True
    review = answer_review(selected, 0, '<think>private synthetic reasoning</think>')
    redact_answer(review, (), selected.questions)
    assert review["finalAnswer"] is None and "private synthetic reasoning" not in str(review)
    review = answer_review(selected, 0, json.dumps({"order_count": 5, "total_amount": secret}))
    redact_answer(review, (secret,), selected.questions)
    assert secret not in str(review) and "[omitted]" in str(review)


def test_only_fixed_synthetic_result_columns_and_entities_enter_report() -> None:
    selected = case("aggregate")
    observed = observed_results(selected.oracles[0], [{"order_count": 5, "total_amount": "500.00",
                                                     "secret_column_name": "arbitrary private business text"}])
    assert observed["data"] == [{"order_count": 5, "total_amount": "500.00"}]
    assert observed["unexpectedColumnCount"] == 1 and "private" not in str(observed)
    observed = observed_results(selected.oracles[0], [{"order_count": 5, "total_amount": "private data"}])
    assert "private data" not in str(observed) and "unexpectedTextOrType" in str(observed)
