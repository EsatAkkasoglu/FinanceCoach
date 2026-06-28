"""Unit tests for the multi-asset signal engine's pure logic (no network).

The class-aware fusion (_assemble_plan), candle assembly, and asset-class
inference are exercised directly; the live equity/fund fetch paths are covered
by the network-marked integration smoke test."""
from __future__ import annotations

from app.services import signal_engine as se

# ── asset-class inference ────────────────────────────────────────────────────


def test_infer_asset_class():
    assert se.infer_asset_class("BTC") == "crypto"
    assert se.infer_asset_class("BTC-USD") == "crypto"
    assert se.infer_asset_class("ETH") == "crypto"
    assert se.infer_asset_class("AAPL") == "stock"
    assert se.infer_asset_class("SPY", "etf") == "etf"
    assert se.infer_asset_class("AFA", "fund") == "fund"
    # Explicit class wins over inference.
    assert se.infer_asset_class("BTC", "stock") == "stock"


def test_family_groups_stock_and_etf():
    assert se._family("crypto") == "crypto"
    assert se._family("fund") == "fund"
    assert se._family("stock") == "equity"
    assert se._family("etf") == "equity"


# ── candle assembly ──────────────────────────────────────────────────────────


def test_build_candles_sorts_oldest_first():
    bars = [
        {"date": "2025-01-03", "open": 3, "high": 4, "low": 2, "close": 3.5},
        {"date": "2025-01-01", "open": 1, "high": 2, "low": 0.5, "close": 1.5},
        {"date": "2025-01-02", "open": 2, "high": 3, "low": 1.5, "close": 2.5},
    ]
    out = se._build_candles(bars)
    assert [c["close"] for c in out] == [1.5, 2.5, 3.5]


def test_build_candles_handles_nav_only_rows():
    # TEFAS rows carry `price`, not OHLC — high/low/open fall back to close.
    rows = [{"date": "2025-01-01", "price": 10.0}, {"date": "2025-01-02", "price": 11.0}]
    out = se._build_candles(rows)
    assert out[0]["close"] == 10.0 and out[0]["high"] == 10.0 and out[0]["low"] == 10.0
    assert out[1]["close"] == 11.0


# ── class-aware fusion (_assemble_plan) ──────────────────────────────────────


def _equity_plan(tech, fund, sent, *, bucket="swing", price=100.0, atr=1.0):
    return se._assemble_plan(
        symbol="AAPL", ticker="AAPL", asset_class="stock", bucket=bucket,
        components={"technical": tech, "fundamental": fund, "sentiment": sent},
        weights=se._W_EQUITY,
        technical_detail={}, extra_detail={}, sentiment_n=3,
        atr_bar=atr, price=price, grain="1h",
    )


def test_bullish_equity_is_long_with_target_above_entry():
    p = _equity_plan(0.8, 0.6, 0.4)
    assert p["direction"] == "long"
    assert p["target"] > p["entry"] > p["stop"]
    assert p["target_pct"] > 0 and p["stop_pct"] < 0
    assert p["rr"] == round(se.hz.resolve("swing")["atr_mult_target"] / se.hz.resolve("swing")["atr_mult_stop"], 2)


def test_bearish_equity_is_short():
    p = _equity_plan(-0.8, -0.5, -0.3)
    assert p["direction"] == "short"
    assert p["target"] < p["entry"] < p["stop"]


def test_balanced_equity_is_neutral_no_target():
    p = _equity_plan(0.05, 0.0, -0.05)
    assert p["direction"] == "neutral"
    assert p["target"] is None and p["rr"] is None


def test_fundamentals_swing_the_blended_score():
    bullish = _equity_plan(0.4, 0.9, 0.2)
    bearish = _equity_plan(0.4, -0.9, 0.2)
    assert bullish["score"] > bearish["score"]
    # 0.30 weight on the fundamental/macro slot must be visible in the blend.
    assert bullish["components"]["fundamental"] == 0.9


def test_longer_horizon_widens_equity_target_within_a_grain():
    # Within one bar grain (intraday & swing both use 1h bars), a longer hold
    # → a wider target for the same per-bar ATR. (Across the swing↔position
    # grain boundary the comparison needs the real grain-specific ATR, which is
    # larger for daily bars — so equal-ATR is not apples-to-apples there.)
    intraday = _equity_plan(0.8, 0.6, 0.4, bucket="intraday")
    swing = _equity_plan(0.8, 0.6, 0.4, bucket="swing")
    assert abs(swing["target_pct"]) > abs(intraday["target_pct"])
    assert swing["horizon_hours"] == 24 and intraday["horizon_hours"] == 4


def test_confidence_rises_when_components_agree():
    agree = _equity_plan(0.6, 0.6, 0.6)
    disagree = _equity_plan(0.6, -0.4, -0.4)
    assert agree["confidence"] > disagree["confidence"]


def test_vix_regime_score_is_bounded():
    # Pure mapping check via the clamp helper used inside the scorer.
    assert se._clamp((20.0 - 10.0) / 10.0) == 1.0   # calm VIX 10 → max risk-on
    assert se._clamp((20.0 - 45.0) / 10.0) == -1.0  # panic VIX 45 → max risk-off
