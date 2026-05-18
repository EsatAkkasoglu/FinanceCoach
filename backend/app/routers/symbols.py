"""Symbol search / resolve route.

Exposes the `resolve_symbol` tool's underlying search pipeline as a thin REST
endpoint so the frontend can offer a real-time autocomplete in the "Add
holding" form.

Sources (in order of priority):
  1. Curated aliases from `app.tools.symbol_resolver._TABLE`
     — covers indices, FX, commodity-ETF proxies.
  2. yfinance Search
     — covers US equities, ETFs, ADRs by company name or ticker.
  3. CoinGecko search
     — covers crypto coins by name or symbol.

Results are deduped by ticker and capped at 10.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.auth import get_current_user_id  # noqa: F401  (kept for future scoping)
from app.services import coingecko as cg
from app.services.coingecko import CoinGeckoError
from app.services import yfinance_service as yf_svc
from app.services.yfinance_service import YFinanceError
from app.tools.symbol_resolver import _TABLE

log = logging.getLogger("fincoach.symbols")
router = APIRouter(tags=["symbols"])


class SymbolSuggestion(BaseModel):
    ticker: str
    description: str
    asset_class: str
    source: str
    region: str | None = None


class SymbolSearchResponse(BaseModel):
    query: str
    results: list[SymbolSuggestion]


def _curated_hits(q: str, limit: int) -> list[SymbolSuggestion]:
    """Substring scan over the curated alias table."""
    out: list[SymbolSuggestion] = []
    qq = q.lower().strip()
    if not qq:
        return out
    for phrase, (ticker, desc, asset_class) in _TABLE.items():
        if qq in phrase or qq in ticker.lower():
            out.append(SymbolSuggestion(
                ticker=ticker, description=desc, asset_class=asset_class,
                source="curated",
            ))
        if len(out) >= limit:
            break
    return out


def _yf_hits(q: str, limit: int) -> list[SymbolSuggestion]:
    try:
        matches = yf_svc.search(q, max_results=limit * 2)
    except YFinanceError as exc:
        log.info("yfinance search failed for %r: %s", q, exc)
        return []
    out: list[SymbolSuggestion] = []
    # Prefer US listings first
    matches_sorted = sorted(
        matches,
        key=lambda m: (0 if (m.get("region") or "").lower() == "united states" else 1),
    )
    for m in matches_sorted:
        sym = m.get("symbol")
        if not sym:
            continue
        out.append(SymbolSuggestion(
            ticker=str(sym).upper(),
            description=m.get("name") or str(sym),
            asset_class=(m.get("type") or "stock").lower(),
            source="yfinance",
            region=m.get("region"),
        ))
        if len(out) >= limit:
            break
    return out


def _crypto_hits(q: str, limit: int) -> list[SymbolSuggestion]:
    try:
        hits = cg.search_coins(q)
    except CoinGeckoError as exc:
        log.info("CoinGecko search failed for %r: %s", q, exc)
        return []
    out: list[SymbolSuggestion] = []
    for h in hits:
        sym = (h.get("symbol") or "").upper()
        name = h.get("name") or sym
        rank = h.get("rank")
        if rank is None or rank > 300:
            continue
        out.append(SymbolSuggestion(
            ticker=f"{sym}-USD",
            description=f"{name} (#{rank})" if rank else name,
            asset_class="crypto",
            source="coingecko",
        ))
        if len(out) >= limit:
            break
    return out


@router.get("/symbols/resolve", response_model=SymbolSearchResponse)
def resolve(q: str = Query(..., min_length=1, max_length=64), limit: int = Query(10, ge=1, le=20)):
    """Autocomplete-friendly symbol search.

    Returns up to `limit` candidate tickers across curated aliases,
    yfinance, and CoinGecko.
    """
    q = q.strip()
    if not q:
        return SymbolSearchResponse(query=q, results=[])

    merged: list[SymbolSuggestion] = []
    seen: set[str] = set()

    def _add(items: list[SymbolSuggestion]) -> None:
        for it in items:
            if it.ticker in seen:
                continue
            seen.add(it.ticker)
            merged.append(it)
            if len(merged) >= limit:
                return

    _add(_curated_hits(q, limit))
    if len(merged) < limit:
        _add(_yf_hits(q, limit - len(merged)))
    if len(merged) < limit:
        _add(_crypto_hits(q, limit - len(merged)))

    return SymbolSearchResponse(query=q, results=merged[:limit])
