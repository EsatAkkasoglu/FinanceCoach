"""Finnhub — optional equity quote + news backstop (free 60/min).

Graceful: with no ``FINNHUB_API_KEY`` every call returns ``None`` so callers fall
back to yfinance. A real-time equity quote and per-ticker news that don't depend
on the (unofficial, occasionally flaky) yfinance scrape.
"""
from __future__ import annotations

import logging
import time
from typing import Any

import requests

from app.settings import settings

log = logging.getLogger("fincoach.finnhub")

_BASE = "https://finnhub.io/api/v1"
_TIMEOUT = 8.0
_TTL = 5 * 60
_cache: dict[str, tuple[float, Any]] = {}


def available() -> bool:
    return bool(settings.finnhub_api_key)


def _get(path: str, params: dict[str, Any]) -> Any | None:
    if not settings.finnhub_api_key:
        return None
    key = f"{path}:{sorted(params.items())}"
    hit = _cache.get(key)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    try:
        r = requests.get(
            f"{_BASE}{path}", params={**params, "token": settings.finnhub_api_key}, timeout=_TIMEOUT
        )
        r.raise_for_status()
        data = r.json()
        _cache[key] = (time.monotonic() + _TTL, data)
        return data
    except Exception as exc:  # noqa: BLE001 — optional backstop, never block
        log.info("finnhub %s unavailable: %s", path, exc)
        return None


def quote(symbol: str) -> dict[str, Any] | None:
    """Real-time quote. None when no key / no data."""
    d = _get("/quote", {"symbol": symbol.upper()})
    if not isinstance(d, dict) or not d.get("c"):
        return None
    return {
        "symbol": symbol.upper(),
        "price": d.get("c"),
        "change_pct": d.get("dp"),
        "high": d.get("h"),
        "low": d.get("l"),
        "prev_close": d.get("pc"),
        "source": "finnhub",
    }


def company_news(symbol: str, days: int = 7) -> list[dict[str, Any]] | None:
    """Recent company news headlines (most recent first). None when no key."""
    from datetime import UTC, datetime, timedelta
    today = datetime.now(UTC).date()
    d = _get("/company-news", {
        "symbol": symbol.upper(),
        "from": (today - timedelta(days=days)).isoformat(),
        "to": today.isoformat(),
    })
    if not isinstance(d, list):
        return None
    return [
        {"title": a.get("headline"), "source": a.get("source"), "url": a.get("url"), "summary": (a.get("summary") or "")[:240]}
        for a in d[:8]
        if isinstance(a, dict)
    ]
