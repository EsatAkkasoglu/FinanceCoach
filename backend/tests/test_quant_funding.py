"""Perpetual funding — sign, timing, and the engine wiring. No network.

The two properties that matter are the two that were previously wrong:

* Funding is a **transfer, not a fee**. Charging |position| * rate — the old
  unsigned carry — bills the short for money it should have received. An
  audit flagged this as the largest un-modelled friction in a short-heavy
  book; these tests make the sign a pinned property.
* Funding settles at **stamps, not every bar**. A position that opens and
  closes between two settlements owes nothing.
"""
from __future__ import annotations

import json

import numpy as np
import pytest

from app.quant import backtest as bt
from app.quant import funding as fn

HOUR = 3_600_000
FREE = bt.Costs(fee_bps=0.0, slippage_bps=0.0)


def _bars(n: int = 200, step: int = HOUR) -> np.ndarray:
    return np.arange(n, dtype=np.int64) * step


def _flat(n: int = 200) -> np.ndarray:
    """Constant price — every basis point of P&L must come from funding."""
    return np.full(n, 100.0)


# ── stamp mapping ────────────────────────────────────────────────────────────


def test_a_stamp_lands_on_the_single_bar_containing_it():
    ts = _bars(100)
    f = {"ts": [int(ts[10]) + 60_000], "rate": [0.001]}   # inside bar 10
    out = fn.per_bar_funding(ts, f)
    assert out[10] == pytest.approx(0.001)
    assert np.count_nonzero(out) == 1


def test_bars_between_settlements_carry_nothing():
    """The property a per-bar average would destroy: a trade that opens and
    closes between stamps pays no funding at all."""
    ts = _bars(100)
    f = {"ts": [int(ts[0]), int(ts[50])], "rate": [0.001, 0.001]}
    out = fn.per_bar_funding(ts, f)
    assert np.count_nonzero(out) == 2
    assert out[1:50].sum() == 0.0


def test_two_stamps_inside_one_bar_are_summed():
    """A 4h bar spans multiple 8h stamps only in degenerate data, but a coarse
    bar must never silently drop one."""
    ts = _bars(50, step=24 * HOUR)
    f = {"ts": [int(ts[3]) + HOUR, int(ts[3]) + 9 * HOUR], "rate": [0.001, 0.002]}
    out = fn.per_bar_funding(ts, f)
    assert out[3] == pytest.approx(0.003)


def test_stamps_before_the_first_bar_are_dropped():
    ts = _bars(50)
    f = {"ts": [int(ts[0]) - 10 * HOUR], "rate": [0.05]}
    assert fn.per_bar_funding(ts, f).sum() == 0.0


def test_empty_inputs_return_zeros_rather_than_raising():
    assert fn.per_bar_funding(_bars(10), {"ts": [], "rate": []}).sum() == 0.0
    assert fn.per_bar_funding(np.asarray([], dtype=np.int64), {"ts": [1], "rate": [0.1]}).size == 0


# ── sign: the transfer runs the right way ────────────────────────────────────


def _run(direction: float, rate: float) -> float:
    n = 200
    ts, c = _bars(n), _flat(n)
    fr = fn.per_bar_funding(ts, {"ts": [int(ts[50]), int(ts[100])], "rate": [rate, rate]})
    raw = np.full(n, direction)
    return bt.run_backtest(c, raw, costs=FREE, funding_rates=fr).net_total_return


def test_positive_funding_costs_a_long_and_pays_a_short():
    """+rate means longs pay shorts. Two stamps of 0.1% is 0.2% each way."""
    assert _run(+1.0, 0.001) == pytest.approx(-0.002, abs=1e-5)
    assert _run(-1.0, 0.001) == pytest.approx(+0.002, abs=1e-5)


def test_negative_funding_reverses_both_sides():
    assert _run(+1.0, -0.001) == pytest.approx(+0.002, abs=1e-5)
    assert _run(-1.0, -0.001) == pytest.approx(-0.002, abs=1e-5)


