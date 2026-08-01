"""Backtest engine tests — all pure, no network.

The important ones are not "does it produce a number" but the three structural
guarantees a backtest is worthless without: causal alignment (no look-ahead),
exact cost accounting, and refusing to invent out-of-sample folds it doesn't
have the history for.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from app.quant.backtest import (
    trial_variance,
    PARAM_GRIDS,
    Costs,
    align_positions,
    build_positions,
    macd_series,
    rsi_series,
    run_backtest,
    sma_series,
    summarize,
    walk_forward,
)
from app.quant.data import to_returns
from app.tools.crypto_short_term import macd as macd_scalar
from app.tools.crypto_short_term import rsi as rsi_scalar

ZERO = Costs(fee_bps=0.0, slippage_bps=0.0, funding_bps_per_bar=0.0)


def _wave(n: int = 300, amp: float = 0.05, drift: float = 0.0003) -> np.ndarray:
    """Deterministic oscillating price path — no RNG, so tests never flake."""
    t = np.arange(n, dtype=float)
    return 100.0 * np.exp(drift * t + amp * np.sin(t / 9.0))


# ── indicator series agree with the live scalar helpers ──────────────────────


def test_rsi_series_last_matches_scalar_helper():
    """rsi_series must not drift from crypto_short_term.rsi — same Wilder math."""
    v = _wave(120)
    for period in (7, 14, 21):
        expected = rsi_scalar([float(x) for x in v], period)
        got = rsi_series(v, period)[-1]
        assert expected is not None
        assert got == pytest.approx(expected, abs=1e-9)


def test_macd_series_last_matches_scalar_helper():
    v = _wave(200)
    line, sig = macd_series(v, 12, 26, 9)
    expected = macd_scalar([float(x) for x in v], 12, 26, 9)
    assert expected is not None
    assert line[-1] == pytest.approx(expected[0], abs=1e-9)
    assert sig[-1] == pytest.approx(expected[1], abs=1e-9)


def test_sma_series_warmup_is_nan_then_exact():
    v = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    s = sma_series(v, 3)
    assert np.isnan(s[0]) and np.isnan(s[1])
    assert s[2] == pytest.approx(2.0)
    assert s[4] == pytest.approx(4.0)


# ── the look-ahead guard ─────────────────────────────────────────────────────


def test_align_positions_drops_the_final_target():
    p = np.array([0.0, 1.0, 1.0, 0.0, 1.0])
    assert align_positions(p).tolist() == [0.0, 1.0, 1.0, 0.0]


def test_final_bar_signal_is_structurally_unreachable():
    """Changing the LAST target must not change any realised return.

    The last bar's signal has no subsequent bar to trade into. If it ever
    influenced the result, the engine would be peeking at the future.
    """
    closes = np.array([100.0, 110.0, 99.0, 108.9, 98.01])
    a = run_backtest(closes, np.array([1.0, 1.0, 1.0, 1.0, 1.0]), costs=ZERO)
    b = run_backtest(closes, np.array([1.0, 1.0, 1.0, 1.0, 0.0]), costs=ZERO)
    assert np.allclose(a.bar_returns, b.bar_returns)


def test_position_earns_the_return_of_the_following_bar():
    """target[t] must earn the t → t+1 move, not the t-1 → t move."""
    closes = np.array([100.0, 110.0, 99.0])       # returns: +10%, -10%
    res = run_backtest(closes, np.array([1.0, 0.0, 0.0]), costs=ZERO)
    # Long over the first move only → +10%, then flat through the -10%.
    assert res.bar_returns.tolist() == pytest.approx([0.10, 0.0])
    assert res.net_total_return == pytest.approx(0.10)


# ── cost accounting ──────────────────────────────────────────────────────────


def test_costs_are_charged_per_position_change_and_reported_as_drag():
    closes = np.full(5, 100.0)                     # flat market: all P&L is cost
    costs = Costs(fee_bps=10.0, slippage_bps=5.0)  # 15 bps = 0.0015 per turn
    res = run_backtest(closes, np.array([1.0, 1.0, 1.0, 0.0, 0.0]), costs=costs)

    assert res.turnover == pytest.approx(2.0)      # one entry, one exit
    assert res.n_trades == 2
    assert res.bar_returns.tolist() == pytest.approx([-0.0015, 0.0, 0.0, -0.0015])
    assert res.gross_total_return == pytest.approx(0.0, abs=1e-12)
    assert res.cost_drag == pytest.approx(0.0 - res.net_total_return)


def test_funding_is_charged_on_held_exposure_only():
    closes = np.full(4, 100.0)
    costs = Costs(fee_bps=0.0, slippage_bps=0.0, funding_bps_per_bar=1.0)  # 1bp/bar
    res = run_backtest(closes, np.array([1.0, 1.0, 0.0, 0.0]), costs=costs)
    # Held on bars 0 and 1 of the aligned series, flat on bar 2.
    assert res.bar_returns.tolist() == pytest.approx([-0.0001, -0.0001, 0.0])


def test_equity_curve_is_the_compounded_return_series():
    closes = _wave(120)
    raw, warmup = build_positions("sma_cross", closes, params={"fast": 5, "slow": 10})
    res = run_backtest(closes, raw, costs=Costs(), warmup=warmup)
    assert res.equity[-1] == pytest.approx(float(np.prod(1.0 + res.bar_returns)))
    assert res.net_total_return == pytest.approx(res.equity[-1] - 1.0)
    assert (res.drawdown <= 1e-12).all()


def test_zero_cost_buy_hold_equals_the_benchmark():
    closes = _wave(150)
    raw, warmup = build_positions("buy_hold", closes)
    res = run_backtest(closes, raw, costs=ZERO, warmup=warmup)
    assert res.net_total_return == pytest.approx(
        float(np.prod(1.0 + to_returns(closes)) - 1.0)
    )
    assert np.allclose(res.bar_returns, res.benchmark_returns)


# ── warm-up handling ─────────────────────────────────────────────────────────


def test_warmup_bars_are_trimmed_not_counted_as_flat():
    closes = _wave(120)
    raw, warmup = build_positions("sma_cross", closes, params={"fast": 20, "slow": 50})
    assert warmup == 50
    assert (raw[:50] == 0.0).all()
    res = run_backtest(closes, raw, costs=Costs(), warmup=warmup)
    assert res.bar_returns.size == (closes.size - 1) - 50


def test_dates_stay_aligned_with_returns():
    closes = _wave(30)
    dates = [f"2024-01-{i + 1:02d}" for i in range(30)]
    raw, warmup = build_positions("buy_hold", closes)
    res = run_backtest(closes, raw, costs=Costs(), warmup=warmup, dates=dates)
    assert len(res.dates) == res.bar_returns.size
    assert res.dates[0] == "2024-01-02"   # first return ends on the second bar


# ── strategies ───────────────────────────────────────────────────────────────


def test_every_registered_strategy_runs_and_stays_in_bounds():
    closes = _wave(400)
    highs, lows = closes * 1.01, closes * 0.99
    for name in PARAM_GRIDS:
        raw, warmup = build_positions(name, closes, highs, lows)
        assert raw.size == closes.size
        assert set(np.unique(raw)).issubset({0.0, 1.0}), name
        res = run_backtest(closes, raw, costs=Costs(), warmup=warmup)
        assert np.all(np.isfinite(res.bar_returns)), name


def test_allow_short_maps_the_flat_leg_to_minus_one():
    closes = _wave(300)
    raw, _ = build_positions("sma_cross", closes, allow_short=True)
    assert set(np.unique(raw)).issubset({-1.0, 0.0, 1.0})
    assert (raw == -1.0).any()


def test_unknown_strategy_raises_keyerror():
    with pytest.raises(KeyError):
        build_positions("does_not_exist", _wave(50))


def test_donchian_channel_excludes_the_current_bar():
    # Monotonic ramp: every close is a new high, so a channel that included the
    # current bar could never signal a breakout.
    closes = np.arange(1, 61, dtype=float)
    raw, warmup = build_positions("donchian", closes, closes, closes, {"lookback": 10})
    assert warmup == 10
    assert (raw[10:] == 1.0).all()


# ── summary ──────────────────────────────────────────────────────────────────


def test_summarize_is_json_safe_and_annualizes_consistently():
    closes = _wave(400)
    raw, warmup = build_positions("sma_cross", closes)
    res = run_backtest(closes, raw, costs=Costs(), warmup=warmup)
    s = summarize(res, ppy=252.0, n_trials=9)

    for k, v in s.items():
        assert v is None or isinstance(v, (int, float, str, bool)), f"{k} is not JSON-safe"
    assert s["n_trials"] == 9
    # Both are rounded to 4dp independently, so allow for that rounding gap.
    assert s["sharpe_annualized"] == pytest.approx(s["sharpe"] * math.sqrt(252.0), abs=1e-3)
    assert 0.0 <= s["win_rate"] <= 1.0
    assert s["max_drawdown_pct"] <= 0.0


def test_summarize_flags_insufficient_data_instead_of_guessing():
    res = run_backtest(np.array([100.0, 101.0]), np.array([1.0, 1.0]), costs=Costs())
    assert summarize(res, ppy=252.0)["insufficient_data"] is True


def test_more_trials_never_raises_the_deflated_sharpe():
    """DSR must get harder, not easier, as the parameter search widens."""
    closes = _wave(500)
    raw, warmup = build_positions("sma_cross", closes)
    res = run_backtest(closes, raw, costs=Costs(), warmup=warmup)
    few = summarize(res, ppy=252.0, n_trials=1)["dsr"]
    many = summarize(res, ppy=252.0, n_trials=64)["dsr"]
    if few is not None and many is not None:
        assert many <= few + 1e-9


# ── walk-forward ─────────────────────────────────────────────────────────────


def test_walk_forward_refuses_to_invent_folds_on_short_history():
    out = walk_forward(_wave(60), "sma_cross", ppy=252.0)
    assert out["ok"] is False
    assert "not enough history" in out["reason"]


def test_walk_forward_reports_out_of_sample_only():
    closes = _wave(900)
    out = walk_forward(closes, "tsmom", n_folds=4, embargo=5, ppy=252.0)
    assert out["ok"] is True
    assert out["n_folds"] >= 1
    assert out["n_trials"] == len(PARAM_GRIDS["tsmom"]["lookback"])
    assert out["oos_bars"] == sum(f["test_bars"] for f in out["folds"])
    assert out["embargo_bars"] == 5
    for fold in out["folds"]:
        assert fold["params"]["lookback"] in PARAM_GRIDS["tsmom"]["lookback"]


def test_walk_forward_test_blocks_do_not_overlap_training():
    """Every fold must train on strictly fewer bars than the next one sees."""
    out = walk_forward(_wave(1200), "sma_cross", n_folds=3, ppy=252.0)
    assert out["ok"] is True
    train_sizes = [f["train_bars"] for f in out["folds"]]
    assert train_sizes == sorted(train_sizes)
    assert len(set(train_sizes)) == len(train_sizes)  # expanding, never repeating


# ── Deflated Sharpe units (regression) ───────────────────────────────────────


def test_trial_variance_is_in_per_bar_units_not_annual():
    """The bug this pins: deflated_sharpe_ratio defaults variance_trials=1.0,
    which reads as unit variance of ANNUAL Sharpes. Fed the per-bar Sharpes this
    engine works in, it puts the benchmark at an annualised Sharpe of ~660 and
    pins every DSR at exactly 0.0 — a survivor gate that can never fire, and a
    false negative that looks like rigour."""
    ppy = 365.25 * 24 * 4                       # 15-minute bars
    per_bar = [0.01, 0.02, 0.015, -0.005, 0.03]
    var = trial_variance(per_bar, ppy)
    assert var == pytest.approx(float(np.var(np.asarray(per_bar), ddof=1)))
    assert var < 0.01                            # per-bar scale, nowhere near 1.0


def test_trial_variance_falls_back_in_per_bar_units():
    ppy = 365.25 * 24 * 4
    fallback = trial_variance([], ppy)
    assert fallback == pytest.approx((0.5 / math.sqrt(ppy)) ** 2)
    assert 0.0 < fallback < 1e-4


def test_walk_forward_dsr_is_not_structurally_zero():
    """A strategy with a genuinely strong edge must produce a NON-zero deflated
    Sharpe. Before the units fix every cell returned exactly 0.0000."""
    n = 4000
    t = np.arange(n, dtype=float)
    # A clean, persistent trend: momentum should capture it and score well.
    closes = 100.0 * np.exp(0.0004 * t + 0.01 * np.sin(t / 50.0))
    out = walk_forward(
        closes, "tsmom", grid={"lookback": [24, 48]},
        n_folds=4, costs=ZERO, ppy=365.25 * 24 * 4,
    )
    assert out["ok"] is True
    assert out["oos_dsr"] is not None
    assert out["oos_dsr"] > 0.0
    assert out["trial_sharpe_variance"] < 0.01


def test_walk_forward_reports_a_fair_benchmark():
    closes = _wave(900)
    out = walk_forward(closes, "tsmom", n_folds=4, ppy=252.0)
    assert out["ok"] is True
    assert out["benchmark_return_pct"] is not None
    assert out["excess_vs_buy_hold_pct"] is not None
