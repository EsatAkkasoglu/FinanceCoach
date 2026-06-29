"""Persistence for short-term crypto trade targets.

Extracted so three callers can share ONE implementation without an import
cycle (``routers.crypto`` and ``tools.crypto_short_term`` both need it, and the
latter is imported BY ``routers.crypto``):

  • routers/crypto.py        — POST /crypto/targets/scan
  • tools/crypto_short_term  — the chat agent's "open a trade" write tools
  • auth/routes.py           — demo-account seeding

A target is the order the chat creates and the Markets desk renders. One ACTIVE
target per (user, ticker); a fresh plan REPLACES the prior one (delete, not
expire — it was superseded, not market-resolved).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.db.models import TradeStatus, TradeTarget

DEFAULT_HORIZON_HOURS = 4


def naive_utc() -> datetime:
    """utcnow() as a naive datetime, matching the model column defaults."""
    return datetime.now(UTC).replace(tzinfo=None)


def upsert_target_from_plan(db, user_id: int, result: dict[str, Any]) -> TradeTarget | None:
    """Create/replace the ACTIVE target for (user, ticker) from a signal result.

    ``result`` is the ``analyze_short_term`` envelope. Returns None if the signal
    failed or is a no-trade (neutral / no target). Supersedes (deletes) the prior
    active row for that ticker. Caller commits.
    """
    if not result.get("ok"):
        return None
    plan = result.get("data") or {}
    if plan.get("direction") == "neutral" or plan.get("target") is None:
        return None
    ticker = plan.get("ticker") or f"{plan.get('symbol', '')}-USD"
    now = naive_utc()

    existing = db.execute(
        select(TradeTarget).where(
            TradeTarget.user_id == user_id,
            TradeTarget.ticker == ticker,
            TradeTarget.status == TradeStatus.ACTIVE.value,
        )
    ).scalars().all()
    # A re-scan REPLACES the prior plan — it was never market-resolved, so drop
    # it rather than leaving a price-less "expired" ghost cluttering the desk.
    for row in existing:
        db.delete(row)

    horizon = int(plan.get("horizon_hours", DEFAULT_HORIZON_HOURS))
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
