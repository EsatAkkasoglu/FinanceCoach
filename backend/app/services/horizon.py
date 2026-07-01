"""Canonical trade-horizon model — one source of truth for the strategist,
the signal engine and the order layer.

The user can ask about any holding horizon ("next few hours", "this week",
"over a couple of months"). We bucket that intent into four canonical horizons,
each mapping to:

  • a canonical hour count          (drives the TradeTarget expiry)
  • the technical bar granularity   (intraday uses 1h bars; position/long use 1d)
  • ATR target/stop geometry        (entry ± mult · horizon-ATR, R:R ≈ 1.5)

Why the ATR multiplier WIDENS with horizon instead of √T-scaling a single base
ATR: the square-root-of-time rule systematically *underestimates* risk at longer
horizons under fat tails, jumps and autocorrelation (Danielsson & Zigrand 2006,
https://researchonline.lse.ac.uk/24827/). So each bucket carries both a √T scale
(``horizon_atr = per_bar_atr · √bars``) AND a multiplier that grows faster than
√T — the extra widening is the explicit fat-tail premium a longer hold demands.

Pure module: no network, no DB — safe to import from tools, services and agents.
"""
from __future__ import annotations

import math
import re
from typing import Any

DEFAULT_BUCKET = "swing"

# bars: preferred technical granularity; bar_hours: its length in hours;
# atr_mult_target / atr_mult_stop: R-defined geometry on the horizon ATR.
# R:R ≈ 1.5 across all buckets (1.5/1.0, 2.0/1.3, 3.0/2.0, 4.0/2.7).
HORIZON_BUCKETS: dict[str, dict[str, Any]] = {
    "intraday": {
        "hours": 4, "bars": "1h", "bar_hours": 1, "fallback_bars": "1d",
        "atr_mult_target": 1.5, "atr_mult_stop": 1.0,
        "allows": ("crypto", "stock", "etf"),
    },
    "swing": {
        "hours": 24, "bars": "1h", "bar_hours": 1, "fallback_bars": "1d",
        "atr_mult_target": 2.0, "atr_mult_stop": 1.3,
        "allows": ("crypto", "stock", "etf", "fund"),
    },
    "position": {
        "hours": 168, "bars": "1d", "bar_hours": 24, "fallback_bars": "1d",
        "atr_mult_target": 3.0, "atr_mult_stop": 2.0,
        "allows": ("crypto", "stock", "etf", "fund"),
    },
    "long": {
        "hours": 720, "bars": "1d", "bar_hours": 24, "fallback_bars": "1wk",
        "atr_mult_target": 4.0, "atr_mult_stop": 2.7,
        "allows": ("crypto", "stock", "etf", "fund"),
    },
}

# Keyword → bucket, for the LLM-unavailable fallback only (the strategist
# normally extracts the horizon as a structured field). EN + TR + generic.
# Order matters: explicit week/month words win first; intraday is checked BEFORE
# swing so "gün içi"/"scalp" beat swing's bare "gün". (The strategist LLM is the
# real path — this only fires when the LLM is down.)
_KEYWORD_BUCKETS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(\d+\s*)?(month|months|ay|aylık|aylik|çeyrek|quarter|yıl|yil|year)\b", re.I), "long"),
    (re.compile(r"\b(\d+\s*)?(week|weeks|hafta|haftalık|haftalik)\b", re.I), "position"),
    (re.compile(r"(intraday|scalp|gün içi|gun ici|day trade|\b(\d+\s*)?(hour|hours|saat|saatlik)\b|\b(today|bugün|bugun)\b)", re.I), "intraday"),
    (re.compile(r"\b(swing|few days|couple of days|gün|gunluk|günlük|daily)\b", re.I), "swing"),
]


def resolve(bucket: str | None) -> dict[str, Any]:
    """Return the full spec dict (with ``name``) for a bucket; default to swing."""
    name = bucket if bucket in HORIZON_BUCKETS else DEFAULT_BUCKET
    return {"name": name, **HORIZON_BUCKETS[name]}


def bucket_for_hours(hours: int | float | None) -> str:
    """Nearest canonical bucket for an arbitrary hour count (None → default)."""
    if hours is None:
        return DEFAULT_BUCKET
    return min(HORIZON_BUCKETS, key=lambda b: abs(HORIZON_BUCKETS[b]["hours"] - hours))


def keyword_bucket(text: str | None) -> str | None:
    """Cheap horizon guess from free text — fallback when the LLM is unavailable."""
    if not text:
        return None
    for pattern, bucket in _KEYWORD_BUCKETS:
        if pattern.search(text):
            return bucket
    return None


def allows(bucket: str, asset_class: str) -> bool:
    """Is this asset class tradable at this horizon? (Funds have no intraday NAV.)"""
    return asset_class in resolve(bucket)["allows"]


def horizon_atr(per_bar_atr: float, bucket: str) -> float:
    """Scale a per-bar ATR up to the horizon via √(bars-in-horizon).

    e.g. intraday (4h on 1h bars) → √4 = 2× the hourly ATR, reproducing the
    original 4-hour engine exactly. The fat-tail premium lives in the multiplier,
    not here.
    """
    spec = resolve(bucket)
    bars_in_horizon = max(1.0, spec["hours"] / spec["bar_hours"])
    return per_bar_atr * math.sqrt(bars_in_horizon)


def atr_targets(
    price: float, per_bar_atr: float | None, bucket: str, direction: str
) -> dict[str, Any]:
    """Entry/target/stop geometry for a horizon. Neutral or no-ATR → flat plan.

    Returns a dict with target/stop/target_pct/stop_pct/rr/horizon_atr (all None
    when there is no tradable level). Reward:risk is fixed per bucket (≈ 1.5).
    """
    spec = resolve(bucket)
    out: dict[str, Any] = {
        "target": None, "stop": None, "target_pct": None, "stop_pct": None,
        "rr": None, "horizon_atr": None, "horizon_atr_pct": None,
    }
    if not per_bar_atr or direction == "neutral" or not price:
        return out
    h_atr = horizon_atr(per_bar_atr, bucket)
    mt, ms = spec["atr_mult_target"], spec["atr_mult_stop"]
    if direction == "long":
        target = price + mt * h_atr
        stop = price - ms * h_atr
    else:  # short
        target = price - mt * h_atr
        stop = price + ms * h_atr
    out.update(
        target=round(target, 6),
        stop=round(stop, 6),
        target_pct=round((target / price - 1.0) * 100.0, 2),
        stop_pct=round((stop / price - 1.0) * 100.0, 2),
        rr=round(mt / ms, 2),
        horizon_atr=round(h_atr, 6),
        horizon_atr_pct=round(h_atr / price * 100.0, 2),
    )
    return out
