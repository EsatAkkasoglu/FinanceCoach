"""Alpha Vantage HTTP client.

Single entry point for every AV REST call. Handles:
  * API-key injection (from ``settings.alphavantage_api_key``)
  * yfinance-style ticker normalization (``^GSPC`` → ``SPX``, ``BTC-USD`` →
    crypto pair, ``EURUSD=X`` → forex pair, ``GC=F`` → ETF proxy fallback)
  * In-process TTL cache to survive the free-tier 25 req/day limit
  * AV's "Note"/"Information" rate-limit messages surfaced as Python errors
  * Common error shape so downstream tools can ``.get("error")``

All public helpers return plain ``dict``s with snake_case keys mapped from
AV's quirky JSON (numbered keys like ``"05. price"`` → ``price``).
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

import requests

from app.settings import settings

log = logging.getLogger("fincoach.alpha_vantage")

_BASE_URL = "https://www.alphavantage.co/query"
_DEFAULT_TIMEOUT = 10

# Per-endpoint TTL (seconds). Market-hour quotes refresh quickly; fundamentals
# barely move day-to-day, so cache aggressively to spare the rate limit.
_TTL: dict[str, int] = {
    "GLOBAL_QUOTE": 60,
    "CURRENCY_EXCHANGE_RATE": 60,
    "TIME_SERIES_DAILY": 6 * 3600,
    "DIGITAL_CURRENCY_DAILY": 6 * 3600,
    "FX_DAILY": 6 * 3600,
    "TREASURY_YIELD": 12 * 3600,
    "OVERVIEW": 24 * 3600,
    "EARNINGS": 24 * 3600,
    "DIVIDENDS": 24 * 3600,
    "TOP_GAINERS_LOSERS": 5 * 60,
    "NEWS_SENTIMENT": 15 * 60,
    "SMA": 6 * 3600,
    "RSI": 6 * 3600,
    "SYMBOL_SEARCH": 24 * 3600,
}
_DEFAULT_TTL = 10 * 60

_cache: dict[str, tuple[float, Any]] = {}
_cache_lock = threading.Lock()


def _cache_get(key: str, ttl: int) -> Any | None:
    with _cache_lock:
        hit = _cache.get(key)
    if hit is None:
        return None
    fetched_at, value = hit
    if time.time() - fetched_at > ttl:
        return None
    return value


def _cache_set(key: str, value: Any) -> None:
    with _cache_lock:
        _cache[key] = (time.time(), value)


class AlphaVantageError(RuntimeError):
    """Raised on transport / rate-limit / unknown-symbol errors."""


def _check_payload(payload: dict[str, Any], function: str) -> dict[str, Any]:
    """AV returns HTTP 200 even on rate-limit / bad-symbol. Convert those to
    AlphaVantageError so callers see a single failure path."""
    if not isinstance(payload, dict):
        raise AlphaVantageError(f"{function}: unexpected non-dict response")
    if "Note" in payload:
        raise AlphaVantageError(f"AV rate limit: {payload['Note']}")
    if "Information" in payload:
        # AV uses this for premium-only endpoints AND for daily-quota-exceeded.
        raise AlphaVantageError(f"AV info: {payload['Information']}")
    if "Error Message" in payload:
        raise AlphaVantageError(f"AV error: {payload['Error Message']}")
    return payload


def _request(function: str, params: dict[str, Any], ttl: int | None = None) -> dict[str, Any]:
    """Issue a GET to AV with caching + error normalization."""
    if not settings.alphavantage_api_key:
        raise AlphaVantageError("ALPHAVANTAGE_API_KEY not configured")

    cache_key = f"{function}:" + ":".join(f"{k}={v}" for k, v in sorted(params.items()))
    effective_ttl = ttl if ttl is not None else _TTL.get(function, _DEFAULT_TTL)
    cached = _cache_get(cache_key, effective_ttl)
    if cached is not None:
        return cached

    query = {"function": function, **params, "apikey": settings.alphavantage_api_key}
    try:
        resp = requests.get(_BASE_URL, params=query, timeout=_DEFAULT_TIMEOUT)
        resp.raise_for_status()
        payload = resp.json()
    except requests.RequestException as exc:
        raise AlphaVantageError(f"{function} transport error: {exc}") from exc
    except ValueError as exc:
        raise AlphaVantageError(f"{function} bad JSON: {exc}") from exc

    payload = _check_payload(payload, function)
    _cache_set(cache_key, payload)
    return payload


# --- Ticker normalization --------------------------------------------------

# yfinance index conventions → AV symbols (no caret prefix; uses bare symbols)
_INDEX_MAP = {
    "^GSPC": "SPX",
    "^IXIC": "COMP",
    "^DJI": "DJI",
    "^NDX": "NDX",
    "^RUT": "RUT",
    "^VIX": "VIX",
    "^FTSE": "FTSE",
    "^N225": "N225",
    "^GDAXI": "DAX",
}

# yfinance Treasury yield tickers → AV TREASURY_YIELD maturity codes
_TREASURY_MAP = {
    "^TNX": "10year",
    "^TYX": "30year",
    "^IRX": "3month",
    "^FVX": "5year",
}

# yfinance commodity-futures continuous tickers → AV ETF proxies (AV has no
# direct futures endpoint on the free/standard tier).
_FUTURES_PROXY_MAP = {
    "GC=F": "GLD",
    "SI=F": "SLV",
    "CL=F": "USO",
    "NG=F": "UNG",
    "HG=F": "CPER",
}


def classify_ticker(ticker: str) -> dict[str, Any]:
    """Classify a yfinance-style ticker into ``(kind, normalized_symbol[, …])``
    so the rest of the layer can dispatch the right AV endpoint.

    kind: "stock" | "index" | "treasury" | "forex" | "crypto" | "futures_proxy"
    """
    t = (ticker or "").strip().upper()
    if not t:
        return {"kind": "unknown", "input": ticker}

    if t in _INDEX_MAP:
        return {"kind": "index", "symbol": _INDEX_MAP[t], "input": t}
    if t in _TREASURY_MAP:
        return {"kind": "treasury", "maturity": _TREASURY_MAP[t], "input": t}
    if t in _FUTURES_PROXY_MAP:
        return {"kind": "futures_proxy", "symbol": _FUTURES_PROXY_MAP[t], "input": t}

    # Crypto: BTC-USD style
    if "-" in t and t.endswith("-USD"):
        return {"kind": "crypto", "base": t.split("-")[0], "quote": "USD", "input": t}

    # Forex: EURUSD=X style (yfinance) or simple 6-letter pair
    if t.endswith("=X") and len(t) == 8:
        pair = t[:6]
        return {"kind": "forex", "from": pair[:3], "to": pair[3:], "input": t}

    # DX-Y.NYB → DXY proxy via UUP ETF (AV has no dollar index endpoint)
    if t in {"DX-Y.NYB", "DXY"}:
        return {"kind": "stock", "symbol": "UUP", "input": t, "proxy": True}

    # Anything else falls through as a stock symbol (handles XU100.IS, BABA, etc.)
    return {"kind": "stock", "symbol": t, "input": t}


# --- High-level wrappers ---------------------------------------------------


def global_quote(symbol: str) -> dict[str, Any]:
    """GLOBAL_QUOTE → flatten the ``Global Quote`` block to snake_case."""
    payload = _request("GLOBAL_QUOTE", {"symbol": symbol})
    block = payload.get("Global Quote") or payload.get("Realtime Global Securities Quote") or {}
    if not block:
        raise AlphaVantageError(f"GLOBAL_QUOTE empty for {symbol}")
    return {
        "symbol": block.get("01. symbol"),
        "open": _to_float(block.get("02. open")),
        "high": _to_float(block.get("03. high")),
        "low": _to_float(block.get("04. low")),
        "price": _to_float(block.get("05. price")),
        "volume": _to_int(block.get("06. volume")),
        "latest_trading_day": block.get("07. latest trading day"),
        "previous_close": _to_float(block.get("08. previous close")),
        "change": _to_float(block.get("09. change")),
        "change_percent": _to_change_pct(block.get("10. change percent")),
    }


def currency_exchange_rate(from_ccy: str, to_ccy: str) -> dict[str, Any]:
    payload = _request(
        "CURRENCY_EXCHANGE_RATE",
        {"from_currency": from_ccy, "to_currency": to_ccy},
    )
    block = payload.get("Realtime Currency Exchange Rate") or {}
    if not block:
        raise AlphaVantageError(f"CURRENCY_EXCHANGE_RATE empty for {from_ccy}/{to_ccy}")
    return {
        "from": block.get("1. From_Currency Code"),
        "to": block.get("3. To_Currency Code"),
        "rate": _to_float(block.get("5. Exchange Rate")),
        "last_refreshed": block.get("6. Last Refreshed"),
        "bid": _to_float(block.get("8. Bid Price")),
        "ask": _to_float(block.get("9. Ask Price")),
    }


def time_series_daily(symbol: str, outputsize: str = "compact") -> list[dict[str, Any]]:
    """Return list of {date, open, high, low, close, volume}, newest first."""
    payload = _request(
        "TIME_SERIES_DAILY",
        {"symbol": symbol, "outputsize": outputsize},
    )
    series = payload.get("Time Series (Daily)") or {}
    rows: list[dict[str, Any]] = []
    for date, bar in series.items():
        rows.append({
            "date": date,
            "open": _to_float(bar.get("1. open")),
            "high": _to_float(bar.get("2. high")),
            "low": _to_float(bar.get("3. low")),
            "close": _to_float(bar.get("4. close")),
            "volume": _to_int(bar.get("5. volume")),
        })
    rows.sort(key=lambda r: r["date"], reverse=True)
    return rows


def fx_daily(from_ccy: str, to_ccy: str) -> list[dict[str, Any]]:
    payload = _request("FX_DAILY", {"from_symbol": from_ccy, "to_symbol": to_ccy})
    series = payload.get("Time Series FX (Daily)") or {}
    rows = []
    for date, bar in series.items():
        rows.append({
            "date": date,
            "open": _to_float(bar.get("1. open")),
            "high": _to_float(bar.get("2. high")),
            "low": _to_float(bar.get("3. low")),
            "close": _to_float(bar.get("4. close")),
        })
    rows.sort(key=lambda r: r["date"], reverse=True)
    return rows


def digital_currency_daily(symbol: str, market: str = "USD") -> list[dict[str, Any]]:
    payload = _request(
        "DIGITAL_CURRENCY_DAILY",
        {"symbol": symbol, "market": market},
    )
    series = payload.get("Time Series (Digital Currency Daily)") or {}
    rows: list[dict[str, Any]] = []
    for date, bar in series.items():
        # AV historically used keys like "4a. close (USD)" — modern responses
        # also expose unsuffixed "1. open"/.../"5. volume". Handle both.
        close = bar.get(f"4a. close ({market})") or bar.get("4. close")
        open_ = bar.get(f"1a. open ({market})") or bar.get("1. open")
        high = bar.get(f"2a. high ({market})") or bar.get("2. high")
        low = bar.get(f"3a. low ({market})") or bar.get("3. low")
        vol = bar.get("5. volume")
        rows.append({
            "date": date,
            "open": _to_float(open_),
            "high": _to_float(high),
            "low": _to_float(low),
            "close": _to_float(close),
            "volume": _to_float(vol),
        })
    rows.sort(key=lambda r: r["date"], reverse=True)
    return rows


def treasury_yield(maturity: str, interval: str = "daily") -> list[dict[str, Any]]:
    payload = _request(
        "TREASURY_YIELD",
        {"interval": interval, "maturity": maturity},
    )
    data = payload.get("data") or []
    rows: list[dict[str, Any]] = []
    for item in data:
        rows.append({"date": item.get("date"), "value": _to_float(item.get("value"))})
    # AV returns newest first already, but be defensive.
    rows.sort(key=lambda r: r["date"] or "", reverse=True)
    return rows


def overview(symbol: str) -> dict[str, Any]:
    """OVERVIEW: fundamentals, analyst ratings, dividend info."""
    payload = _request("OVERVIEW", {"symbol": symbol})
    if not payload or not payload.get("Symbol"):
        raise AlphaVantageError(f"OVERVIEW empty for {symbol}")
    return payload  # AV already returns flat string-valued dict; keep as-is.


def earnings(symbol: str) -> dict[str, Any]:
    return _request("EARNINGS", {"symbol": symbol})


def dividends(symbol: str) -> list[dict[str, Any]]:
    payload = _request("DIVIDENDS", {"symbol": symbol})
    data = payload.get("data") or []
    rows: list[dict[str, Any]] = []
    for item in data:
        rows.append({
            "ex_dividend_date": item.get("ex_dividend_date"),
            "declaration_date": item.get("declaration_date"),
            "record_date": item.get("record_date"),
            "payment_date": item.get("payment_date"),
            "amount": _to_float(item.get("amount")),
        })
    return rows


def top_gainers_losers() -> dict[str, Any]:
    return _request("TOP_GAINERS_LOSERS", {})


def news_sentiment(
    tickers: str | None = None,
    topics: str | None = None,
    limit: int = 50,
    sort: str = "LATEST",
) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": limit, "sort": sort}
    if tickers:
        params["tickers"] = tickers
    if topics:
        params["topics"] = topics
    return _request("NEWS_SENTIMENT", params)


def sma(symbol: str, time_period: int = 20, interval: str = "daily") -> list[dict[str, Any]]:
    payload = _request(
        "SMA",
        {
            "symbol": symbol,
            "interval": interval,
            "time_period": time_period,
            "series_type": "close",
        },
    )
    series = payload.get("Technical Analysis: SMA") or {}
    rows = [{"date": d, "sma": _to_float(v.get("SMA"))} for d, v in series.items()]
    rows.sort(key=lambda r: r["date"], reverse=True)
    return rows


def rsi(symbol: str, time_period: int = 14, interval: str = "daily") -> list[dict[str, Any]]:
    payload = _request(
        "RSI",
        {
            "symbol": symbol,
            "interval": interval,
            "time_period": time_period,
            "series_type": "close",
        },
    )
    series = payload.get("Technical Analysis: RSI") or {}
    rows = [{"date": d, "rsi": _to_float(v.get("RSI"))} for d, v in series.items()]
    rows.sort(key=lambda r: r["date"], reverse=True)
    return rows


def symbol_search(keywords: str) -> list[dict[str, Any]]:
    payload = _request("SYMBOL_SEARCH", {"keywords": keywords})
    matches = payload.get("bestMatches") or []
    out: list[dict[str, Any]] = []
    for m in matches:
        out.append({
            "symbol": m.get("1. symbol"),
            "name": m.get("2. name"),
            "type": m.get("3. type"),
            "region": m.get("4. region"),
            "currency": m.get("8. currency"),
            "match_score": _to_float(m.get("9. matchScore")),
        })
    return out


# --- Type coercion helpers ------------------------------------------------


def _to_float(value: Any) -> float | None:
    if value is None or value == "" or value == "None":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    if value is None or value == "" or value == "None":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _to_change_pct(value: Any) -> float | None:
    """AV returns ``"-1.2345%"`` — strip the ``%`` and convert."""
    if value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    s = str(value).strip().rstrip("%")
    try:
        return float(s)
    except ValueError:
        return None
