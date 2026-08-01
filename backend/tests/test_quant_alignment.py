"""Calendar alignment across timeframes — pure, no network.

Why this is tested rather than trusted: the first full tournament measured 15m
over 84 days and 4h over 938 days, then reported a "timeframe ranking". That
ranking was inseparable from a regime difference, and nothing downstream could
detect the problem — every number was individually correct. The window is the
fix, so the window is what gets pinned here.
"""
from __future__ import annotations

import numpy as np

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
