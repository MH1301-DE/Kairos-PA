from __future__ import annotations

import pytest

from kairos.metrics.custom_eval import InvalidExpression, evaluate_expression, extract_metric_refs


def test_extract_metric_refs_finds_all_names() -> None:
    refs = extract_metric_refs("hrv_5min * 0.5 + stress * 0.2 - sleep_hours")
    assert refs == {"hrv_5min", "stress", "sleep_hours"}


def test_extract_metric_refs_rejects_syntax_error() -> None:
    with pytest.raises(InvalidExpression):
        extract_metric_refs("hrv_5min * ")


def test_evaluate_expression_computes_arithmetic() -> None:
    result = evaluate_expression(
        "hrv_5min * 0.5 + stress * 0.2", {"hrv_5min": 60.0, "stress": 20.0}
    )
    assert result == pytest.approx(34.0)


def test_evaluate_expression_rejects_function_call() -> None:
    with pytest.raises(InvalidExpression):
        evaluate_expression("__import__('os')", {})


def test_evaluate_expression_rejects_unknown_name() -> None:
    with pytest.raises(InvalidExpression):
        evaluate_expression("unknown_metric + 1", {"hrv_5min": 60.0})


def test_evaluate_expression_rejects_lambda() -> None:
    with pytest.raises(InvalidExpression):
        evaluate_expression("(lambda: 1)()", {})


def test_evaluate_expression_rejects_non_numeric_result() -> None:
    with pytest.raises(InvalidExpression):
        evaluate_expression("hrv_5min > 50", {"hrv_5min": 60.0})
