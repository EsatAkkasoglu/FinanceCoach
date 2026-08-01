"""Quant tool-layer tests — envelope shape, error paths, payload size.

No network: the price-history loader is monkeypatched with a synthetic path, and
the portfolio tools exploit the same "no user in context → list_holdings returns
[]" route that ``test_calc_tools.py`` uses.

The payload-size test is the load-bearing one. ``main._summarize_tool_output``
truncates tool output at 4000 characters and ``parseToolResult.ts`` silently
degrades a truncated envelope to plain text — so an oversized curve doesn't
error, it just quietly stops rendering as a card.
"""
from __future__ import annotations

import json

import numpy as np
import pytest

from app.tools.quant_tools import (
    _params_for,
    backtest_strategy,
    compute_beta_alpha,
    compute_value_at_risk,
    implied_volatility,
    optimize_portfolio,
    price_option,
    walk_forward_backtest,
)

SSE_CAP = 4000


def _synthetic_path(n: int = 1200):
    t = np.arange(n, dtype=float)
    closes = 100.0 * np.exp(0.0004 * t + 0.06 * np.sin(t / 11.0))
    dates = [f"2020-{(i % 12) + 1:02d}-{(i % 28) + 1:02d}" for i in range(n)]
    return dates, closes, closes * 1.01, closes * 0.99


@pytest.fixture
def offline_prices(monkeypatch):
    """Replace the price loader so no test touches yfinance."""
    monkeypatch.setattr(
        "app.tools.quant_tools._load_path", lambda ticker, days: _synthetic_path()
    )


# ── argument mapping ─────────────────────────────────────────────────────────


def test_params_map_onto_each_strategys_own_names():
    assert _params_for("sma_cross", 10, 30, 0) == {"fast": 10, "slow": 30}
    assert _params_for("tsmom", 0, 0, 90) == {"lookback": 90}
    assert _params_for("rsi_reversion", 0, 0, 21) == {"period": 21}
    assert _params_for("buy_hold", 10, 30, 90) == {}


def test_zero_means_use_the_strategy_default():
    assert _params_for("sma_cross", 0, 0, 0) == {}


# ── backtest tool ────────────────────────────────────────────────────────────


def test_backtest_returns_an_equity_curve_envelope(offline_prices):
    env = backtest_strategy.invoke({"ticker": "TEST", "strategy": "sma_cross"})
    assert env["ok"] is True
    assert env["ui_type"] == "equity_curve"
    assert env["formatted_value"] and "buy & hold" in env["formatted_value"]

    data = env["data"]
    assert len(data["equity"]) == len(data["benchmark"]) == len(data["drawdown"])
    assert data["metrics"]["n_bars"] > 0
    assert data["start_date"] and data["end_date"]
    assert all(d <= 1e-9 for d in data["drawdown"])   # drawdown is never positive


def test_backtest_envelope_fits_under_the_sse_truncation_cap(offline_prices):
    """A 1200-bar backtest must still serialize under 4000 characters."""
    for strategy in ("sma_cross", "rsi_reversion", "tsmom", "buy_hold"):
        env = backtest_strategy.invoke({"ticker": "TEST", "strategy": strategy})
        size = len(json.dumps(env, ensure_ascii=False, default=str))
        assert size < SSE_CAP, f"{strategy} envelope is {size} chars"


def test_backtest_curve_is_downsampled_not_truncated(offline_prices):
    env = backtest_strategy.invoke({"ticker": "TEST", "strategy": "buy_hold"})
    data = env["data"]
    assert len(data["equity"]) <= 80
    # Both endpoints survive thinning, so the curve still spans the full window.
    assert data["equity"][0] > 0 and data["equity"][-1] > 0


def test_backtest_explanation_carries_the_honesty_caveats(offline_prices):
    env = backtest_strategy.invoke({"ticker": "TEST", "strategy": "sma_cross"})
    explanation = env["explanation"].lower()
    assert "no look-ahead" in explanation
    assert "cost drag" in explanation
    assert "not advice" in explanation


def test_backtest_rejects_an_unknown_strategy():
    env = backtest_strategy.invoke({"ticker": "AAPL", "strategy": "moon_phase"})
    assert env["ok"] is False
    assert "moon_phase" in env["error"]
    assert "sma_cross" in env["error"]      # the error lists the valid options


def test_backtest_requires_a_ticker():
    env = backtest_strategy.invoke({"ticker": "  ", "strategy": "sma_cross"})
    assert env["ok"] is False
    assert env["inputs_received"]["ticker"] == "  "


def test_backtest_reports_missing_history_instead_of_raising(monkeypatch):
    monkeypatch.setattr("app.tools.quant_tools._load_path", lambda ticker, days: None)
    env = backtest_strategy.invoke({"ticker": "NOPE", "strategy": "sma_cross"})
    assert env["ok"] is False
    assert "No usable price history" in env["error"]


def test_backtest_short_history_is_an_error_not_a_fabrication(monkeypatch):
    monkeypatch.setattr(
        "app.tools.quant_tools._load_path",
        lambda ticker, days: (["2024-01-01"] * 10, np.linspace(100, 110, 10), None, None),
    )
    env = backtest_strategy.invoke({"ticker": "TINY", "strategy": "sma_cross"})
    assert env["ok"] is False
    assert "at least" in env["error"]


