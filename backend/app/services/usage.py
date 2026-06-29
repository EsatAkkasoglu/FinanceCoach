"""Per-user monthly usage metering + plan gating (cost control).

The chat turn is the metered (LLM-spending) action. Free-tier users get a
configurable monthly cap; Pro users are uncapped. Everything keys off a UTC
calendar-month ``period`` string so the counter resets on the 1st automatically
without a cron job.

Two-tier limits keep the unit economics safe (a power user on ~1000 turns/mo
would otherwise erase the margin in BIRIM_MALIYET_FIYAT.md).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.models import UsageCounter
from app.settings import settings


def current_period(now: datetime | None = None) -> str:
    """UTC calendar month as ``"YYYY-MM"`` — the counter's reset bucket."""
    return (now or datetime.utcnow()).strftime("%Y-%m")


def monthly_limit(tier: str | None) -> int | None:
    """Turn cap for a tier. ``None`` means uncapped (Pro, or gate disabled)."""
    if (tier or "free").lower() != "free":
        return None  # Pro / paid tiers are uncapped.
    cap = settings.free_monthly_chat_turns
    return None if cap <= 0 else cap


def _count(db, user_id: int, period: str) -> int:
    row = db.execute(
        select(UsageCounter.chat_turns).where(
            UsageCounter.user_id == user_id, UsageCounter.period == period
        )
    ).scalar_one_or_none()
    return int(row or 0)


def get_usage(db, user_id: int, tier: str | None) -> dict:
    """Read-only snapshot for the ``GET /usage`` endpoint / UI meter."""
    period = current_period()
    used = _count(db, user_id, period)
    limit = monthly_limit(tier)
    return {
        "period": period,
        "tier": (tier or "free").lower(),
        "used": used,
        "limit": limit,
        "remaining": None if limit is None else max(0, limit - used),
        "unlimited": limit is None,
    }


def check_and_increment(db, user_id: int, tier: str | None) -> tuple[bool, dict]:
    """Atomically gate + count one chat turn.

    Returns ``(allowed, usage)``. When the user is at/over the cap, returns
    ``(False, usage)`` WITHOUT incrementing. Uncapped tiers always pass and are
    not counted (no row churn). Idempotent under the unique constraint: a raced
    insert falls back to an in-place increment.
    """
    period = current_period()
    limit = monthly_limit(tier)
    if limit is None:
        return True, get_usage(db, user_id, tier)

    row = db.execute(
        select(UsageCounter).where(
            UsageCounter.user_id == user_id, UsageCounter.period == period
        )
    ).scalar_one_or_none()

    if row is None:
        row = UsageCounter(user_id=user_id, period=period, chat_turns=0)
        db.add(row)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()  # raced another insert — fetch the winner
            row = db.execute(
                select(UsageCounter).where(
                    UsageCounter.user_id == user_id, UsageCounter.period == period
                )
            ).scalar_one()

    if row.chat_turns >= limit:
        db.rollback()
        return False, get_usage(db, user_id, tier)

    row.chat_turns += 1
    db.commit()
    return True, {
        "period": period,
        "tier": (tier or "free").lower(),
        "used": row.chat_turns,
        "limit": limit,
        "remaining": max(0, limit - row.chat_turns),
        "unlimited": False,
    }
