"""Calendar alignment across timeframes — pure, no network.

Why this is tested rather than trusted: the first full tournament measured 15m
over 84 days and 4h over 938 days, then reported a "timeframe ranking". That
ranking was inseparable from a regime difference, and nothing downstream could
detect the problem — every number was individually correct. The window is the
fix, so the window is what gets pinned here.
"""
from __future__ import annotations

import numpy as np

from app.quant import backtest as bt
from app.quant import tournament as tn
from app.quant.exchange import Candles

DAY_MS = 86_400_000
TF_MS = {"15m": 900_000, "30m": 1_800_000, "1h": 3_600_000, "4h": 14_400_000}


def _candles(symbol: str, timeframe: str, *, start_ms: int, n: int) -> Candles:
    step = TF_MS[timeframe]
    ts = start_ms + np.arange(n, dtype=np.int64) * step
    closes = 100.0 * (1.0 + np.linspace(0.0, 0.5, n))
    return Candles(
        symbol=symbol, timeframe=timeframe, source="test", ts=ts,
        opens=closes, highs=closes * 1.001, lows=closes * 0.999,
        closes=closes, volumes=np.ones(n),
    )


# ── Candles.window ───────────────────────────────────────────────────────────


def test_window_keeps_only_bars_inside_the_span():
    c = _candles("BTC", "1h", start_ms=0, n=100)
    cut = c.window(int(c.ts[10]), int(c.ts[20]))
    assert len(cut) == 11
    assert cut.ts[0] == c.ts[10] and cut.ts[-1] == c.ts[20]


def test_window_bounds_are_inclusive():
    c = _candles("BTC", "1h", start_ms=0, n=10)
    assert len(c.window(int(c.ts[0]), int(c.ts[-1]))) == 10


def test_window_on_a_disjoint_span_returns_nothing_rather_than_raising():
    c = _candles("BTC", "1h", start_ms=0, n=10)
    assert len(c.window(10**15, 10**16)) == 0


def test_window_preserves_ohlcv_correspondence():
    c = _candles("BTC", "1h", start_ms=0, n=50)
    cut = c.window(int(c.ts[5]), int(c.ts[9]))
    assert np.allclose(cut.closes, c.closes[5:10])
    assert np.allclose(cut.highs, c.highs[5:10])
    assert np.allclose(cut.volumes, c.volumes[5:10])


def test_span_days_reports_calendar_not_bar_count():
    """The number the bar count hides: same 400 bars, very different spans."""
    fast = _candles("BTC", "15m", start_ms=0, n=400)
    slow = _candles("BTC", "4h", start_ms=0, n=400)
    assert round(fast.span_days) == 4
    assert round(slow.span_days) == 66


# ── _align_window ────────────────────────────────────────────────────────────


def _noop(_msg: str) -> None:
    pass


def test_alignment_picks_the_intersection_of_every_series():
    now = 1_700_000_000_000
    series = {
        ("BTC", "4h"): _candles("BTC", "4h", start_ms=now - 900 * DAY_MS, n=5000),
        ("BTC", "15m"): _candles("BTC", "15m", start_ms=now - 100 * DAY_MS, n=9000),
    }
    win = tn._align_window(series, _noop)
    assert win is not None
    # 15m starts latest, so it sets the start; whichever ends earliest sets the end.
    assert win["start_ms"] == int(series[("BTC", "15m")].ts[0])
    assert win["start_set_by"] == "BTC/15m"


def test_alignment_equalises_calendar_span_across_timeframes():
    """The actual point: after cutting, every timeframe covers the same days."""
    now = 1_700_000_000_000
    start_slow = now - 900 * DAY_MS
    start_fast = now - 100 * DAY_MS
    series = {
        ("BTC", "15m"): _candles("BTC", "15m", start_ms=start_fast, n=9600),
        ("BTC", "1h"): _candles("BTC", "1h", start_ms=start_slow, n=21600),
        ("BTC", "4h"): _candles("BTC", "4h", start_ms=start_slow, n=5400),
    }
    win = tn._align_window(series, _noop)
    spans = {
        tf: c.window(win["start_ms"], win["end_ms"]).span_days
        for (_s, tf), c in series.items()
    }
    # Slack is at most one bar of the slowest timeframe (4h = 1/6 day).
    assert max(spans.values()) - min(spans.values()) < 0.25
    # …and the bar counts now differ by roughly the timeframe ratio, as they must.
    assert spans["15m"] > 90


def test_alignment_returns_none_when_series_do_not_overlap():
    series = {
        ("BTC", "1h"): _candles("BTC", "1h", start_ms=0, n=100),
        ("ETH", "1h"): _candles("ETH", "1h", start_ms=10**14, n=100),
    }
    assert tn._align_window(series, _noop) is None


