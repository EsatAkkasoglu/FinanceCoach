"""Exchange candle-loader tests — no network, every HTTP call is stubbed.

The two assertions that carry real weight are the in-progress-bar drop and the
de-duplication. Both failures are silent: an unclosed bar leaks the future into
every indicator, and a duplicated bar double-counts a return. Neither raises,
neither shows up in a chart, and both inflate every downstream metric.
"""
from __future__ import annotations

import time

import numpy as np
import pytest

from app.quant import exchange as ex


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(ex, "CACHE_DIR", str(tmp_path))
    return tmp_path


def _now_ms() -> int:
    return int(time.time() * 1000)


def _rows(n: int, start_i: int = 0, base: float = 100.0) -> list[list[float]]:
    """Realistic bars: a moving close and a non-zero high-low range.

    Constant prices would trip the stale-book gate (100% of bars unchanged) and
    a flat 1.0 -> 2.0 step would trip the discontinuity truncator, so fixtures
    have to look like a market or they test the guards instead of the loader.
    """
    out = []
    for k in range(n):
        i = start_i + k
        close = base * (1.0 + 0.0007 * i + 0.004 * np.sin(i / 7.0))
        out.append([float(i * 900_000), close * 0.999, close * 1.003,
                    close * 0.997, close, 100.0 + i])
    return out


# ── normalisation ────────────────────────────────────────────────────────────


def test_rows_are_sorted_oldest_first():
    rows = [[3000.0, 1, 2, 0.5, 1.5, 10], [1000.0, 1, 2, 0.5, 1.2, 10], [2000.0, 1, 2, 0.5, 1.3, 10]]
    c = ex._normalise(rows, "BTC", "15m", "test")
    assert c.ts.tolist() == [1000, 2000, 3000]
    assert c.closes.tolist() == [1.2, 1.3, 1.5]


def test_duplicate_timestamps_are_collapsed():
    """Paginated fetches overlap at the seams — a repeated bar would double a
    return and quietly inflate every metric built on it."""
    rows = [[1000.0, 1, 2, 0.5, 1.2, 10]] * 4 + [[2000.0, 1, 2, 0.5, 1.3, 10]]
    c = ex._normalise(rows, "BTC", "15m", "test")
    assert len(c) == 2


def test_malformed_bars_are_dropped():
    rows = [
        [1000.0, 1, 2, 0.5, 1.2, 10],
        [2000.0, 1, 2, 0.5, 0.0, 10],           # zero close
        [3000.0, 1, 0.4, 0.9, 1.4, 10],         # high below low
        [4000.0, 1, 2, 0.5, float("nan"), 10],  # non-finite
    ]
    assert len(ex._normalise(rows, "BTC", "15m", "test")) == 1


def test_empty_input_yields_an_empty_series():
    c = ex._normalise([], "BTC", "1h", "test")
    assert len(c) == 0 and c.closes.size == 0


# ── the in-progress bar ──────────────────────────────────────────────────────


def test_okx_drops_the_unconfirmed_bar(monkeypatch):
    """OKX flags a live candle with confirm != "1". Trading it means using a
    close that has not happened yet."""
    now = _now_ms()
    payload = {"code": "0", "data": [
        [str(now), "10", "11", "9", "10.5", "5", "", "", "0"],       # live
        [str(now - 900_000), "10", "11", "9", "10.2", "5", "", "", "1"],
        [str(now - 1_800_000), "10", "11", "9", "10.1", "5", "", "", "1"],
    ]}
    monkeypatch.setattr(ex, "_get", lambda url, params: payload)
    rows = ex._okx_rows("BTC", "15m", 2)
    assert len(rows) == 2
    assert all(int(r[0]) < now for r in rows)


def test_binance_drops_a_bar_whose_close_time_has_not_passed(monkeypatch):
    """Binance does not flag the live bar, so it is identified by arithmetic:
    open time + one interval must already be in the past."""
    now = _now_ms()
    step = ex._TIMEFRAME_MS["15m"]
    payload = [
        [now - step * 3, "10", "11", "9", "10.1", "5"],
        [now - step * 2, "10", "11", "9", "10.2", "5"],
        [now, "10", "11", "9", "10.5", "5"],           # still forming
    ]
    calls = {"n": 0}

    def fake_get(url, params):
        calls["n"] += 1
        return payload if calls["n"] == 1 else []

    monkeypatch.setattr(ex, "_get", fake_get)
    rows = ex._binance_rows("BTC", "15m", 10)
    assert len(rows) == 2
    assert all(r[0] + step <= _now_ms() for r in rows)


# ── source fallback ──────────────────────────────────────────────────────────


def test_fetch_falls_through_to_the_next_venue(cache_dir, monkeypatch):
    def dead(symbol, timeframe, want):
        raise RuntimeError("venue down")

    good = _rows(200)
    monkeypatch.setattr(ex, "_SOURCES", (("dead", dead), ("good", lambda s, t, w: good)))

    c = ex.fetch_candles("BTC", "15m", 100)
    assert c.source == "good"
    assert len(c) == 200


