"""Insights / scanner / analysis routes.

Thin REST sarmalayıcılar over the LangGraph market & news tools, so the
frontend's Discover tab and ticker-detail drawer can render the same data
the chat agents see. All endpoints degrade gracefully — tool errors come
back as 200 with an `error` field so the UI can show a useful message.

Endpoints:
    GET  /insights/8dim/{ticker}?fast=1
    GET  /insights/technicals/{ticker}?sma=50&rsi=14
    GET  /insights/dividend/{ticker}
    GET  /insights/history/{ticker}?days=90&asset_class=stock
    GET  /insights/news?q=...&limit=5
    GET  /insights/trends
    GET  /insights/rumors
"""
from __future__ import annotations

import logging
import math
from typing import Any

from fastapi import APIRouter, Query

import app.services.coindesk as cg
import app.services.yfinance_service as yf_svc
from app.services.coindesk import CoinDeskError
from app.services.yfinance_service import YFinanceError
from app.tools.fund_tools import get_fund_history
from app.tools.market_tools import (
    analyze_ticker_8dim,
    classify_ticker,
    get_dividend_metrics,
    get_technical_indicators,
    scan_hot_trends,
    scan_rumors,
)
from app.tools.news_tools import search_news

log = logging.getLogger("fincoach.insights")
router = APIRouter(prefix="/insights", tags=["insights"])


def _json_safe(obj: Any) -> Any:
    """Coerce tool output into something Starlette's JSONResponse can render.

    yfinance-derived metrics can be NaN/Infinity (e.g. RSI with no downward
    movement, or a 0-division) or numpy scalars. Starlette serializes with
    ``json.dumps(..., allow_nan=False)`` and can't encode numpy types — either
    raises a 500 at *render* time, AFTER the route returns, where ``_safe_tool``
    can't catch it. Normalize here: non-finite floats → None, numpy scalars →
    native Python, recursively.
    """
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, float):
        return float(obj) if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [_json_safe(v) for v in obj]
    item = getattr(obj, "item", None)  # numpy scalar → python scalar
    if callable(item) and not isinstance(obj, str | bytes):
        try:
            return _json_safe(obj.item())
        except Exception:  # noqa: BLE001
            return obj
    return obj


def _safe_tool(ticker: str, label: str, run):
    """Invoke a tool, degrading ANY failure to a 200 with an ``error`` field.

    These endpoints must never surface a raw 500. An unhandled exception is
    returned by Starlette's outermost ``ServerErrorMiddleware`` — *outside* the
    CORS + security-headers middleware — so the browser sees a misleading
    "No 'Access-Control-Allow-Origin' header" CORS error instead of the real
    failure. Catching here keeps the response inside the middleware stack and
    hands the UI a usable message; the full traceback is logged for diagnosis.
    """
    try:
        return _json_safe(run())
    except Exception as exc:  # noqa: BLE001
        log.warning("insights %s failed for %r: %s", label, ticker, exc, exc_info=True)
        out: dict[str, Any] = {"error": str(exc)}
        if ticker:
            out["ticker"] = ticker.strip().upper()
        return out


@router.get("/8dim/{ticker}")
def eight_dim(ticker: str, fast: bool = Query(False)):
    return _safe_tool(ticker, "8dim", lambda: analyze_ticker_8dim.invoke({"ticker": ticker, "fast": fast}))


@router.get("/technicals/{ticker}")
def technicals(
    ticker: str,
    sma: int = Query(50, ge=5, le=200),
    rsi: int = Query(14, ge=2, le=50),
):
    return _safe_tool(
        ticker,
        "technicals",
        lambda: get_technical_indicators.invoke(
            {"ticker": ticker, "sma_period": sma, "rsi_period": rsi}
        ),
    )


@router.get("/dividend/{ticker}")
def dividend(ticker: str):
    res = _safe_tool(ticker, "dividend", lambda: get_dividend_metrics.invoke({"ticker": ticker}))
    return res or {"ticker": ticker.upper(), "error": "no dividend data"}


def _days_to_period(days: int) -> str:
    if days <= 31:
        return "1mo"
    if days <= 93:
        return "3mo"
    if days <= 186:
        return "6mo"
    return "1y"


@router.get("/history/{ticker}")
def price_history(
    ticker: str,
    days: int = Query(90, ge=2, le=365),
    asset_class: str = Query("stock"),
):
    """Daily close history for any holding — stock/ETF/crypto/index or TEFAS fund.

    Returns {ticker, currency, points: [{date, price}]} oldest-first so the
    frontend chart can render a left-to-right time series. Degrades to a 200
    with an ``error`` field so the drawer can show a useful message.
    """
    upper = (ticker or "").strip().upper()

    # TEFAS funds aren't on yfinance — route to the fund history tool.
    if asset_class == "fund":
        try:
            pts = get_fund_history.invoke({"code": ticker, "days": days})
            points = [{"date": p["date"], "price": float(p["price"])} for p in pts]
            return {"ticker": upper, "currency": "TRY", "points": points}
        except Exception as exc:  # noqa: BLE001
            log.warning("fund history failed for %s: %s", upper, exc)
            return {"ticker": upper, "error": str(exc), "points": []}

    cls = classify_ticker(upper)
    try:
        if cls.get("kind") == "crypto":
            bars = cg.coin_history(cls["base"], days=days)  # newest-first {date, close}
            currency = "USD"
        else:
            symbol = cls.get("symbol", upper)
            bars = yf_svc.history(symbol, period=_days_to_period(days))  # newest-first
            currency = "TRY" if symbol.upper().endswith(".IS") else "USD"
    except (YFinanceError, CoinDeskError) as exc:
        log.warning("price history failed for %s: %s", upper, exc)
        return {"ticker": upper, "error": str(exc), "points": []}

    # Bars are newest-first; reverse to oldest-first for a left-to-right chart.
    points: list[dict[str, Any]] = [
        {"date": b["date"], "price": float(b["close"])}
        for b in reversed(bars)
        if b.get("close") is not None
    ]
    return {"ticker": upper, "currency": currency, "points": points}


@router.get("/news")
def news(q: str = Query(..., min_length=1, max_length=80), limit: int = Query(5, ge=1, le=20)):
    res = _safe_tool("", "news", lambda: search_news.invoke({"query": q, "limit": limit}))
    if isinstance(res, dict) and "error" in res:
        return {"articles": [], "error": res["error"]}
    return {"articles": res}


@router.get("/trends")
def trends():
    return _safe_tool("", "trends", lambda: scan_hot_trends.invoke({"no_social": False}))


@router.get("/rumors")
def rumors():
    return _safe_tool("", "rumors", lambda: scan_rumors.invoke({}))