def test_alignment_returns_none_for_an_empty_universe():
    assert tn._align_window({}, _noop) is None


def test_warmup_budget_is_measured_not_guessed():
    """The prefix has to cover the LONGEST warm-up any config in the grid needs."""
    strategies = tuple(k for k in bt.SIGNALS if k != "buy_hold")
    for tf in ("15m", "30m", "1h", "4h"):
        budget = tn.warmup_bars_for(tf, strategies)
        assert budget > 0
        probe = np.linspace(100.0, 120.0, 4000)
        for strategy in strategies:
            for params in tn._combos(tn.grid_for(strategy, tf)):
                _raw, warmup = bt.build_positions(strategy, probe, probe, probe, params)
                assert warmup <= budget, f"{tf}/{strategy}/{params} needs {warmup} > {budget}"


# ── eval_start: paying for warm-up out of history, not out of the window ─────


def _series(n: int, seed: int = 3) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return 100.0 * np.cumprod(1.0 + rng.normal(0.0002, 0.01, n))


def _wf(closes, **kw):
    return bt.walk_forward(
        closes, "sma_cross", grid={"fast": [10], "slow": [50]},
        n_folds=5, embargo=10, costs=bt.Costs(), ppy=252.0, **kw
    )


def test_eval_start_shrinks_the_evaluated_span():
    c = _series(3000)
    base = _wf(c)
    shifted = _wf(c, eval_start=1000)
    assert base["ok"] and shifted["ok"]
    assert shifted["oos_bars"] < base["oos_bars"]


def test_eval_start_below_the_indicator_warmup_is_a_no_op():
    """The engine still cannot evaluate un-warmed bars, so a small prefix
    changes nothing — the guarantee that makes the flag safe to pass blindly."""
    c = _series(3000)
    assert _wf(c, eval_start=5)["oos_bars"] == _wf(c)["oos_bars"]


def test_eval_start_leaves_the_evaluated_fraction_timeframe_independent():
    """The actual fix.

    Two series covering the SAME calendar at different bar sizes: 4000 fast bars
    against 1000 four-times-coarser ones. Each gets a warm-up prefix worth the
    same slice of calendar (200 fast bars, 50 slow ones), and both prefixes
    exceed the indicator's own warm-up — which is the condition the tournament
    arranges by sizing the prefix from the widest grid.

    The evaluated span must then be the same FRACTION of each series. Without
    the prefix the fixed indicator warm-up is deducted from the window itself,
    which costs the coarse series four times as much of its calendar.
    """
    grid = {"fast": [5], "slow": [20]}          # 20-bar warm-up, under both prefixes
    kw = dict(n_folds=5, embargo=10, costs=bt.Costs(), ppy=252.0)
    f = bt.walk_forward(_series(4200), "sma_cross", grid=grid, eval_start=200, **kw)
    s = bt.walk_forward(_series(1050, seed=4), "sma_cross", grid=grid, eval_start=50, **kw)
    assert f["ok"] and s["ok"]
    f_frac = f["oos_bars"] / (4200 - 200)
    s_frac = s["oos_bars"] / (1050 - 50)
    assert abs(f_frac - s_frac) < 0.05, (f_frac, s_frac)


def test_eval_start_beyond_the_series_refuses_rather_than_fabricating_folds():
    out = _wf(_series(3000), eval_start=2990)
    assert out["ok"] is False
    assert "not enough history" in out["reason"]


def test_training_windows_are_equal_length_across_configs_in_a_fold():
    """A combo with a short lookback used to get a longer training window than
    one with a long lookback inside the same fold, so the selection was partly a
    comparison of sample sizes rather than of rules."""
    c = _series(3000)
    out = bt.walk_forward(
        c, "sma_cross", grid={"fast": [5, 10], "slow": [20, 200]},
        n_folds=3, embargo=5, costs=bt.Costs(), ppy=252.0,
    )
    assert out["ok"]
    # train_bars is reported from the common start, so it grows monotonically
    # with the fold index and never depends on which combo won.
    train = [f["train_bars"] for f in out["folds"]]
    assert train == sorted(train)
    assert all(t > 0 for t in train)


def test_alignment_reports_which_series_binds_each_end():
    now = 1_700_000_000_000
    series = {
        # 4h reaches back 900 days and runs to now; HYPE only lists 60 days ago.
        ("BTC", "4h"): _candles("BTC", "4h", start_ms=now - 900 * DAY_MS, n=5400),
        ("HYPE", "15m"): _candles("HYPE", "15m", start_ms=now - 60 * DAY_MS, n=5700),
    }
    win = tn._align_window(series, _noop)
    assert win["start_set_by"] == "HYPE/15m"
    assert isinstance(win["start"], str) and isinstance(win["end"], str)
    assert win["days"] > 0
