"""Unit tests for the 4-hour crypto short-term signal engine.

All pure — no network. Covers the indicator math (EMA/RSI/ATR), the signal
fusion (direction / ATR target geometry / component influence) and the trade
target re-pricing/resolution lifecycle.
"""
from __future__ import annotations

from datetime import datetime

from app.db.models import TradeStatus, TradeTarget
from app.routers.crypto import _evaluate
from app.tools.crypto_short_term import (
    atr,
    compute_short_term_signal,
    ema_last,
    macd,
    rsi,
)


def _candles(closes: list[float], spread: float = 0.0) -> list[dict[str, float]]:
    """Build oldest-first OHLC candles from a close series (symmetric H/L)."""
    out = []
    for c in closes:
        out.append({"open": c, "high": c + spread, "low": c - spread, "close": c})
    return out


# ── Indicator math ──────────────────────────────────────────────────────────


def test_ema_of_constant_series_is_the_constant():
    assert ema_last([5.0] * 30, 9) == 5.0


def test_ema_tracks_an_uptrend_below_price():
    closes = [float(i) for i in range(1, 41)]
    e = ema_last(closes, 9)
    # EMA of a rising series lags below the latest price.
    assert e is not None and e < closes[-1]


def test_rsi_extremes():
    up = [float(i) for i in range(1, 40)]
    down = [float(i) for i in range(40, 1, -1)]
    assert rsi(up, 14) > 90.0
    assert rsi(down, 14) < 10.0


def test_rsi_none_when_too_short():
    assert rsi([1.0, 2.0, 3.0], 14) is None


def test_atr_positive_for_ranged_series_and_none_when_short():
    closes = [100.0 + i for i in range(30)]
    a = atr(closes, [c + 1 for c in closes], [c - 1 for c in closes], 14)
    assert a is not None and a > 0
    assert atr([1.0, 2.0], [2.0, 3.0], [1.0, 2.0], 14) is None


def test_macd_none_when_too_short():
    assert macd([1.0, 2.0, 3.0]) is None


# ── Signal fusion ───────────────────────────────────────────────────────────


def test_insufficient_candles_returns_not_ok():
    out = compute_short_term_signal(_candles([1.0, 2.0, 3.0]))
    assert out["ok"] is False


def test_strong_uptrend_is_long_with_target_above_entry():
    closes = [100.0 * (1.01 ** i) for i in range(60)]
    out = compute_short_term_signal(_candles(closes, spread=0.5))
    assert out["ok"] is True
    assert out["direction"] == "long"
    assert out["target"] > out["entry"] > out["stop"]
    assert out["rr"] == 1.5
    assert out["target_pct"] > 0 and out["stop_pct"] < 0
    assert out["components"]["technical"] > 0.5


def test_strong_downtrend_is_short_with_target_below_entry():
    closes = [100.0 * (0.99 ** i) for i in range(60)]
    out = compute_short_term_signal(_candles(closes, spread=0.5))
    assert out["direction"] == "short"
    assert out["target"] < out["entry"] < out["stop"]
    assert out["target_pct"] < 0 and out["stop_pct"] > 0


def test_flat_market_is_neutral_with_no_target():
    out = compute_short_term_signal(_candles([100.0] * 60, spread=0.2))
    assert out["direction"] == "neutral"
    assert out["target"] is None and out["stop"] is None


def test_extreme_positive_funding_dampens_a_long_contrarian():
    closes = [100.0 * (1.01 ** i) for i in range(60)]
    base = compute_short_term_signal(_candles(closes, spread=0.5))
    crowded = compute_short_term_signal(
        _candles(closes, spread=0.5), funding_bps_8h=8.0
    )
    # Crowded leverage is a contrarian drag: the blended score must fall.
    assert crowded["score"] < base["score"]
    assert crowded["derivatives_detail"]["squeeze_flag"] == "crowded_longs"


def test_negative_news_sentiment_lowers_the_score():
    closes = [100.0 * (1.01 ** i) for i in range(60)]
    base = compute_short_term_signal(_candles(closes, spread=0.5))
    bearish = compute_short_term_signal(
        _candles(closes, spread=0.5), sentiment_score=-1.0, sentiment_n=5
    )
    assert bearish["score"] < base["score"]
    assert bearish["components"]["sentiment"] == -1.0


def test_rising_oi_confirms_an_uptrend():
    closes = [100.0 * (1.01 ** i) for i in range(60)]
    base = compute_short_term_signal(_candles(closes, spread=0.5))
    confirmed = compute_short_term_signal(
        _candles(closes, spread=0.5), oi_change_24h_pct=10.0
    )
    assert confirmed["derivatives_detail"]["oi_score"] > 0
    assert confirmed["score"] >= base["score"]


# ── Trade-target lifecycle (pure _evaluate, no DB session) ───────────────────


def _target(**kw) -> TradeTarget:
    base = dict(
        id=1,
        ticker="BTC-USD",
        asset_class="crypto",
        direction="long",
        entry_price=100.0,
        target_price=110.0,
        stop_price=95.0,
        horizon_hours=4,
        confidence=0.5,
        score=0.4,
        status=TradeStatus.ACTIVE.value,
        created_at=datetime(2025, 1, 1, 12, 0, 0),
        expires_at=datetime(2025, 1, 1, 16, 0, 0),
    )
    base.update(kw)
    return TradeTarget(**base)


def test_long_target_marked_hit_when_price_reaches_target():
    t = _target()
    view = _evaluate(t, price=111.0, now=datetime(2025, 1, 1, 14, 0, 0))
    assert t.status == TradeStatus.HIT.value
    assert view["status"] == "hit"
    assert view["pnl_pct"] == 11.0
    assert view["progress"] >= 1.0


def test_long_target_marked_stopped_when_price_hits_stop():
    t = _target()
    _evaluate(t, price=94.0, now=datetime(2025, 1, 1, 14, 0, 0))
    assert t.status == TradeStatus.STOPPED.value


def test_target_expires_after_horizon_without_resolution():
    t = _target()
    _evaluate(t, price=103.0, now=datetime(2025, 1, 1, 17, 0, 0))
    assert t.status == TradeStatus.EXPIRED.value
    assert t.resolved_price == 103.0


def test_short_pnl_is_inverted():
    t = _target(direction="short", target_price=90.0, stop_price=105.0)
    view = _evaluate(t, price=95.0, now=datetime(2025, 1, 1, 14, 0, 0))
    # Short from 100 now at 95 → +5% in the trade's favour.
    assert view["pnl_pct"] == 5.0
    assert t.status == TradeStatus.ACTIVE.value
