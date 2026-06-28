"""Unit tests for the canonical trade-horizon model and its effect on the
signal engine's target geometry. All pure — no network."""
from __future__ import annotations

import math

from app.services import horizon as hz
from app.tools.crypto_short_term import compute_short_term_signal


def _candles(closes: list[float], spread: float = 0.0) -> list[dict[str, float]]:
    return [{"open": c, "high": c + spread, "low": c - spread, "close": c} for c in closes]


# ── resolve / bucket_for_hours ───────────────────────────────────────────────


def test_resolve_defaults_to_swing_for_unknown_or_none():
    assert hz.resolve(None)["name"] == "swing"
    assert hz.resolve("nonsense")["name"] == "swing"
    assert hz.resolve("position")["name"] == "position"


def test_canonical_hours_are_stable():
    assert hz.resolve("intraday")["hours"] == 4
    assert hz.resolve("swing")["hours"] == 24
    assert hz.resolve("position")["hours"] == 168
    assert hz.resolve("long")["hours"] == 720


def test_bucket_for_hours_picks_nearest():
    assert hz.bucket_for_hours(4) == "intraday"
    assert hz.bucket_for_hours(20) == "swing"
    assert hz.bucket_for_hours(150) == "position"
    assert hz.bucket_for_hours(1000) == "long"
    assert hz.bucket_for_hours(None) == hz.DEFAULT_BUCKET


def test_reward_risk_is_about_1_5_for_every_bucket():
    for b in ("intraday", "swing", "position", "long"):
        spec = hz.resolve(b)
        rr = spec["atr_mult_target"] / spec["atr_mult_stop"]
        assert 1.45 <= rr <= 1.55


# ── keyword fallback (LLM-down only) ─────────────────────────────────────────


def test_keyword_bucket_multilingual():
    assert hz.keyword_bucket("gün içi scalp") == "intraday"
    assert hz.keyword_bucket("3 saatlik bir işlem") == "intraday"
    assert hz.keyword_bucket("birkaç gün tutarım") == "swing"
    assert hz.keyword_bucket("önümüzdeki 2 hafta") == "position"
    assert hz.keyword_bucket("birkaç ay") == "long"
    assert hz.keyword_bucket("over the next few months") == "long"
    assert hz.keyword_bucket("merhaba nasılsın") is None


# ── ATR target geometry ──────────────────────────────────────────────────────


def test_horizon_atr_scales_by_sqrt_of_bars():
    # intraday = 4h on 1h bars → √4 = 2× the per-bar ATR.
    assert hz.horizon_atr(1.0, "intraday") == 2.0
    # position = 168h on 1d bars → √7.
    assert math.isclose(hz.horizon_atr(1.0, "position"), math.sqrt(7), rel_tol=1e-9)


def test_atr_targets_long_short_neutral():
    long = hz.atr_targets(100.0, 1.0, "intraday", "long")
    assert long["target"] > 100.0 > long["stop"]
    assert long["target_pct"] > 0 and long["stop_pct"] < 0
    assert long["rr"] == 1.5

    short = hz.atr_targets(100.0, 1.0, "intraday", "short")
    assert short["target"] < 100.0 < short["stop"]

    flat = hz.atr_targets(100.0, 1.0, "intraday", "neutral")
    assert flat["target"] is None and flat["rr"] is None

    no_atr = hz.atr_targets(100.0, None, "swing", "long")
    assert no_atr["target"] is None


def test_longer_horizon_gives_a_wider_target():
    intraday = hz.atr_targets(100.0, 1.0, "intraday", "long")
    position = hz.atr_targets(100.0, 1.0, "position", "long")
    long_h = hz.atr_targets(100.0, 1.0, "long", "long")
    # Both the √bars scale and the widened multiplier push the target out.
    assert position["target_pct"] > intraday["target_pct"]
    assert long_h["target_pct"] > position["target_pct"]


def test_allows_blocks_funds_intraday_only():
    assert hz.allows("intraday", "crypto") is True
    assert hz.allows("intraday", "fund") is False
    assert hz.allows("swing", "fund") is True
    assert hz.allows("position", "fund") is True


# ── signal engine honours the bucket ─────────────────────────────────────────


def test_signal_target_widens_with_horizon_same_candles():
    closes = [100.0 * (1.01 ** i) for i in range(60)]
    intraday = compute_short_term_signal(_candles(closes, spread=0.5), bucket="intraday")
    position = compute_short_term_signal(_candles(closes, spread=0.5), bucket="position")
    assert intraday["direction"] == position["direction"] == "long"
    # Same signal, longer horizon → the target sits further from entry.
    assert abs(position["target_pct"]) > abs(intraday["target_pct"])
    assert position["horizon_hours"] == 168
    assert intraday["horizon_hours"] == 4


def test_default_bucket_matches_legacy_4h_output():
    closes = [100.0 * (1.01 ** i) for i in range(60)]
    default = compute_short_term_signal(_candles(closes, spread=0.5))
    intraday = compute_short_term_signal(_candles(closes, spread=0.5), bucket="intraday")
    assert default["target"] == intraday["target"]
    assert default["horizon_hours"] == 4
    # Back-compat alias still present for the existing frontend.
    assert default["atr_4h"] == default["horizon_atr"]
