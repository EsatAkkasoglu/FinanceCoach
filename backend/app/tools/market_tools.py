"""Market data tools — yfinance lookups + bridge to the legacy stock-analysis
scripts copied into ``app/legacy/``.

Bind these to agents via ``langgraph.prebuilt.create_react_agent(tools=[...])``.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import yfinance as yf
from langchain_core.tools import tool

from app.legacy import (
    analyze_ticker,
    analyze_dividends as _legacy_dividends,
    scan_hot_trends as _legacy_hot,
    scan_rumors as _legacy_rumors,
)

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
    try:
        t = yf.Ticker(ticker)
        result = _quote_via_fast_info(t) or _quote_via_history(t)
        if result is None:
            return {"ticker": ticker.upper(), "error": "no quote data available"}
        price = result["price"]
        prev = result["previous_close"]
        change_pct = ((price - prev) / prev * 100.0) if prev else 0.0
        return {
            "ticker": ticker.upper(),
            "price": round(price, 4),
            "change_pct": round(change_pct, 2),
            "currency": result["currency"],
            "as_of": datetime.utcnow().isoformat() + "Z",
            "source": "yfinance",
            "via": result["via"],
        }
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
