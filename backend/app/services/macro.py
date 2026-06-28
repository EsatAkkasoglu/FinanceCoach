"""Macro / regime context feeds — Crypto Fear & Greed + FRED.

Gives the signal engine a market-regime read beyond the VIX. Everything degrades
gracefully: a missing key or a dead endpoint yields ``None`` (neutral), never an
exception, so a signal still computes from price-action alone.

  • Crypto Fear & Greed (alternative.me) — KEYLESS, 0–100 (fear → greed).
  • FRED (St. Louis Fed) — needs a free ``FRED_API_KEY``: the 10y–2y treasury
    curve (recession/risk signal) and the fed funds rate.

Pure mapping helpers (``fear_greed_score``, ``yield_curve_score``) are unit-tested
without network; the fetchers are best-effort and cached.
"""
from __future__ import annotations

import logging
import time
from typing import Any

import requests

from app.settings import settings

log = logging.getLogger("fincoach.macro")

_FNG_URL = "https://api.alternative.me/fng/"
_FRED_URL = "https://api.stlouisfed.org/fred/series/observations"
_TIMEOUT = 8.0
_TTL = 30 * 60  # regime data moves slowly — 30 min cache

# Module-level TTL cache (regime feeds are global, not per-user — a process-wide
# cache is correct and cheap; the per-request ContextVar cache is the wrong tool).
_cache: dict[str, tuple[float, Any]] = {}


def _cache_get(key: str) -> Any | None:
    hit = _cache.get(key)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    return None


def _cache_set(key: str, value: Any) -> None:
    _cache[key] = (time.monotonic() + _TTL, value)


def _clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


# ── pure mappings (testable) ─────────────────────────────────────────────────


def fear_greed_score(value: float | None) -> float:
    """0–100 Fear & Greed → risk-on tilt in [-1, 1]. 50 = 0; greed positive,
    fear negative. Linear; the engine's own bands handle extremes."""
    if value is None:
        return 0.0
    return _clamp((value - 50.0) / 50.0)


def yield_curve_score(spread_10y2y: float | None) -> float:
    """10y–2y treasury spread → regime tilt in [-1, 1]. A deeply inverted curve
    (recession signal) is risk-off (negative); a steep curve is risk-on."""
    if spread_10y2y is None:
        return 0.0
    # ±1.0 percentage-point spread ≈ full tilt; inversion (<0) is bearish.
    return _clamp(spread_10y2y / 1.0)


# ── fetchers (best-effort, cached) ───────────────────────────────────────────


def crypto_fear_greed() -> dict[str, Any] | None:
    """Latest crypto Fear & Greed index (keyless). None on failure."""
    cached = _cache_get("macro:fng")
    if isinstance(cached, dict):
        return cached
    try:
        r = requests.get(_FNG_URL, params={"limit": 1}, timeout=_TIMEOUT)
        r.raise_for_status()
        row = (r.json().get("data") or [])[0]
        out = {
            "value": int(row["value"]),
            "classification": row.get("value_classification"),
            "score": fear_greed_score(int(row["value"])),
        }
        _cache_set("macro:fng", out)
        return out
    except Exception as exc:  # noqa: BLE001 — best-effort regime feed
        log.info("crypto fear & greed unavailable: %s", exc)
        return None


def _fred_latest(series_id: str) -> float | None:
    if not settings.fred_api_key:
        return None
    cache_key = f"macro:fred:{series_id}"
    cached = _cache_get(cache_key)
    if isinstance(cached, int | float):
        return float(cached)
    try:
        r = requests.get(
            _FRED_URL,
            params={
                "series_id": series_id, "api_key": settings.fred_api_key,
                "file_type": "json", "sort_order": "desc", "limit": 1,
            },
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        obs = (r.json().get("observations") or [])
        for o in obs:  # FRED uses "." for missing values
            if o.get("value") not in (None, "", "."):
                val = float(o["value"])
                _cache_set(cache_key, val)
                return val
    except Exception as exc:  # noqa: BLE001
        log.info("FRED series %s unavailable: %s", series_id, exc)
    return None


def yield_curve_10y2y() -> float | None:
    """10y–2y treasury spread in percentage points (FRED ``T10Y2Y``)."""
    return _fred_latest("T10Y2Y")


def macro_regime() -> dict[str, Any]:
    """Blended macro-regime read in [-1, 1] from Fear & Greed + the yield curve.

    Returns the blended ``score`` plus the components, all best-effort. Used to
    deepen the equity signal's confirmation slot (StockBench: regime is decisive
    between passing in bull markets and failing in bear ones)."""
    fng = crypto_fear_greed()
    curve = yield_curve_10y2y()
    fng_score = fng["score"] if fng else 0.0
    curve_score = yield_curve_score(curve)
    # The curve is a slow, structural risk signal; F&G is a fast sentiment read.
    score = _clamp(0.5 * curve_score + 0.5 * fng_score)
    return {
        "score": round(score, 3),
        "fear_greed": fng.get("value") if fng else None,
        "fear_greed_score": round(fng_score, 3),
        "yield_curve_10y2y": curve,
        "yield_curve_score": round(curve_score, 3),
    }
