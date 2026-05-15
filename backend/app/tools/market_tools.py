"""Market data tools — yfinance lookups + bridge to the legacy stock-analysis
scripts copied into ``app/legacy/``.

Bind these to agents via ``langgraph.prebuilt.create_react_agent(tools=[...])``.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import yfinance as yf
import requests
from langchain_core.tools import tool

from app.legacy import (
    analyze_ticker,
    analyze_dividends as _legacy_dividends,
    scan_hot_trends as _legacy_hot,
    scan_rumors as _legacy_rumors,
)
from app.tools._cache import cache_get, cache_set

log = logging.getLogger("fincoach.tools.market")


def _quote_via_fast_info(t: "yf.Ticker") -> dict[str, Any] | None:
    """First-try path — cheapest. fails for indices, forex, some commodities."""
    try:
        info = t.fast_info
        price = float(info["last_price"])
    except Exception:
        return None
    prev = float(info.get("previous_close") or price)
    return {
        "price": price,
        "previous_close": prev,
        "currency": info.get("currency", "USD"),
        "via": "fast_info",
    }


def _quote_via_history(t: "yf.Ticker") -> dict[str, Any] | None:
    """Fallback for indices (^GSPC), forex (=X), bond yields (^TNX), futures (=F).
    Pulls 5d so weekend / holiday gaps don't yield empty frames."""
    try:
        hist = t.history(period="5d", auto_adjust=False)
    except Exception:
        return None
    if hist is None or hist.empty:
        return None
    closes = hist["Close"].dropna()
    if closes.empty:
        return None
    price = float(closes.iloc[-1])
    prev = float(closes.iloc[-2]) if len(closes) > 1 else price
    return {"price": price, "previous_close": prev, "currency": "USD", "via": "history"}


def _quote_via_coingecko(ticker: str) -> dict[str, Any] | None:
    """Fallback path for crypto tickers (BTC-USD, ETH-USD). Query CoinGecko
    markets endpoint (first 250 coins) and match on symbol. Returns similar
    shape to other quote helpers.
    """
    try:
        sym = ticker.split("-")[0].lower()
        # Try first two pages (500 coins) to cover most symbols.
        for page in (1, 2):
            url = (
                "https://api.coingecko.com/api/v3/coins/markets"
                "?vs_currency=usd&order=market_cap_desc&per_page=250&page=" + str(page)
            )
            r = requests.get(url, timeout=6)
            r.raise_for_status()
            data = r.json()
            for item in data:
                if (item.get("symbol") or "").lower() == sym:
                    price = float(item.get("current_price") or 0)
                    # previous close isn't provided reliably; approximate
                    prev = price / (1 + (float(item.get("price_change_percentage_24h") or 0) / 100.0)) if item.get("price_change_percentage_24h") is not None else price
                    return {"price": price, "previous_close": prev, "currency": "USD", "via": "coingecko"}
    except Exception:
        return None
    return None


@tool
def get_quote(ticker: str) -> dict[str, Any]:
    """Get the latest price and 1-day change for ANY yfinance-compatible
    ticker — works for stocks, crypto, ETFs, indices, futures, forex,
    Treasury yields.

    For asset NAMES (e.g. "gold", "S&P 500"), call ``resolve_symbol`` first
    to get the right ticker.

    Examples:
        AAPL, NVDA           — US stocks
        BTC-USD, ETH-USD     — crypto
        SPY, QQQ, VTI        — ETFs
        ^GSPC, ^IXIC, ^VIX   — indices
        GLD, SLV, USO        — commodity ETFs
        EURUSD=X, USDTRY=X   — forex
        ^TNX, ^TYX           — Treasury yields
        GC=F, CL=F           — futures (continuous contract)

    Returns:
        {ticker, price, change_pct, currency, as_of, source, via}
    """
    cache_key = f"get_quote:{(ticker or '').strip().upper()}"
    cached = cache_get(cache_key)
    if isinstance(cached, dict):
        return cached
    try:
        t = yf.Ticker(ticker)
        result = _quote_via_fast_info(t) or _quote_via_history(t)
        if result is None:
            # If this looks like a crypto ticker (e.g. BTC-USD), try CoinGecko
            if isinstance(ticker, str) and ticker.upper().endswith("-USD"):
                cg = _quote_via_coingecko(ticker)
                if cg:
                    result = cg
            if result is None:
                return {"ticker": ticker.upper(), "error": "no quote data available"}
        price = result["price"]
        prev = result["previous_close"]
        change_pct = ((price - prev) / prev * 100.0) if prev else 0.0
        quote_result = {
            "ticker": ticker.upper(),
            "price": round(price, 4),
            "change_pct": round(change_pct, 2),
            "currency": result["currency"],
            "as_of": datetime.utcnow().isoformat() + "Z",
            "source": "yfinance",
            "via": result["via"],
        }
        cache_set(cache_key, quote_result)
        return quote_result
    except Exception as exc:
        log.warning("get_quote failed for %s: %s", ticker, exc)
        return {"ticker": ticker.upper(), "error": str(exc)}


@tool
def analyze_ticker_8dim(ticker: str, fast: bool = False) -> dict[str, Any]:
    """Run the 8-dimension analysis on a US stock or crypto ticker.

    Dimensions: earnings_surprise, fundamentals, analyst_sentiment, historical,
    market_context, sector, momentum, sentiment. Returns weighted score and
    BUY/HOLD/SELL recommendation.

    Args:
        ticker: e.g. "NVDA", "BTC-USD"
        fast: skip insider trading + breaking news (~3-5s instead of 10s)
    """
    return analyze_ticker(ticker, fast=fast)


@tool
def get_dividend_metrics(ticker: str) -> dict[str, Any] | None:
    """Yield, payout ratio, growth (5Y CAGR), consecutive years of increases,
    safety score (0-100), income rating (excellent/good/moderate/poor)."""
    return _legacy_dividends(ticker)


@tool
def scan_hot_trends(no_social: bool = True) -> dict[str, Any]:
    """Find trending tickers across CoinGecko, Yahoo Finance, Google News.
    Returns top trending, crypto highlights, stock movers, breaking news."""
    return _legacy_hot(no_social=no_social)


@tool
def scan_rumors() -> dict[str, Any]:
    """M&A rumors, insider activity, analyst upgrades, Twitter whispers.
    Each rumor scored 1-10 by potential market impact."""
    return _legacy_rumors()