# ── walk-forward tool ────────────────────────────────────────────────────────


def test_walk_forward_reports_out_of_sample_metrics(offline_prices):
    env = walk_forward_backtest.invoke({"ticker": "TEST", "strategy": "tsmom"})
    assert env["ok"] is True
    assert env["ui_type"] == "table"
    metrics = {r["metric"] for r in env["data"]["rows"]}
    assert "Deflated Sharpe" in metrics
    assert "Parameter sets tried" in metrics
    assert "out-of-sample" in env["explanation"].lower()
    assert len(json.dumps(env, default=str)) < SSE_CAP


def test_walk_forward_refuses_when_history_is_too_short(monkeypatch):
    dates, closes, highs, lows = _synthetic_path(80)
    monkeypatch.setattr(
        "app.tools.quant_tools._load_path", lambda t, d: (dates, closes, highs, lows)
    )
    env = walk_forward_backtest.invoke({"ticker": "TEST", "strategy": "sma_cross"})
    assert env["ok"] is False
    assert "out-of-sample" in env["error"]


# ── portfolio-backed tools degrade cleanly with no holdings ──────────────────


def test_value_at_risk_without_holdings_returns_a_readable_error():
    env = compute_value_at_risk.invoke({})
    assert env["ok"] is False
    assert "holdings" in env["error"].lower()


def test_optimize_requires_at_least_two_holdings():
    env = optimize_portfolio.invoke({"objective": "max_sharpe"})
    assert env["ok"] is False
    assert "two" in env["error"].lower()


def test_optimize_rejects_an_unknown_objective():
    env = optimize_portfolio.invoke({"objective": "vibes"})
    assert env["ok"] is False
    assert "max_sharpe" in env["error"]


def test_beta_alpha_reports_a_bad_benchmark(monkeypatch):
    monkeypatch.setattr("app.tools.quant_tools.load_close_series", lambda *a, **k: None)
    env = compute_beta_alpha.invoke({"ticker": "AAPL", "benchmark": "NOTREAL"})
    assert env["ok"] is False
    assert "NOTREAL" in env["error"]


# ── option calculators (pure) ────────────────────────────────────────────────


def test_price_option_matches_the_textbook_case():
    env = price_option.invoke({
        "spot": 100.0, "strike": 100.0, "days_to_expiry": 365.0,
        "volatility_pct": 20.0, "risk_free_pct": 5.0, "kind": "call",
    })
    assert env["ok"] is True
    assert env["ui_type"] == "table"
    assert env["raw_value"] == pytest.approx(10.4506, abs=1e-3)
    by_metric = {r["metric"]: r["value"] for r in env["data"]["rows"]}
    assert 0.5 < by_metric["Delta"] < 0.75
    assert by_metric["Theta (per day)"] < 0


def test_price_option_rejects_impossible_inputs():
    env = price_option.invoke({
        "spot": 0.0, "strike": 100.0, "days_to_expiry": 30.0, "volatility_pct": 50.0,
    })
    assert env["ok"] is False
    assert env["inputs_received"]["spot"] == 0.0


def test_price_option_rejects_a_bad_kind():
    env = price_option.invoke({
        "spot": 100.0, "strike": 100.0, "days_to_expiry": 30.0,
        "volatility_pct": 50.0, "kind": "straddle",
    })
    assert env["ok"] is False


def test_implied_volatility_round_trips_through_the_tool():
    priced = price_option.invoke({
        "spot": 100.0, "strike": 110.0, "days_to_expiry": 90.0,
        "volatility_pct": 45.0, "risk_free_pct": 2.0, "kind": "call",
    })
    env = implied_volatility.invoke({
        "option_price": priced["raw_value"], "spot": 100.0, "strike": 110.0,
        "days_to_expiry": 90.0, "risk_free_pct": 2.0, "kind": "call",
    })
    assert env["ok"] is True
    assert env["ui_type"] == "metric"
    assert env["raw_value"] == pytest.approx(45.0, abs=0.05)


def test_implied_volatility_refuses_an_arbitrageable_quote():
    env = implied_volatility.invoke({
        "option_price": 500.0, "spot": 100.0, "strike": 100.0, "days_to_expiry": 30.0,
    })
    assert env["ok"] is False
    assert "no-arbitrage" in env["error"]


# ── envelope contract ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "ui_type", ["equity_curve", "frontier", "heatmap", "table", "metric"]
)
def test_declared_ui_types_are_in_the_backend_literal(ui_type):
    """Every ui_type the quant layer emits must exist in the shared Literal —
    the frontend's TS union mirrors this list."""
    from typing import get_args

    from app.tools._calc_result import UiType

    assert ui_type in get_args(UiType)


def test_every_quant_envelope_is_json_serializable(offline_prices):
    envelopes = [
        backtest_strategy.invoke({"ticker": "TEST", "strategy": "macd"}),
        walk_forward_backtest.invoke({"ticker": "TEST", "strategy": "tsmom"}),
        price_option.invoke({
            "spot": 50.0, "strike": 55.0, "days_to_expiry": 45.0, "volatility_pct": 80.0,
        }),
        compute_value_at_risk.invoke({}),
        optimize_portfolio.invoke({}),
    ]
    for env in envelopes:
        json.dumps(env)   # raises on numpy scalars / non-serializable types
