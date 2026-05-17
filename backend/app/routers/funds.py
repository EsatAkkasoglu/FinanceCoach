"""TEFAS Turkish mutual fund routes.

Thin REST sarmalayıcılar over the LangGraph tools in `app.tools.fund_tools`.
All data ultimately comes from tefas.gov.tr via the `tefas-crawler` package.

Endpoints:
    GET /funds/search?q=...&kind=mutual|pension
    GET /funds/top?metric=best_rank|worst_rank&category=...
    GET /funds/{code}/quote
    GET /funds/{code}/history?days=90

Caching is delegated to the underlying tool layer (12h per-fund history,
24h universe snapshot).
"""
from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.tools.fund_tools import (
    _fold_tr,
    get_fund_history,
    get_fund_quote,
    list_top_funds,
    search_fund,
)

log = logging.getLogger("fincoach.funds")
router = APIRouter(prefix="/funds", tags=["funds"])


class FundRow(BaseModel):
    code: str
    title: str | None = None
    price: float | None = None
    change_pct: float | None = None
    category: str | None = None
    risk: str | None = None
    return_1m: float | None = None
    return_3m: float | None = None
    return_6m: float | None = None
    return_1y: float | None = None
    return_ytd: float | None = None
    category_rank: int | None = None
    category_total: int | None = None
    as_of: str | None = None


class FundListResponse(BaseModel):
    results: list[FundRow]


class FundHistoryPoint(BaseModel):
    date: str
    price: float


class FundHistoryResponse(BaseModel):
    code: str
    days: int
    points: list[FundHistoryPoint]


def _to_row(d: dict[str, Any]) -> FundRow:
    risk = d.get("risk")
    return FundRow(
        code=d.get("code") or "",
        title=d.get("title"),
        price=d.get("price"),
        category=d.get("category"),
        risk=str(risk) if risk is not None else None,
        return_1m=d.get("return_1m"),
        return_3m=d.get("return_3m"),
        return_6m=d.get("return_6m"),
        return_1y=d.get("return_1y"),
        return_ytd=d.get("return_ytd"),
        category_rank=d.get("category_rank"),
        category_total=d.get("category_total"),
        as_of=d.get("date") or d.get("as_of"),
    )


@router.get("/search", response_model=FundListResponse)
def search(
    q: str = Query(..., min_length=1, max_length=64),
    limit: int = Query(10, ge=1, le=50),
    kind: Literal["mutual", "pension"] = "mutual",
):
    hits = search_fund.invoke({"query": q, "limit": limit, "kind": kind})
    return FundListResponse(results=[_to_row(h) for h in hits])


@router.get("/top", response_model=FundListResponse)
def top(
    metric: Literal["best_rank", "worst_rank"] = "best_rank",
    limit: int = Query(10, ge=1, le=50),
    category: str | None = Query(
        default=None,
        description="Optional category filter — matches fund title (e.g. 'altın', 'hisse').",
    ),
):
    """Top / bottom funds by within-category rank, optionally narrowed by title keyword."""
    rows = list_top_funds.invoke({"metric": metric, "limit": 500})
    if category:
        cat = _fold_tr(category)
        rows = [
            r for r in rows
            if cat in _fold_tr(r.get("category") or "") or cat in _fold_tr(r.get("title") or "")
        ]
    return FundListResponse(results=[_to_row(r) for r in rows[:limit]])


@router.get("/{code}/quote", response_model=FundRow)
def quote(code: str):
    res = get_fund_quote.invoke({"code": code})
    if res.get("error"):
        raise HTTPException(status_code=404, detail=res["error"])
    return FundRow(
        code=res["code"],
        title=res.get("title"),
        price=res.get("price"),
        change_pct=res.get("change_pct"),
        category_rank=res.get("category_rank"),
        category_total=res.get("category_total"),
        as_of=res.get("as_of"),
    )


@router.get("/{code}/history", response_model=FundHistoryResponse)
def history(code: str, days: int = Query(90, ge=2, le=365)):
    pts = get_fund_history.invoke({"code": code, "days": days})
    return FundHistoryResponse(
        code=code.upper(),
        days=days,
        points=[FundHistoryPoint(date=p["date"], price=float(p["price"])) for p in pts],
    )
