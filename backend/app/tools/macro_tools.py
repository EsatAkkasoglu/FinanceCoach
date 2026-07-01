"""Macro / regime context tools — give the analyst explicit market-mood context.

A single regime read (VIX + crypto Fear & Greed + the 10y-2y yield curve) and an
optional Finnhub equity quote backstop. Both degrade gracefully when a feed/key
is missing.
"""
from __future__ import annotations

from typing import Any

from langchain_core.tools import tool


@tool
def get_macro_snapshot() -> dict[str, Any]:
    """Current macro / market regime — VIX, crypto Fear & Greed, and the 10y-2y
    treasury yield curve, blended into one risk-on / risk-off read.

    Use when the user asks about the broad market mood ("piyasa nasıl?", "risk
    iştahı", "is the market risk-on?") or to contextualize a trade decision with
    the prevailing regime. All fields are best-effort (null when a feed is down).
    """
    from app.services.signal_engine import _macro_regime_score
    score, detail = _macro_regime_score()
    label = "risk-on" if score > 0.2 else "risk-off" if score < -0.2 else "neutral"
    return {"ok": True, "regime_score": round(score, 3), "regime": label, **detail}


@tool
def get_finnhub_quote(symbol: str) -> dict[str, Any]:
    """Real-time US equity quote via Finnhub (a backstop to yfinance).

    Returns price, % change and the day's high/low/prev-close. Use when a yfinance
    quote looks stale/missing for a US stock or ETF. Requires FINNHUB_API_KEY;
    returns an error field when unavailable.

    Args:
        symbol: US ticker, e.g. "AAPL", "NVDA", "SPY".
    """
    from app.services import finnhub
    q = finnhub.quote(symbol)
    if q is None:
        return {"ok": False, "error": "finnhub unavailable (no key or no data)", "symbol": symbol}
    return {"ok": True, **q}
