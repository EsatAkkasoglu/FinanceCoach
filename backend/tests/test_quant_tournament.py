"""Tournament tests — no network, synthetic price paths.

The property that matters most here is the multiple-testing accounting. A
tournament that deflates the winner's Sharpe by its own six-cell parameter grid,
rather than by the thousands of configurations actually searched, will bless
noise every single time.
"""
from __future__ import annotations

import numpy as np
import pytest

from app.quant import backtest as bt
from app.quant import tournament as tn
from app.quant.exchange import Candles

ZERO_COST = bt.Costs(fee_bps=0.0, slippage_bps=0.0)


def _series(n: int = 3000, drift: float = 0.0002, amp: float = 0.03, seed: int = 5) -> np.ndarray:
    rng = np.random.default_rng(seed)
    t = np.arange(n, dtype=float)
    wiggle = np.cumsum(rng.normal(0.0, 0.002, n))
    return 100.0 * np.exp(drift * t + amp * np.sin(t / 40.0) + wiggle * 0.2)


def _candles(symbol: str = "BTC", timeframe: str = "1h", n: int = 3000) -> Candles:
    closes = _series(n)
    return Candles(
        symbol=symbol, timeframe=timeframe, source="test",
        ts=np.arange(n, dtype=np.int64) * 3_600_000,
        opens=closes, highs=closes * 1.004, lows=closes * 0.996,
        closes=closes, volumes=np.ones(n),
    )


@pytest.fixture
def offline(monkeypatch):
    monkeypatch.setattr(
        tn, "fetch_candles",
        lambda symbol, timeframe, want, use_cache=True: _candles(symbol, timeframe),
    )


# ── grids ────────────────────────────────────────────────────────────────────


def test_grids_are_timeframe_aware():
    """A 252-bar lookback is a year on daily bars and two days on 15m bars —
    the grids have to be expressed in bars, not inherited from the daily set."""
    assert tn.grid_for("tsmom", "15m")["lookback"] != tn.grid_for("tsmom", "4h")["lookback"]


def test_grid_size_counts_the_cartesian_product():
    assert tn.grid_size("sma_cross", "1h") == 9        # 3 fast × 3 slow
    assert tn.grid_size("buy_hold", "1h") == 1         # no parameters


def test_every_strategy_has_a_grid():
    for strategy in bt.SIGNALS:
        assert tn.grid_size(strategy, "15m") >= 1


# ── one cell ─────────────────────────────────────────────────────────────────


def test_evaluate_cell_returns_series_that_line_up():
    candles = _candles()
    cell, trials, oos, bench = tn.evaluate_cell(candles, "sma_cross", costs=ZERO_COST)
    assert cell.symbol == "BTC" and cell.variant == "long_flat"
    assert cell.n_configs == len(trials) > 0
    assert oos.size == bench.size          # strategy and benchmark cover the same bars


def test_benchmark_covers_the_out_of_sample_bars_only():
    """Comparing an out-of-sample record against a FULL-sample buy & hold is the
    classic apples-to-oranges error — the two figures must differ."""
    candles = _candles()
    cell, _t, oos, _b = tn.evaluate_cell(candles, "sma_cross", costs=ZERO_COST)
    assert cell.oos_ok is True
    assert cell.oos_buy_hold_return_pct is not None
    assert cell.oos_buy_hold_return_pct != cell.buy_hold_return_pct
    assert oos.size < len(candles)         # OOS is a strict subset


def test_short_variant_is_labelled_and_can_differ():
    candles = _candles()
    long_flat, _t1, _o1, _b1 = tn.evaluate_cell(candles, "sma_cross", costs=ZERO_COST)
    long_short, _t2, _o2, _b2 = tn.evaluate_cell(
        candles, "sma_cross", costs=ZERO_COST, allow_short=True
    )
    assert long_flat.variant == "long_flat"
    assert long_short.variant == "long_short"
    assert long_short.oos_return_pct != long_flat.oos_return_pct


def test_costs_reduce_the_out_of_sample_return():
    candles = _candles()
    free, _t1, _o1, _b1 = tn.evaluate_cell(candles, "sma_cross", costs=ZERO_COST)
    dear, _t2, _o2, _b2 = tn.evaluate_cell(
        candles, "sma_cross", costs=bt.Costs(fee_bps=50.0, slippage_bps=50.0)
    )
    assert dear.oos_return_pct < free.oos_return_pct


# ── the full run ─────────────────────────────────────────────────────────────


def test_tournament_counts_every_configuration_it_tried(offline):
    res = tn.run_tournament(
        symbols=("BTC", "ETH"), timeframes=("1h",),
        strategies=("sma_cross", "tsmom"), include_short=True,
    )
    # 2 symbols × 1 timeframe × 2 strategies × 2 variants
    assert res["n_cells"] == 8
    expected = 2 * 2 * (tn.grid_size("sma_cross", "1h") + tn.grid_size("tsmom", "1h"))
    assert res["total_configurations_tested"] == expected


def test_leaderboard_deflates_against_the_whole_tournament_not_one_grid(offline):
    """dsr_tournament must be no kinder than the per-cell dsr_local, because it
    corrects for every configuration searched anywhere in the run."""
    res = tn.run_tournament(
        symbols=("BTC",), timeframes=("1h",),
        strategies=("sma_cross", "tsmom", "donchian"),
    )
    checked = 0
    for row in res["leaderboard"]:
        if row["dsr_local"] is not None and row["dsr_tournament"] is not None:
            assert row["dsr_tournament"] <= row["dsr_local"] + 1e-9
            checked += 1
    assert checked > 0


def test_leaderboard_rows_carry_a_fair_benchmark_and_three_verdicts(offline):
    res = tn.run_tournament(
        symbols=("BTC",), timeframes=("1h",), strategies=("sma_cross", "donchian")
    )
    assert res["leaderboard"]
    for row in res["leaderboard"]:
        assert row["oos_buy_hold_return_pct"] is not None
        assert row["excess_vs_buy_hold_pct"] == pytest.approx(
            row["oos_return_pct"] - row["oos_buy_hold_return_pct"], abs=1e-6
        )
        assert "dsr_tournament" in row and "bootstrap_p" in row
        assert isinstance(row["survives"], bool)


def test_verdict_reports_a_null_result_plainly(offline):
    res = tn.run_tournament(
        symbols=("BTC",), timeframes=("1h",), strategies=("sma_cross",), include_short=False
    )
    verdict = res["verdict"]
    assert verdict["n_survivors"] == len(verdict["survivors"])
    assert "cleared all three tests" in verdict["headline"]
    if verdict["n_survivors"] == 0:
        assert "expected outcome" in verdict["headline"]


def test_tournament_records_fetch_failures_without_aborting(monkeypatch):
    def flaky(symbol, timeframe, want, use_cache=True):
        if symbol == "ETH":
            raise tn.ExchangeError("no data for ETH")
        return _candles(symbol, timeframe)

    monkeypatch.setattr(tn, "fetch_candles", flaky)
    res = tn.run_tournament(
        symbols=("BTC", "ETH"), timeframes=("1h",), strategies=("sma_cross",)
    )
    assert any("ETH" in e for e in res["fetch_errors"])
    assert res["n_cells"] > 0          # BTC still evaluated


def test_tournament_result_is_json_serializable(offline):
    import json

    res = tn.run_tournament(
        symbols=("BTC",), timeframes=("1h",), strategies=("sma_cross",)
    )
    json.dumps(res)      # raises on numpy scalars leaking through