def test_fetch_keeps_the_deepest_series_across_venues(cache_dir, monkeypatch):
    """A venue that returns a stub is not a hit — the loader keeps looking."""
    shallow = _rows(10)
    deep = _rows(500)
    monkeypatch.setattr(
        ex, "_SOURCES",
        (("shallow", lambda s, t, w: shallow), ("deep", lambda s, t, w: deep)),
    )
    c = ex.fetch_candles("BTC", "15m", 400)
    assert c.source == "deep"
    assert len(c) == 500


def test_fetch_raises_only_when_every_source_fails(cache_dir, monkeypatch):
    def dead(symbol, timeframe, want):
        raise RuntimeError("nope")

    monkeypatch.setattr(ex, "_SOURCES", (("a", dead), ("b", dead)))
    with pytest.raises(ex.ExchangeError):
        ex.fetch_candles("BTC", "15m", 100)


def test_unsupported_timeframe_is_rejected(cache_dir):
    with pytest.raises(ex.ExchangeError):
        ex.fetch_candles("BTC", "7m", 100)


# ── cache ────────────────────────────────────────────────────────────────────


def test_cache_is_written_and_extends_a_later_fetch(cache_dir, monkeypatch):
    first = _rows(300)
    monkeypatch.setattr(ex, "_SOURCES", (("v1", lambda s, t, w: first),))
    ex.fetch_candles("BTC", "15m", 200)
    assert (cache_dir / "BTC_15m.json").exists()

    # A later fetch returning only NEW bars must still see the cached history.
    later = _rows(20, start_i=300)
    monkeypatch.setattr(ex, "_SOURCES", (("v2", lambda s, t, w: later),))
    merged = ex.fetch_candles("BTC", "15m", 200)
    assert len(merged) == 320


def test_a_corrupt_cache_does_not_stop_a_fetch(cache_dir, monkeypatch):
    (cache_dir / "BTC_15m.json").write_text("{not json", encoding="utf-8")
    rows = _rows(50)
    monkeypatch.setattr(ex, "_SOURCES", (("v", lambda s, t, w: rows),))
    assert len(ex.fetch_candles("BTC", "15m", 50)) == 50


# ── shape helpers ────────────────────────────────────────────────────────────


def test_bars_per_year_matches_a_24_7_market():
    assert ex.BARS_PER_YEAR["1h"] == pytest.approx(365.25 * 24)
    assert ex.BARS_PER_YEAR["15m"] == pytest.approx(ex.BARS_PER_YEAR["1h"] * 4)
    assert ex.BARS_PER_YEAR["4h"] == pytest.approx(ex.BARS_PER_YEAR["1h"] / 4)


def test_candles_tail_and_dates_line_up():
    rows = _rows(100)
    c = ex._normalise(rows, "ETH", "1h", "test")
    t = c.tail(10)
    assert len(t) == 10
    assert len(t.dates) == 10
    assert t.closes[-1] == c.closes[-1]
    assert np.all(np.diff(c.ts) > 0)


# ── data-quality gates ───────────────────────────────────────────────────────


def test_a_stale_book_is_marked_untradeable():
    """The TRX case: 68% of bars unchanged, zero volume, no range. Spectacular
    mean-reversion backtests on this are bid-ask bounce, not an edge."""
    rows = []
    for i in range(400):
        close = 0.33 if i % 3 else 0.33 * (1 + 0.01 * ((i // 3) % 5 - 2))
        rows.append([float(i * 900_000), close, close, close, close, 0.0])
    c = ex._normalise(rows, "TRX", "15m", "test")
    assert c.tradeable is False
    joined = " ".join(c.quality.reasons)
    assert "stale book" in joined
    assert "zero volume" in joined


def test_a_liquid_book_passes_every_gate():
    c = ex._normalise(_rows(500), "BTC", "15m", "test")
    assert c.tradeable is True
    assert c.quality.reasons == []
    assert c.quality.stale_fraction < ex.MAX_STALE_FRACTION


def test_a_split_sized_jump_truncates_the_series():
    """TRX/1h printed +385% in one bar — a redenomination, not a return. Keeping
    it hands any long rule a free 385%."""
    rows = _rows(300) + _rows(200, start_i=300, base=500.0)
    c = ex._normalise(rows, "TRX", "1h", "test")
    assert len(c) == 200                      # only the post-break segment survives
    assert c.quality.n_discontinuities == 0   # and the survivor is clean


def test_fetch_prefers_a_liquid_venue_over_a_deeper_stale_one(cache_dir, monkeypatch):
    """Depth was the old criterion, and it is exactly how a dead book won."""
    stale = [
        [float(i * 900_000), 0.33, 0.33, 0.33, 0.33, 0.0] for i in range(2000)
    ]
    liquid = _rows(600)
    monkeypatch.setattr(
        ex, "_SOURCES",
        (("deep-but-dead", lambda s, t, w: stale), ("liquid", lambda s, t, w: liquid)),
    )
    c = ex.fetch_candles("TRX", "15m", 1500, use_cache=False)
    assert c.source == "liquid"
    assert c.tradeable is True


def test_quality_is_json_safe():
    c = ex._normalise(_rows(300), "BTC", "15m", "test")
    payload = c.quality.as_dict()
    import json

    json.dumps(payload)
    assert set(payload) >= {"stale_fraction", "median_range_pct", "tradeable", "reasons"}
