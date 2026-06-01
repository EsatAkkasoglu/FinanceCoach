"""Deterministic unit tests for the calc tool layer.

No network: covers the TVM calculators, pure-series risk math, the graceful
error path, and the empty-portfolio case (list_holdings returns [] with no
user in context). Portfolio analytics that price live holdings are exercised
end-to-end, not here.
"""
from __future__ import annotations

import numpy as np

from app.tools.calc_tools import (
    _metrics_from_returns,
    analyze_portfolio_risk,
    compute_portfolio_summary,
    compute_return_metrics,
    correlation_matrix,
    future_value,
    goal_required_contribution,
)


def test_future_value_known_compounding():
    r = future_value.invoke(
        {"monthly_contribution": 5000, "annual_rate_pct": 8, "years": 30, "currency": "TRY"}
    )
    assert r["ok"] is True
    assert abs(r["raw_value"] - 7451797.24) < 1.0  # numpy-financial FV, exact
    assert r["ui_type"] == "metric"
    assert r["formatted_value"] and "₺" in r["formatted_value"]  # localized in Python
    assert r["data"]["total_contributed"] == 1800000.0


def test_future_value_zero_rate_is_plain_sum():
    r = future_value.invoke({"monthly_contribution": 1000, "annual_rate_pct": 0, "years": 10})
    assert r["ok"] is True
    assert abs(r["raw_value"] - 120000.0) < 1e-6


def test_goal_required_zero_rate():
    r = goal_required_contribution.invoke(
        {"target_amount": 100000, "months": 12, "annual_rate_pct": 0, "currency": "USD"}
    )
    assert r["ok"] is True
    assert abs(r["raw_value"] - 8333.33) < 0.01
    assert "$" in r["formatted_value"]


def test_goal_required_compounding_beats_linear():
    # With a positive return, the required monthly contribution is LESS than
    # the plain linear split (compounding does some of the work).
    r = goal_required_contribution.invoke(
        {"target_amount": 100000, "months": 24, "annual_rate_pct": 10}
    )
    assert r["ok"] is True
    assert 0 < r["raw_value"] < 100000 / 24


def test_goal_already_reached():
    r = goal_required_contribution.invoke(
        {"target_amount": 100000, "months": 12, "current_amount": 100000}
    )
    assert r["ok"] is True
    assert r["raw_value"] == 0.0
    assert r["data"]["already_reached"] is True


def test_error_negative_months_does_not_raise():
    r = goal_required_contribution.invoke({"target_amount": 100000, "months": -5})
    assert r["ok"] is False
    assert "error" in r
    assert r["inputs_received"]["months"] == -5


def test_error_zero_years():
    r = future_value.invoke({"monthly_contribution": 100, "annual_rate_pct": 8, "years": 0})
    assert r["ok"] is False
    assert "error" in r


def test_error_absurd_rate():
    r = future_value.invoke({"monthly_contribution": 100, "annual_rate_pct": 8000, "years": 5})
    assert r["ok"] is False


def test_return_metrics_structure_and_drawdown():
    r = compute_return_metrics.invoke({"prices": [100, 110, 121], "periods_per_year": 12})
    assert r["ok"] is True
    assert r["ui_type"] == "table"
    metrics = {row["metric"]: row["value"] for row in r["data"]["rows"]}
    assert "Sharpe ratio" in metrics
    assert metrics["Max drawdown"] == 0.0  # monotonic rise → no drawdown


def test_return_metrics_insufficient_data():
    r = compute_return_metrics.invoke({"prices": [100]})
    assert r["ok"] is False


def test_correlation_perfectly_correlated():
    r = correlation_matrix.invoke({"series": {"a": [1, 2, 3, 4], "b": [2, 4, 6, 8]}})
    assert r["ok"] is True
    assert abs(r["raw_value"] - 1.0) < 1e-6  # identical return shape → corr 1.0


def test_correlation_needs_two_series():
    r = correlation_matrix.invoke({"series": {"a": [1, 2, 3]}})
    assert r["ok"] is False


def test_portfolio_summary_empty_no_user():
    # No user in context → list_holdings returns [] → graceful empty summary,
    # no network calls.
    r = compute_portfolio_summary.invoke({})
    assert r["ok"] is True
    assert r["ui_type"] == "none"
    assert r["data"]["positions"] == []


def test_metrics_from_returns_constant_series():
    m = _metrics_from_returns(np.array([0.1, 0.1, 0.1]), ppy=12, rf=0.0)
    assert m["ann_vol"] < 1e-9  # ~0 up to float dust
    assert m["sharpe"] == 0.0  # epsilon guard → 0, not a 1e16 artifact
    assert m["max_dd"] == 0.0


def test_metrics_from_returns_has_drawdown():
    m = _metrics_from_returns(np.array([0.1, -0.2, 0.05]), ppy=12, rf=0.0)
    assert m["ann_vol"] > 0.0
    assert m["max_dd"] < 0.0


def test_analyze_portfolio_risk_empty_no_user():
    # No user → no holdings → graceful empty result, no network.
    r = analyze_portfolio_risk.invoke({})
    assert r["ok"] is True
    assert r["ui_type"] == "none"
