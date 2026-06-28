"""Short-term crypto trading routes — the 4-hour signal layer.

Exposes the intraday signal engine (``tools.crypto_short_term``) and the
persisted, live-scored trade targets that power the demo account's
"maximum profit in 4 hours" surface.

  GET  /crypto/basket            — the curated symbols (news + technicals ready)
  GET  /crypto/short-term/{tk}   — compute a 4h plan for one symbol (no persist)
  POST /crypto/targets/scan      — score the whole basket, upsert a target each
  GET  /crypto/targets           — list the user's targets, re-priced live

All endpoints require a bearer token and degrade gracefully — a data-source
failure comes back as a 200 with an ``error`` field, never a raw 500 (an
unhandled exception would bypass CORS/security middleware, see insights.py).
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends

import app.services.coindesk as cd
from app.auth import get_current_user_id
from app.db.models import TradeStatus, TradeTarget
from app.db.session import SessionLocal
from app.settings import settings
from app.tools.crypto_short_term import HORIZON_HOURS, analyze_short_term
from app.tools.market_tools import get_quote

log = logging.getLogger("fincoach.crypto")
router = APIRouter(prefix="/crypto", tags=["crypto"])


def _naive_utc() -> datetime:
    """utcnow() as a naive datetime, matching the model column defaults."""
    return datetime.now(UTC).replace(tzinfo=None)


@router.get("/basket")
def basket() -> dict[str, Any]:
    """The curated short-term basket: symbol + display name + canonical ticker."""
    items = [
        {"symbol": s, "ticker": f"{s}-USD", "name": cd._SYMBOL_TO_ID.get(s, s)}
        for s in settings.crypto_basket
    ]
    return {"basket": items, "horizon_hours": HORIZON_HOURS}


@router.get("/short-term/{ticker}")
def short_term(ticker: str, news: bool = True) -> dict[str, Any]:
    """Compute (without persisting) a 4-hour trade plan for one crypto symbol."""
    try:
        return analyze_short_term(ticker, with_news=news)
    except Exception as exc:  # noqa: BLE001 — never surface a raw 500 (bypasses CORS)
        log.warning("short-term signal failed for %r: %s", ticker, exc, exc_info=True)
        return {"ok": False, "error": str(exc), "symbol": ticker}


def _live_price(ticker: str) -> float | None:
    try:
        q = get_quote.invoke({"ticker": ticker})
        if isinstance(q, dict) and "error" not in q:
            return q.get("price")
    except Exception as exc:  # noqa: BLE001
        log.info("live price unavailable for %s: %s", ticker, exc)
    return None


def _evaluate(t: TradeTarget, price: float | None, now: datetime) -> dict[str, Any]:
    """Re-price a target, resolve hit/stopped/expired, and compute progress.

    Mutates ``t`` (status/resolved_*) when it newly resolves; the caller commits.
    Returns the JSON-safe view for the API.
    """
    long = t.direction == "long"
    newly_resolved = False
    if t.status == TradeStatus.ACTIVE.value and price is not None:
        if t.target_price is not None and (
            (long and price >= t.target_price) or (not long and price <= t.target_price)
        ):
            t.status = TradeStatus.HIT.value
            newly_resolved = True
        elif t.stop_price is not None and (
            (long and price <= t.stop_price) or (not long and price >= t.stop_price)
        ):
            t.status = TradeStatus.STOPPED.value
            newly_resolved = True
        elif t.expires_at is not None and now >= t.expires_at:
            t.status = TradeStatus.EXPIRED.value
            newly_resolved = True
    if newly_resolved:
        t.resolved_at = now
        t.resolved_price = price

    # P&L in the trade's favour (long: +ve when price up; short: inverse).
    pnl_pct = None
    if price is not None and t.entry_price:
        raw = (price / t.entry_price - 1.0) * 100.0
        pnl_pct = round(raw if long else -raw, 2)

    # Progress from entry toward target ∈ [0, 1] (can exceed on overshoot).
    progress = None
    if price is not None and t.target_price is not None and t.target_price != t.entry_price:
        progress = round((price - t.entry_price) / (t.target_price - t.entry_price), 3)

    minutes_left = None
    if t.expires_at is not None:
        minutes_left = max(0, int((t.expires_at - now).total_seconds() // 60))

    return {
        "id": t.id,
        "ticker": t.ticker,
        "asset_class": t.asset_class,
        "direction": t.direction,
        "entry_price": t.entry_price,
        "target_price": t.target_price,
        "stop_price": t.stop_price,
        "current_price": price,
        "pnl_pct": pnl_pct,
        "progress": progress,
        "horizon_hours": t.horizon_hours,
        "confidence": t.confidence,
        "score": t.score,
        "thesis": t.thesis,
        "status": t.status,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "expires_at": t.expires_at.isoformat() if t.expires_at else None,
        "minutes_left": minutes_left,
        "resolved_at": t.resolved_at.isoformat() if t.resolved_at else None,
        "resolved_price": t.resolved_price,
    }


def upsert_target_from_plan(db, user_id: int, result: dict[str, Any]) -> TradeTarget | None:
    """Create/replace the ACTIVE target for (user, ticker) from a signal result.

    Shared by the scan endpoint and the demo seeder. ``result`` is the
    ``analyze_short_term`` envelope; returns None if the signal failed or is a
    no-trade (neutral with no target). Supersedes the prior active row.
    """
    if not result.get("ok"):
        return None
    plan = result.get("data") or {}
    if plan.get("direction") == "neutral" or plan.get("target") is None:
        return None
    ticker = plan.get("ticker") or f"{plan.get('symbol', '')}-USD"
    now = _naive_utc()

    from sqlalchemy import select

    existing = db.execute(
        select(TradeTarget).where(
            TradeTarget.user_id == user_id,
            TradeTarget.ticker == ticker,
            TradeTarget.status == TradeStatus.ACTIVE.value,
        )
    ).scalars().all()
    # A re-scan REPLACES the prior plan — it was never market-resolved, so drop
    # it rather than leaving a price-less "expired" ghost cluttering the desk.
    # Genuine resolutions (hit/stopped/expired-by-time) happen in _evaluate and
    # persist as history.
    for row in existing:
        db.delete(row)

    horizon = int(plan.get("horizon_hours", HORIZON_HOURS))
    target = TradeTarget(
        user_id=user_id,
        ticker=ticker,
        asset_class="crypto",
        direction=plan["direction"],
        entry_price=plan["entry"],
        target_price=plan["target"],
        stop_price=plan["stop"],
        horizon_hours=horizon,
        confidence=plan.get("confidence", 0.0),
        score=plan.get("score", 0.0),
        thesis=result.get("rationale") or result.get("explanation"),
        status=TradeStatus.ACTIVE.value,
        created_at=now,
        expires_at=now + timedelta(hours=horizon),
    )
    db.add(target)
    return target


@router.post("/targets/scan")
def scan_targets(user_id: int = Depends(get_current_user_id)) -> dict[str, Any]:
    """Score the whole basket and (re)create a 4-hour target for each tradable one."""
    plans: list[dict[str, Any]] = []
    with SessionLocal() as db:
        created = 0
        for sym in settings.crypto_basket:
            result = analyze_short_term(sym)
            plans.append(
                {
                    "symbol": sym,
                    "ok": bool(result.get("ok")),
                    "formatted_value": result.get("formatted_value"),
                    "plan": result.get("data"),
                    "error": result.get("error"),
                }
            )
            if upsert_target_from_plan(db, user_id, result) is not None:
                created += 1
        db.commit()
    return {"ok": True, "created": created, "scanned": len(settings.crypto_basket), "plans": plans}


@router.get("/targets")
def list_targets(
    active_only: bool = False, user_id: int = Depends(get_current_user_id)
) -> dict[str, Any]:
    """List the user's trade targets, re-priced live (resolves hit/stopped/expired)."""
    from sqlalchemy import select

    now = _naive_utc()
    with SessionLocal() as db:
        stmt = select(TradeTarget).where(TradeTarget.user_id == user_id)
        if active_only:
            stmt = stmt.where(TradeTarget.status == TradeStatus.ACTIVE.value)
        stmt = stmt.order_by(TradeTarget.created_at.desc())
        rows = db.execute(stmt).scalars().all()

        # Re-price only the still-open ones (closed rows keep their resolution).
        price_cache: dict[str, float | None] = {}
        out: list[dict[str, Any]] = []
        for t in rows:
            # Skip superseded "ghost" rows from older supersede-by-expire logic:
            # expired with no resolution price = replaced, not market-resolved.
            if t.status == TradeStatus.EXPIRED.value and t.resolved_price is None:
                continue
            price = None
            if t.status == TradeStatus.ACTIVE.value:
                if t.ticker not in price_cache:
                    price_cache[t.ticker] = _live_price(t.ticker)
                price = price_cache[t.ticker]
            out.append(_evaluate(t, price, now))
        db.commit()

    active = [r for r in out if r["status"] == "active"]
    return {
        "targets": out,
        "summary": {
            "total": len(out),
            "active": len(active),
            "hit": sum(1 for r in out if r["status"] == "hit"),
            "stopped": sum(1 for r in out if r["status"] == "stopped"),
            "avg_pnl_pct": round(
                sum(r["pnl_pct"] for r in active if r["pnl_pct"] is not None)
                / max(1, sum(1 for r in active if r["pnl_pct"] is not None)),
                2,
            )
            if active
            else None,
        },
    }
