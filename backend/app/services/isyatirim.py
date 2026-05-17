"""İş Yatırım (isyatirim.com.tr) public JSON endpoint wrapper.

Used as a last-resort fallback for BIST tickers (e.g. THYAO.IS) where:
  • Alpha Vantage has no coverage (US-only).
  • Yahoo Finance occasionally returns 401/empty for Turkish symbols.

The HisseTekil endpoint is the same one isyatirim.com.tr's own charts use.
No API key, no rate limit, returns daily OHLC + close.

Format:
  https://www.isyatirim.com.tr/_layouts/15/Isyatirim.Website/Common/
    Data.aspx/HisseTekil?hisse=THYAO&startdate=01-05-2026&enddate=18-05-2026.json

Response shape:
  {"value": [{"HGDG_HS_KODU": "THYAO", "HGDG_TARIH": "17-05-2026",
              "HGDG_KAPANIS": 303.5, "HGDG_MIN": 301.0, "HGDG_MAX": 305.5,
              "HGDG_HACIM": 12345678, ...}, ...]}
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Any

log = logging.getLogger("fincoach.isyatirim")

_cache: dict[str, tuple[float, Any]] = {}
_cache_lock = threading.Lock()
_QUOTE_TTL = 60
_HIST_TTL = 6 * 3600

_BASE = (
    "https://www.isyatirim.com.tr/_layouts/15/Isyatirim.Website/"
    "Common/Data.aspx/HisseTekil"
)


class IsYatirimError(RuntimeError):
    """Raised when İş Yatırım returns no data or errors out."""


def _strip_suffix(symbol: str) -> str:
    """THYAO.IS → THYAO. İş Yatırım uses bare tickers."""
    return symbol.upper().removesuffix(".IS").removesuffix(".E")


def _cache_get(key: str, ttl: int) -> Any | None:
    with _cache_lock:
        hit = _cache.get(key)
    if not hit:
        return None
    fetched_at, value = hit
    return value if time.time() - fetched_at < ttl else None


def _cache_set(key: str, value: Any) -> None:
    with _cache_lock:
        _cache[key] = (time.time(), value)


def _fetch(symbol: str, days: int = 7) -> list[dict[str, Any]]:
    """Raw HisseTekil call for the last `days` calendar days."""
    import requests  # noqa: PLC0415

    end = datetime.utcnow().date()
    start = end - timedelta(days=days)
    params = {
        "hisse": _strip_suffix(symbol),
        "startdate": start.strftime("%d-%m-%Y"),
        "enddate": end.strftime("%d-%m-%Y") + ".json",
    }
    try:
        r = requests.get(_BASE, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
    except Exception as exc:  # noqa: BLE001
        raise IsYatirimError(f"İş Yatırım request failed for {symbol}: {exc}") from exc

    rows = data.get("value") or []
    if not rows:
        raise IsYatirimError(f"İş Yatırım returned no rows for {symbol}")
    return rows


def quote(symbol: str) -> dict[str, Any]:
    """Latest close and previous close for a BIST ticker."""
    key = f"iy:quote:{symbol.upper()}"
    cached = _cache_get(key, _QUOTE_TTL)
    if cached:
        return cached

    rows = _fetch(symbol, days=10)
    # Endpoint returns oldest-first; take the last two.
    if len(rows) < 1:
        raise IsYatirimError(f"İş Yatırım has no recent bars for {symbol}")
    latest = rows[-1]
    prev = rows[-2] if len(rows) > 1 else latest

    try:
        price = float(latest["HGDG_KAPANIS"])
        prev_close = float(prev["HGDG_KAPANIS"])
    except (KeyError, TypeError, ValueError) as exc:
        raise IsYatirimError(f"İş Yatırım malformed payload for {symbol}: {exc}") from exc

    result = {
        "price": round(price, 4),
        "previous_close": round(prev_close, 4),
        "currency": "TRY",
        "volume": int(latest.get("HGDG_HACIM") or 0) or None,
        "as_of": str(latest.get("HGDG_TARIH") or ""),
        "source": "isyatirim",
    }
    _cache_set(key, result)
    return result
