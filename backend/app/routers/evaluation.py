"""Evaluation routes — the trade-signal "jury" scorecard.

  GET /eval/scorecard — replay the user's resolved trade targets into a
  research-grounded, per (horizon × asset-class) scorecard (risk-adjusted return,
  drawdown, confidence calibration, Deflated Sharpe). Read-only.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.auth import get_current_user_id
from app.db.models import TradeTarget
from app.db.session import SessionLocal
from app.eval.scorecard import build_scorecard

log = logging.getLogger("fincoach.eval")
router = APIRouter(prefix="/eval", tags=["eval"])


def _row(t: TradeTarget) -> dict[str, Any]:
    return {
        "id": t.id,
        "ticker": t.ticker,
        "asset_class": t.asset_class,
        "direction": t.direction,
        "entry_price": t.entry_price,
        "resolved_price": t.resolved_price,
        "confidence": t.confidence,
        "horizon_hours": t.horizon_hours,
        "status": t.status,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }


@router.get("/scorecard")
def scorecard(user_id: int = Depends(get_current_user_id)) -> dict[str, Any]:
    """Research-grounded scorecard over the user's resolved trade targets."""
    try:
        with SessionLocal() as db:
            rows = db.execute(
                select(TradeTarget)
                .where(TradeTarget.user_id == user_id)
                .order_by(TradeTarget.created_at.asc())
            ).scalars().all()
            data = [_row(t) for t in rows]
        return {"ok": True, **build_scorecard(data)}
    except Exception as exc:  # noqa: BLE001 — never surface a raw 500 (bypasses CORS)
        log.warning("scorecard failed for user %s: %s", user_id, exc, exc_info=True)
        return {"ok": False, "error": str(exc)}
