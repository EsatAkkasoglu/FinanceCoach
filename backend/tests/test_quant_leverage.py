"""Leverage and liquidation — pure, no network.

The property worth pinning is the one that refutes the common intuition:
leverage does NOT make a cost-losing rule profitable, because fees are charged
in bps of notional and therefore scale with the position. Sharpe is invariant;
only ruin risk changes. If that invariance ever broke, the engine would be
quietly telling users that leverage manufactures edge.
"""
from __future__ import annotations

import numpy as np
import pytest

from app.quant import backtest as bt

COSTS = bt.Costs(fee_bps=10.0, slippage_bps=5.0)
PPY = 35040.0  # 15-minute bars


def _path(seed: int = 5, n: int = 3000, drift: float = 0.00005, vol: float = 0.008):
    rng = np.random.default_rng(seed)
    r = rng.normal(drift, vol, n)
    c = 100.0 * np.cumprod(1.0 + r)
    wick = np.abs(rng.normal(0.0, vol / 2, n))
    return c, c * (1.0 + wick), c * (1.0 - wick)


def _scan(closes, highs, lows, params=None, **kw):
    raw, warmup = bt.build_positions(
        "sma_cross", closes, highs, lows, params or {"fast": 20, "slow": 100}, allow_short=True
    )
    return bt.leverage_scan(
        closes, highs, lows, raw, costs=COSTS, ppy=PPY, warmup=warmup, **kw
    )


# ── the invariance that kills the "just lever it up" idea ────────────────────


def test_sharpe_is_identical_at_every_leverage_when_nothing_liquidates():
    """Mean and standard deviation both scale by L, so the ratio cannot move.

    This is the whole answer to "the edge is too small to cover fees, so use
    leverage": the after-cost Sharpe you are levering is the same number.
    """
    rows = [r for r in _scan(*_path(), leverages=(1.0, 2.0, 3.0)) if not r["liquidated"]]
    assert len(rows) == 3
    sharpes = {r["sharpe_ann"] for r in rows}
    assert len(sharpes) == 1, sharpes


def test_a_losing_rule_loses_proportionally_more_with_leverage():
    rows = _scan(*_path(), leverages=(1.0, 2.0, 4.0))
    returns = [r["net_return_pct"] for r in rows]
    assert returns[0] < 0, "fixture must be a losing rule for this test to mean anything"
    assert returns[1] < returns[0] and returns[2] < returns[1]


def test_leverage_cannot_flip_the_sign_of_the_expected_return():
    """No level of leverage turns a negative-expectancy rule positive."""
    rows = _scan(*_path(), leverages=(1.0, 5.0, 10.0, 20.0))
    assert rows[0]["net_return_pct"] < 0
    assert all(r["net_return_pct"] < 0 for r in rows)


def test_drawdown_deepens_monotonically_with_leverage():
    rows = _scan(*_path(seed=11), leverages=(1.0, 2.0, 5.0))
    dds = [r["max_drawdown_pct"] for r in rows]
    assert dds[0] >= dds[1] >= dds[2]


# ── funding scales with notional too ─────────────────────────────────────────


def test_funding_drag_also_scales_so_perp_carry_gets_worse_not_better():
    closes, highs, lows = _path()
    raw, warmup = bt.build_positions(
        "sma_cross", closes, highs, lows, {"fast": 20, "slow": 100}, allow_short=True
    )
    free = bt.leverage_scan(
        closes, highs, lows, raw, costs=COSTS, ppy=PPY, warmup=warmup, leverages=(5.0,)
    )[0]
    funded = bt.leverage_scan(
        closes, highs, lows, raw,
        costs=bt.Costs(fee_bps=10.0, slippage_bps=5.0, funding_bps_per_bar=1.0),
        ppy=PPY, warmup=warmup, leverages=(5.0,),
    )[0]
    assert funded["net_return_pct"] < free["net_return_pct"]


