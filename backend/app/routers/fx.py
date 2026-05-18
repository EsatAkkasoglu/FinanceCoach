"""FX rates route: live currency conversion rates via ExchangeRate-API.

Returns rates relative to a base currency. Cached in-process for 15 minutes.
Source: open.er-api.com (free tier, no key required, updated every 24h).
"""
from __future__ import annotations

import logging
import time
from threading import Lock
from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

log = logging.getLogger("fincoach.fx")

router = APIRouter(tags=["fx"])

Currency = Literal["TRY", "USD", "EUR"]
SUPPORTED: tuple[Currency, ...] = ("TRY", "USD", "EUR")
TTL_SECONDS = 15 * 60

# base -> {ccy: rate, fetched_at: float}
_cache: dict[str, tuple[dict[str, float], float]] = {}
_cache_lock = Lock()


class FxRates(BaseModel):
    base: str
    rates: dict[str, float]
    fetched_at: float  # unix seconds


def _fetch_from_api(base: str) -> dict[str, float]:
    """Fetch all rates for `base` from open.er-api.com."""
    url = f"https://open.er-api.com/v6/latest/{base}"
    resp = httpx.get(url, timeout=8)
    resp.raise_for_status()
    data = resp.json()
    if data.get("result") != "success":
        raise RuntimeError(f"ExchangeRate-API error: {data}")
    all_rates: dict[str, float] = data["rates"]
    return {ccy: all_rates[ccy] for ccy in SUPPORTED if ccy in all_rates}


def _get_rates(base: str) -> tuple[dict[str, float], float]:
    now = time.time()
    with _cache_lock:
        hit = _cache.get(base)
        if hit and now - hit[1] < TTL_SECONDS:
            return hit
    rates = _fetch_from_api(base)
    rates[base] = 1.0  # always exact
    fetched_at = time.time()
    with _cache_lock:
        _cache[base] = (rates, fetched_at)
    return rates, fetched_at


@router.get("/fx/rates", response_model=FxRates)
def get_fx_rates(base: str = Query("TRY")):
    base = base.upper()
    if base not in SUPPORTED:
        raise HTTPException(400, f"Unsupported base currency '{base}'. Supported: {list(SUPPORTED)}")

    try:
        rates, fetched_at = _get_rates(base)
    except Exception as exc:
        raise HTTPException(502, f"FX provider unavailable: {exc}") from exc

    return FxRates(base=base, rates=rates, fetched_at=fetched_at)


def _reset_cache_for_tests() -> None:
    with _cache_lock:
        _cache.clear()