def test_a_flat_position_pays_no_funding_at_any_rate():
    n = 200
    ts, c = _bars(n), _flat(n)
    fr = fn.per_bar_funding(ts, {"ts": [int(ts[50])], "rate": [0.05]})
    assert bt.run_backtest(c, np.zeros(n), costs=FREE, funding_rates=fr).net_total_return == (
        pytest.approx(0.0, abs=1e-12)
    )


def test_omitting_funding_reproduces_the_old_behaviour_exactly():
    """Regression guard: every result recorded before funding existed must
    still be reproducible by passing None."""
    rng = np.random.default_rng(5)
    n = 800
    c = 100.0 * np.cumprod(1.0 + rng.normal(0.0, 0.01, n))
    h, lo = c * 1.002, c * 0.998
    raw, warm = bt.build_positions("sma_cross", c, h, lo, {"fast": 10, "slow": 50}, allow_short=True)
    a = bt.run_backtest(c, raw, costs=bt.Costs(), warmup=warm)
    b = bt.run_backtest(c, raw, costs=bt.Costs(), warmup=warm, funding_rates=None)
    assert a.net_total_return == pytest.approx(b.net_total_return, abs=1e-15)


def test_zero_rates_are_indistinguishable_from_no_funding():
    rng = np.random.default_rng(9)
    n = 600
    c = 100.0 * np.cumprod(1.0 + rng.normal(0.0, 0.01, n))
    raw, warm = bt.build_positions("tsmom", c, c, c, {"lookback": 50}, allow_short=True)
    a = bt.run_backtest(c, raw, costs=bt.Costs(), warmup=warm)
    b = bt.run_backtest(c, raw, costs=bt.Costs(), warmup=warm, funding_rates=np.zeros(n))
    assert a.net_total_return == pytest.approx(b.net_total_return, abs=1e-12)


# ── walk_forward wiring ──────────────────────────────────────────────────────


def test_walk_forward_charges_funding_to_the_out_of_sample_record():
    rng = np.random.default_rng(11)
    n = 3000
    c = 100.0 * np.cumprod(1.0 + rng.normal(0.0002, 0.01, n))
    ts = _bars(n)
    stamps = list(range(0, n, 8))
    fr = fn.per_bar_funding(ts, {"ts": [int(ts[i]) for i in stamps],
                                 "rate": [0.001] * len(stamps)})
    kw = dict(grid={"lookback": [50]}, n_folds=4, embargo=10, costs=FREE,
              ppy=8760.0, allow_short=False)
    free = bt.walk_forward(c, "tsmom", **kw)
    paid = bt.walk_forward(c, "tsmom", funding_rates=fr, **kw)
    assert free["ok"] and paid["ok"]
    # A long-only rule under persistently positive funding must do worse.
    assert paid["oos_return_pct"] < free["oos_return_pct"]


# ── frozen mode ──────────────────────────────────────────────────────────────


def test_frozen_mode_reads_the_snapshot(tmp_path, monkeypatch):
    d = tmp_path / "funding"
    d.mkdir()
    (d / "BTC.json").write_text(
        json.dumps({"symbol": "BTC", "source": "okx", "ts": [1, 2], "rate": [0.001, 0.002]}),
        encoding="utf-8",
    )
    monkeypatch.setenv("FINCOACH_FROZEN_DATA", str(tmp_path))
    out = fn.fetch_funding("BTC")
    assert out["rate"] == [0.001, 0.002]


def test_frozen_mode_refuses_a_missing_symbol_instead_of_fetching(tmp_path, monkeypatch):
    monkeypatch.setenv("FINCOACH_FROZEN_DATA", str(tmp_path))
    with pytest.raises(fn.FundingError, match="frozen data layer"):
        fn.fetch_funding("ETH")


def test_summary_reports_the_regime_rather_than_assuming_it():
    out = fn.summary({"ts": [1, 2, 3, 4], "rate": [0.001, -0.001, 0.002, 0.001]})
    assert out["n"] == 4
    assert out["negative_fraction"] == pytest.approx(0.25)
    assert out["annualised_pct"] > 0
