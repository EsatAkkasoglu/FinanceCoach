"""Insights / scanner / analysis routes.

Thin REST sarmalayıcılar over the LangGraph market & news tools, so the
frontend's Discover tab and ticker-detail drawer can render the same data
the chat agents see. All endpoints degrade gracefully — tool errors come
back as 200 with an `error` field so the UI can show a useful message.

Endpoints:
    GET  /insights/8dim/{ticker}?fast=1
    GET  /insights/technicals/{ticker}?sma=50&rsi=14
    GET  /insights/dividend/{ticker}
    GET  /insights/news?q=...&limit=5
    GET  /insights/trends
    GET  /insights/rumors
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Query

from app.tools.market_tools import (
    analyze_ticker_8dim,
    get_dividend_metrics,
    get_technical_indicators,
    scan_hot_trends,
    scan_rumors,
)
from app.tools.news_tools import search_news

log = logging.getLogger("fincoach.insights")
router = APIRouter(prefix="/insights", tags=["insights"])


@router.get("/8dim/{ticker}")
def eight_dim(ticker: str, fast: bool = Query(False)):
    return analyze_ticker_8dim.invoke({"ticker": ticker, "fast": fast})


@router.get("/technicals/{ticker}")
def technicals(
    ticker: str,
    sma: int = Query(50, ge=5, le=200),
    rsi: int = Query(14, ge=2, le=50),
):
    return get_technical_indicators.invoke(
        {"ticker": ticker, "sma_period": sma, "rsi_period": rsi}
    )


@router.get("/dividend/{ticker}")
def dividend(ticker: str):
    res = get_dividend_metrics.invoke({"ticker": ticker})
    return res or {"ticker": ticker.upper(), "error": "no dividend data"}


@router.get("/news")
def news(q: str = Query(..., min_length=1, max_length=80), limit: int = Query(5, ge=1, le=20)):
    return {"articles": search_news.invoke({"query": q, "limit": limit})}


@router.get("/trends")
def trends():
    return scan_hot_trends.invoke({"no_social": False})


@router.get("/rumors")
def rumors():
    return scan_rumors.invoke({})
