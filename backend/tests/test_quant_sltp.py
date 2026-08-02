"""Stop-loss / take-profit simulator and the frozen data layer — no network.

Two properties carry the whole SL/TP study:

1. With both levels disabled the simulator reproduces run_backtest's equity
   exactly — otherwise every SL/TP comparison confounds the overlay with an
   engine difference.
2. The stop/target ambiguity inside one bar is resolved AGAINST the trade and
   counted — the single most flattering lie a stop backtest can tell is
   assuming the target printed first.
"""
from __future__ import annotations

import json

import numpy as np
import pytest

from app.quant import backtest as bt
from app.quant import exchange

COSTS = bt.Costs(fee_bps=10.0, slippage_bps=5.0)


def _flat_path(n: int = 300, base: float = 100.0):
    c = np.full(n, base)
    return c, c * 1.001, c * 0.999, np.concatenate(([c[0]], c[:-1]))


def _sim(c, h, lo, o, raw, **kw):
    return bt.run_sltp_backtest(c, h, lo, o, raw, costs=COSTS, warmup=20, **kw)


# ── identity with the main engine when disabled ──────────────────────────────


@pytest.mark.parametrize("strategy,params", [
    ("sma_cross", {"fast": 20, "slow": 100}),
    ("rsi_reversion", {"period": 14, "low": 30.0, "high": 70.0}),
    ("donchian", {"lookback": 55}),
])
@pytest.mark.parametrize("allow_short", [False, True])
def test_disabled_sltp_reproduces_the_engine_exactly(strategy, params, allow_short):
    rng = np.random.default_rng(7)
    n = 1500
    c = 100.0 * np.cumprod(1.0 + rng.normal(0.0002, 0.01, n))
    h = c * (1.0 + np.abs(rng.normal(0, 0.004, n)))
    lo = c * (1.0 - np.abs(rng.normal(0, 0.004, n)))
    o = np.concatenate(([c[0]], c[:-1]))
    raw, warm = bt.build_positions(strategy, c, h, lo, params, allow_short=allow_short)
    base = bt.run_backtest(c, raw, costs=COSTS, warmup=warm)
    sim = bt.run_sltp_backtest(c, h, lo, o, raw, costs=COSTS, warmup=warm)
    assert sim["net_return_pct"] == pytest.approx(base.net_total_return * 100.0, abs=1e-3)


# ── stop and target mechanics ────────────────────────────────────────────────


def _one_long(n: int = 300, entry_bar: int = 50):
    """A raw series that goes long at `entry_bar` and stays long."""
    raw = np.zeros(n)
    raw[entry_bar:] = 1.0
    return raw


def test_stop_fills_at_the_stop_price_on_a_wick():
    c, h, lo, o = _flat_path()
    raw = _one_long()
    # ATR of the flat path is ~0.2; a 2xATR stop sits ~0.4 under entry.
    sim = _sim(c, h, lo, o, raw, sl_atr=2.0)
    stop = sim["trades"][0]["stop"]
    lo2 = lo.copy()
    lo2[100] = stop - 0.05                       # wick through, close unchanged
    sim2 = _sim(c, h, lo2, o, raw, sl_atr=2.0)
    t = sim2["trades"][0]
    assert t["reason"] == "stop"
    assert t["exit_price"] == pytest.approx(stop)
    assert t["net_pnl_pct"] < 0


def test_target_fills_at_the_target_price_on_a_wick():
    c, h, lo, o = _flat_path()
    raw = _one_long()
    sim = _sim(c, h, lo, o, raw, sl_atr=2.0, tp_atr=4.0)
    target = sim["trades"][0]["target"]
    h2 = h.copy()
    h2[100] = target + 0.05
    sim2 = _sim(c, h2, lo, o, raw, sl_atr=2.0, tp_atr=4.0)
    t = sim2["trades"][0]
    assert t["reason"] == "target"
    assert t["exit_price"] == pytest.approx(target)
    assert t["net_pnl_pct"] > 0


def test_a_bar_touching_both_levels_is_resolved_as_a_stop_and_counted():
    """The honesty clause: when one bar spans stop AND target, the simulator
    must not award the win — OHLC cannot say which printed first."""
    c, h, lo, o = _flat_path()
    raw = _one_long()
    ref = _sim(c, h, lo, o, raw, sl_atr=1.0, tp_atr=1.0)
    stop, target = ref["trades"][0]["stop"], ref["trades"][0]["target"]
    h2, lo2 = h.copy(), lo.copy()
    h2[100] = target + 0.1
    lo2[100] = stop - 0.1
    sim = _sim(c, h2, lo2, o, raw, sl_atr=1.0, tp_atr=1.0)
    assert sim["trades"][0]["reason"] == "stop"
    assert sim["ambiguous_bars"] == 1


