"""Perpetual funding rates — the cost the engine used to pretend was zero.

Why this module exists: ``backtest.Costs.funding_bps_per_bar`` defaulted to 0,
so every long/short result in this repo was priced as if carrying a perp
position were free. An adversarial audit called that out as the single
largest un-modelled friction in a short-heavy book, and it was right.

Two things are easy to get wrong and are handled explicitly here.

**Sign.** Funding is not a fee — it is a transfer. A POSITIVE rate means longs
pay shorts. So the P&L impact of holding position ``p`` through a funding
stamp with rate ``f`` is ``-p * f``: a long bleeds when funding is positive
and *earns* when it is negative, and a short is the mirror. Charging
``|p| * f`` (the old, unsigned carry) is wrong in both directions at once — it
overcharges the side that should be receiving and understates nothing.

**Alignment.** Funding settles at discrete stamps (OKX: 00:00/08:00/16:00 UTC),
not every bar. Spreading a rate evenly across the bars of its interval would
let a position that closes before the stamp still pay it. Here the whole
charge lands on the single bar containing the stamp — the position must
actually be open at settlement to be charged, which is how the venue works.

Source: OKX ``/api/v5/public/funding-rate-history`` (keyless). Binance's
futures API returns 451 from this environment and Bybit 403, so OKX is the
only reachable venue; its rate is used for every symbol regardless of which
venue supplied the candles, and that mismatch is recorded rather than hidden.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

import numpy as np
import requests

log = logging.getLogger("fincoach.quant.funding")

_URL = "https://www.okx.com/api/v5/public/funding-rate-history"
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; FinCoachQuant/1.0)"}
_TIMEOUT = 25

CACHE_DIR = os.environ.get(
    "FINCOACH_FUNDING_CACHE",
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "funding"),
)


class FundingError(RuntimeError):
    """No usable funding history for this symbol."""


def _cache_path(symbol: str) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, f"{symbol.upper()}.json")


def fetch_funding(symbol: str, pages: int = 8, *, use_cache: bool = True) -> dict[str, Any]:
    """``{"ts": [...], "rate": [...]}`` — settlement stamps, oldest first.

    When ``FINCOACH_FROZEN_DATA`` is set the snapshot is the only source, in
    the same all-or-nothing way as :func:`exchange.fetch_candles`: a
    comparison is not controlled if half its inputs can move underneath it.
    """
    frozen = os.environ.get("FINCOACH_FROZEN_DATA")
    if frozen:
        path = os.path.join(frozen, "funding", f"{symbol.upper()}.json")
        if not os.path.exists(path):
            raise FundingError(
                f"frozen data layer has no funding for {symbol.upper()} "
                "— frozen mode never falls back to the network"
            )
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    cached: dict[int, float] = {}
    if use_cache and os.path.exists(_cache_path(symbol)):
        try:
            with open(_cache_path(symbol), encoding="utf-8") as fh:
                blob = json.load(fh)
            cached = dict(zip(blob["ts"], blob["rate"], strict=True))
        except Exception as exc:  # noqa: BLE001 — a bad cache must not stop a run
            log.info("funding cache unreadable for %s: %s", symbol, exc)

    inst = f"{symbol.upper()}-USDT-SWAP"
    cursor: int | None = None
    for _ in range(max(1, pages)):
        params: dict[str, Any] = {"instId": inst, "limit": 100}
        if cursor:
            params["after"] = str(cursor)
        try:
            r = requests.get(_URL, params=params, headers=_HEADERS, timeout=_TIMEOUT)
            r.raise_for_status()
            data = r.json().get("data") or []
        except Exception as exc:  # noqa: BLE001
            log.info("funding fetch failed for %s: %s", symbol, exc)
            break
        if not data:
            break
        for row in data:
            cached[int(row["fundingTime"])] = float(row["fundingRate"])
        cursor = int(data[-1]["fundingTime"])
        time.sleep(0.2)

    if not cached:
        raise FundingError(f"no funding history for {symbol}")

    ts = sorted(cached)
    out = {"symbol": symbol.upper(), "source": "okx", "ts": ts, "rate": [cached[t] for t in ts]}
    if use_cache:
        with open(_cache_path(symbol), "w", encoding="utf-8") as fh:
            json.dump(out, fh)
    return out


def per_bar_funding(bar_ts: np.ndarray, funding: dict[str, Any]) -> np.ndarray:
    """Funding rate charged on each bar — zero except where a stamp lands.

    ``bar_ts`` are bar OPEN times. A stamp at time ``s`` is assigned to the bar
    whose interval contains it, i.e. the last bar with ``open <= s``. Bars with
    no stamp carry nothing, so a position that opens and closes between two
    settlements pays no funding at all — which is exactly right, and is the
    property a naive per-bar average would destroy.

    Returned as a RATE (not bps), signed as the venue publishes it: positive
    means longs pay.
    """
    ts = np.asarray(bar_ts, dtype=np.int64)
    out = np.zeros(ts.size, dtype=float)
    stamps = np.asarray(funding.get("ts") or [], dtype=np.int64)
    rates = np.asarray(funding.get("rate") or [], dtype=float)
    if ts.size == 0 or stamps.size == 0:
        return out
    # searchsorted with side="right" gives the count of bars starting at or
    # before the stamp; minus one is that bar's index.
    idx = np.searchsorted(ts, stamps, side="right") - 1
    keep = (idx >= 0) & (idx < ts.size)
    np.add.at(out, idx[keep], rates[keep])   # add: a bar may span two stamps
    return out


def summary(funding: dict[str, Any]) -> dict[str, Any]:
    """Descriptive stats — used to report the regime rather than assume it."""
    r = np.asarray(funding.get("rate") or [], dtype=float)
    if r.size == 0:
        return {"n": 0}
    return {
        "n": int(r.size),
        "median_pct_per_8h": round(float(np.median(r)) * 100.0, 6),
        "mean_pct_per_8h": round(float(np.mean(r)) * 100.0, 6),
        "negative_fraction": round(float(np.mean(r < 0)), 4),
        "annualised_pct": round(float(np.mean(r)) * 3 * 365 * 100.0, 3),
        "first_ts": int(funding["ts"][0]),
        "last_ts": int(funding["ts"][-1]),
    }
