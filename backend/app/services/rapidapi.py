"""RapidAPI-backed crypto metadata — universe selection and an independent price check.

RapidAPI bills each API separately: a valid key still returns
``403 {"message": "You are not subscribed to this API."}`` for any API the
account has not subscribed to. Every function here therefore degrades to an
empty result rather than raising, and :func:`probe` reports exactly which APIs
are live so a run can say what it had rather than silently doing less.

Verified working on this account:
  * **coinranking1** — market-cap ranking and 24h trending. Used to build the
    experiment's coin universe from data instead of from my own guess.
  * **alpha-vantage** — daily equities plus ``CRYPTO_INTRADAY``. Rate-limited
    hard (bursts are rejected), so it is used as an independent cross-check on
    a handful of bars, never as the primary candle feed.

Verified NOT usable: ``fast-price-exchange-rates``, ``coingecko``,
``economics-news-rss`` (not subscribed); ``realtime-crypto-prices-api`` (times
out); ``coindesk-api1`` (returns 500 from its own upstream).
"""
from __future__ import annotations

import logging
import os
from typing import Any

import requests

log = logging.getLogger("fincoach.rapidapi")

_TIMEOUT = 25

#: Coins whose price is pinned by design — including them in a momentum or
#: mean-reversion study measures the peg, not the market.
STABLECOINS = {
    "USDT", "USDC", "USDS", "DAI", "BUSD", "TUSD", "FDUSD", "USDE", "PYUSD",
    "USDD", "FRAX", "LUSD", "USD1", "EURC", "USDF",
}

#: Wrapped / staked derivatives track their underlying almost exactly, so they
#: add correlated duplicates rather than independent evidence.
_DERIVATIVE_PREFIXES = ("W", "ST", "CB", "RETH", "WSTETH", "WEETH")
_DERIVATIVE_EXACT = {"WBTC", "WETH", "STETH", "WSTETH", "WEETH", "WBETH", "CBBTC", "RETH", "LBTC"}


def api_key() -> str:
    """Key from the environment, falling back to backend/.env via settings.

    Scripts run outside the FastAPI process do not get .env loaded for free, so
    read the environment first (cheap, and lets a run override) and only then
    pay for the settings import.
    """
    env = os.environ.get("RAPIDAPI_KEY", "").strip()
    if env:
        return env
    try:
        from app.settings import settings  # noqa: PLC0415 — avoid import at module load

        return (settings.rapidapi_key or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def _get(host: str, path: str, params: dict[str, Any] | None = None) -> Any | None:
    key = api_key()
    if not key:
        return None
    try:
        r = requests.get(
            f"https://{host}{path}", params=params or {}, timeout=_TIMEOUT,
            headers={
                "Content-Type": "application/json",
                "x-rapidapi-host": host,
                "x-rapidapi-key": key,
            },
        )
    except Exception as exc:  # noqa: BLE001 — an unreachable vendor is not an error here
        log.info("rapidapi %s%s unreachable: %s", host, path, type(exc).__name__)
        return None
    if r.status_code != 200:
        log.info("rapidapi %s%s -> %s", host, path, r.status_code)
        return None
    try:
        return r.json()
    except ValueError:
        return None


# ── coinranking: the coin universe ───────────────────────────────────────────


def top_coins(limit: int = 30) -> list[dict[str, Any]]:
    """Coins by market cap, newest data, stablecoins and wrappers removed."""
    payload = _get(
        "coinranking1.p.rapidapi.com", "/coins",
        {"limit": max(limit * 3, 50), "orderBy": "marketCap", "orderDirection": "desc"},
    )
    coins = ((payload or {}).get("data") or {}).get("coins") or []
    out: list[dict[str, Any]] = []
    for c in coins:
        symbol = str(c.get("symbol") or "").upper()
        if not symbol or symbol in STABLECOINS or symbol in _DERIVATIVE_EXACT:
            continue
        try:
            out.append({
                "symbol": symbol,
                "name": c.get("name"),
                "rank": int(c.get("rank") or 0),
                "market_cap": float(c.get("marketCap") or 0.0),
                "price": float(c.get("price") or 0.0),
                "change_24h_pct": float(c.get("change") or 0.0),
                "volume_24h": float(c.get("24hVolume") or 0.0),
                "low_volume": bool(c.get("lowVolume")),
            })
        except (TypeError, ValueError):
            continue
        if len(out) >= limit:
            break
    return out


def trending_coins(limit: int = 20) -> list[str]:
    """24h trending symbols. Informational only — see the warning below.

    Trending lists are dominated by micro-caps that just printed a large move.
    Selecting a trading universe from them is momentum-chasing with survivorship
    baked in, so the experiment records this alongside its results rather than
    trading on it.
    """
    payload = _get(
        "coinranking1.p.rapidapi.com", "/coins/trending",
        {"referenceCurrencyUuid": "yhjMzLPhuIDl", "timePeriod": "24h",
         "limit": limit, "offset": 0},
    )
    coins = ((payload or {}).get("data") or {}).get("coins") or []
    return [str(c.get("symbol") or "").upper() for c in coins if c.get("symbol")]


def liquid_universe(n: int = 8, min_volume_usd: float = 50_000_000.0) -> list[str]:
    """The experiment's coin universe, chosen by market cap and 24h volume.

    Picking coins by hand bakes the author's priors into the result. Ranking by
    market cap is not neutral either — it is a rule, but at least a stated one,
    and it is the same rule every cycle rather than a fresh guess.
    """
    coins = [
        c for c in top_coins(limit=n * 4)
        if c["volume_24h"] >= min_volume_usd and not c["low_volume"]
    ]
    return [c["symbol"] for c in coins[:n]]


# ── alpha-vantage: independent cross-check ───────────────────────────────────


def crypto_intraday_close(symbol: str, interval: str = "15min") -> float | None:
    """Latest close from a vendor unrelated to the exchange feed.

    Used to sanity-check the primary candle source. If two independent vendors
    disagree by more than a fraction of a percent, the data is wrong somewhere
    and no amount of careful backtesting will fix that.
    """
    payload = _get(
        "alpha-vantage.p.rapidapi.com", "/query",
        {"function": "CRYPTO_INTRADAY", "symbol": symbol.upper(),
         "market": "USD", "interval": interval, "outputsize": "compact"},
    )
    if not isinstance(payload, dict):
        return None
    series_key = next((k for k in payload if k.startswith("Time Series")), None)
    if not series_key:
        return None   # rate-limit or informational payload, not data
    series = payload.get(series_key) or {}
    if not series:
        return None
    newest = max(series)
    try:
        return float(series[newest].get("4. close"))
    except (TypeError, ValueError, AttributeError):
        return None


def probe() -> dict[str, Any]:
    """Which RapidAPI endpoints this key can actually reach right now."""
    if not api_key():
        return {"key_present": False}
    return {
        "key_present": True,
        "coinranking_coins": bool(top_coins(limit=3)),
        "coinranking_trending": bool(trending_coins(limit=3)),
        "alpha_vantage_crypto": crypto_intraday_close("BTC") is not None,
    }