def test_a_gap_through_the_stop_fills_at_the_open_not_the_stop():
    """Gapping past a stop does not grant the stop price — the fill is the
    open, which is strictly worse. A simulator that fills at the level turns
    every overnight crash into a controlled loss."""
    c, h, lo, o = _flat_path()
    raw = _one_long()
    ref = _sim(c, h, lo, o, raw, sl_atr=2.0)
    stop = ref["trades"][0]["stop"]
    c2, h2, lo2, o2 = c.copy(), h.copy(), lo.copy(), o.copy()
    gap = stop - 1.0                              # opens far below the stop
    o2[100] = gap
    lo2[100] = gap - 0.1
    sim = _sim(c2, h2, lo2, o2, raw, sl_atr=2.0)
    t = sim["trades"][0]
    assert t["reason"] == "stop"
    assert t["exit_price"] == pytest.approx(gap)
    assert t["exit_price"] < stop


def test_short_positions_are_stopped_by_an_upward_wick():
    c, h, lo, o = _flat_path()
    raw = np.zeros(300)
    raw[50:] = -1.0
    ref = _sim(c, h, lo, o, raw, sl_atr=2.0)
    stop = ref["trades"][0]["stop"]
    assert stop > 100.0                           # a short's stop sits above entry
    h2 = h.copy()
    h2[100] = stop + 0.05
    sim = _sim(c, h2, lo, o, raw, sl_atr=2.0)
    t = sim["trades"][0]
    assert t["reason"] == "stop"
    assert t["direction"] == -1.0
    assert t["net_pnl_pct"] < 0


def test_reentry_is_blocked_until_the_signal_resets():
    """After a stop-out with the signal still long, re-entering immediately
    would turn the stop into a pure re-entry tax."""
    c, h, lo, o = _flat_path()
    raw = _one_long()                             # long forever, never resets
    ref = _sim(c, h, lo, o, raw, sl_atr=2.0)
    stop = ref["trades"][0]["stop"]
    lo2 = lo.copy()
    lo2[100] = stop - 0.05
    sim = _sim(c, h, lo2, o, raw, sl_atr=2.0)
    assert len(sim["trades"]) == 1                # stopped once, never re-entered

    raw2 = raw.copy()
    raw2[150:160] = 0.0                           # the signal resets…
    sim2 = _sim(c, h, lo2, o, raw2, sl_atr=2.0)
    assert len(sim2["trades"]) == 2               # …and the rule may re-enter
    assert sim2["trades"][1]["entry_bar"] >= 160


def test_win_loss_accounting_adds_up():
    c, h, lo, o = _flat_path()
    raw = _one_long()
    ref = _sim(c, h, lo, o, raw, sl_atr=2.0, tp_atr=4.0)
    stop, target = ref["trades"][0]["stop"], ref["trades"][0]["target"]
    h2, lo2 = h.copy(), lo.copy()
    h2[80] = target + 0.05                        # win
    raw2 = _one_long()
    raw2[90:100] = 0.0                            # reset → second trade
    lo2[150] = stop - 0.05                        # would-be loss for trade 2
    sim = _sim(c, h2, lo2, o, raw2, sl_atr=2.0, tp_atr=4.0)
    assert sim["n_trades"] == sim["n_wins"] + sim["n_losses"]
    assert sim["n_trades"] >= 2
    total = sum(t["net_pnl_pct"] for t in sim["trades"])
    assert sim["expectancy_pct"] == pytest.approx(total / sim["n_trades"], abs=1e-3)


# ── frozen data layer ────────────────────────────────────────────────────────


def _write_snapshot(tmp_path, symbol="BTC", timeframe="1h", n=50):
    rows = [
        [float(i * 3_600_000), 100.0, 101.0, 99.0, 100.5, 10.0] for i in range(n)
    ]
    (tmp_path / f"{symbol}_{timeframe}.json").write_text(
        json.dumps({"source": "okx", "rows": rows}), encoding="utf-8"
    )
    return rows


def test_frozen_mode_reads_only_the_snapshot(tmp_path, monkeypatch):
    _write_snapshot(tmp_path)
    monkeypatch.setenv("FINCOACH_FROZEN_DATA", str(tmp_path))
    c = exchange.fetch_candles("BTC", "1h", 100)
    assert len(c) == 50
    assert c.source == "frozen:okx"


def test_frozen_mode_refuses_a_missing_series_instead_of_fetching(tmp_path, monkeypatch):
    monkeypatch.setenv("FINCOACH_FROZEN_DATA", str(tmp_path))
    with pytest.raises(exchange.ExchangeError, match="frozen data layer"):
        exchange.fetch_candles("ETH", "1h", 100)


def test_frozen_mode_never_writes_the_live_cache(tmp_path, monkeypatch):
    _write_snapshot(tmp_path)
    cache = tmp_path / "live_cache"
    monkeypatch.setenv("FINCOACH_FROZEN_DATA", str(tmp_path))
    monkeypatch.setattr(exchange, "CACHE_DIR", str(cache))
    exchange.fetch_candles("BTC", "1h", 100)
    assert not cache.exists()
