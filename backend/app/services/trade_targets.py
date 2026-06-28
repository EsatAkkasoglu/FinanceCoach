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


def upsert_target_from_plan(
    db,
    user_id: int,
    result: dict[str, Any],
    *,
    status: str = TradeStatus.ACTIVE.value,
) -> TradeTarget | None:
    """Create/replace a target for (user, ticker, horizon) from a signal result.

    ``result`` is the ``analyze_short_term`` / ``build_signal`` envelope. Returns
    None if the signal failed or is a no-trade (neutral / no target). Asset class
    and horizon are read from the plan (default crypto / 4h). Supersede is keyed
    on (user, ticker, horizon) so a fresh re-scan replaces only the *same-horizon*
    open plan — a 2-week position is NOT wiped by a 4-hour scan.

    ``status`` is the lifecycle the new row enters: ACTIVE (auto-placed / seeded)
    or PENDING (proposed in chat, awaiting the user's Approve). Caller commits.
    """
    if not result.get("ok"):
        return None
    plan = result.get("data") or {}
    if plan.get("direction") == "neutral" or plan.get("target") is None:
        return None
    ticker = plan.get("ticker") or f"{plan.get('symbol', '')}-USD"
    asset_class = plan.get("asset_class") or "crypto"
    horizon = int(plan.get("horizon_hours", DEFAULT_HORIZON_HOURS))
    now = naive_utc()

    # Supersede only the same-horizon open/pending plan for this ticker.
    existing = db.execute(
        select(TradeTarget).where(
            TradeTarget.user_id == user_id,
            TradeTarget.ticker == ticker,
            TradeTarget.horizon_hours == horizon,
            TradeTarget.status.in_((TradeStatus.ACTIVE.value, TradeStatus.PENDING.value)),
        )
    ).scalars().all()
    # A re-scan REPLACES the prior plan — it was never market-resolved, so drop
    # it rather than leaving a price-less "expired" ghost cluttering the desk.
    for row in existing:
        db.delete(row)

    target = TradeTarget(
        user_id=user_id,
        ticker=ticker,
        asset_class=asset_class,
        direction=plan["direction"],
        entry_price=plan["entry"],
        target_price=plan["target"],
        stop_price=plan["stop"],
        horizon_hours=horizon,
        confidence=plan.get("confidence", 0.0),
        score=plan.get("score", 0.0),
        thesis=result.get("rationale") or result.get("explanation"),
        status=status,
        created_at=now,
        expires_at=now + timedelta(hours=horizon),
    )
    db.add(target)
    return target