# ── liquidation ──────────────────────────────────────────────────────────────


def test_an_adverse_wick_liquidates_a_long_even_when_the_bar_closes_higher():
    """The bar that kills a levered position is a wick, not a close.

    A close-to-close engine would report this bar as a small GAIN. At 20x a 6%
    dip inside the bar is already a margin call, and pretending otherwise is the
    single most flattering error a leveraged backtest can make.
    """
    n = 300
    closes = np.linspace(100.0, 130.0, n)          # steady climb → long the whole way
    highs = closes * 1.001
    lows = closes * 0.999
    lows[250] = closes[249] * 0.94                 # −6% wick, then closes up

    raw, warmup = bt.build_positions(
        "sma_cross", closes, highs, lows, {"fast": 5, "slow": 20}, allow_short=False
    )
    rows = bt.leverage_scan(
        closes, highs, lows, raw, costs=COSTS, ppy=PPY, warmup=warmup, leverages=(2.0, 20.0)
    )
    assert rows[0]["liquidated"] is False          # 2x survives a 6% dip
    assert rows[1]["liquidated"] is True           # 20x does not
    assert rows[1]["net_return_pct"] == pytest.approx(-100.0, abs=1e-6)


def test_a_short_is_liquidated_by_an_upward_wick():
    n = 300
    closes = np.linspace(130.0, 100.0, n)          # steady fall → short the whole way
    highs = closes * 1.001
    lows = closes * 0.999
    highs[250] = closes[249] * 1.08                # +8% spike against the short

    raw, warmup = bt.build_positions(
        "sma_cross", closes, highs, lows, {"fast": 5, "slow": 20}, allow_short=True
    )
    rows = bt.leverage_scan(
        closes, highs, lows, raw, costs=COSTS, ppy=PPY, warmup=warmup, leverages=(20.0,)
    )
    assert rows[0]["liquidated"] is True
    assert rows[0]["bars_survived"] < raw.size


def test_a_flat_position_is_never_liquidated():
    """Being out of the market cannot produce a margin call at any leverage."""
    n = 300
    closes = np.linspace(100.0, 100.0, n)
    closes[200:] = 50.0                            # a violent move while flat
    raw = np.zeros(n)
    rows = bt.leverage_scan(
        closes, closes * 1.2, closes * 0.5, raw, costs=COSTS, ppy=PPY, leverages=(100.0,)
    )
    assert rows[0]["liquidated"] is False


def test_sharpe_is_withheld_once_a_path_has_been_liquidated():
    """A Sharpe computed across a wipeout is meaningless — None is the honest
    answer, not a number a caller might rank on."""
    n = 300
    closes = np.linspace(100.0, 130.0, n)
    highs, lows = closes * 1.001, closes * 0.999
    lows[250] = closes[249] * 0.90
    raw, warmup = bt.build_positions(
        "sma_cross", closes, highs, lows, {"fast": 5, "slow": 20}, allow_short=False
    )
    row = bt.leverage_scan(
        closes, highs, lows, raw, costs=COSTS, ppy=PPY, warmup=warmup, leverages=(20.0,)
    )[0]
    assert row["liquidated"] is True
    assert row["sharpe_ann"] is None


def test_compounded_ruin_is_reported_even_without_a_margin_call():
    """A levered path can decay to zero without any single bar breaching margin.
    Reporting only `liquidated` would let that read as a survivor."""
    rows = _scan(*_path(), leverages=(20.0,))
    row = rows[0]
    assert row["net_return_pct"] == pytest.approx(-100.0, abs=0.5)
    assert row["ruined"] is True


def test_scan_returns_empty_rather_than_raising_on_a_degenerate_series():
    assert bt.leverage_scan(
        np.asarray([100.0]), np.asarray([100.0]), np.asarray([100.0]),
        np.asarray([1.0]), costs=COSTS, ppy=PPY,
    ) == []
