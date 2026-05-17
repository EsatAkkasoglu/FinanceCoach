"""Net-worth history routes.

Daily snapshots of total portfolio value, captured on demand (idempotent
per-day via upsert). Backed by `NetWorthSnapshot`.

Endpoints:
    POST /networth/snapshot     — capture / update today's snapshot
    GET  /networth/history?days=30  — last N days, oldest-first
"""
from __future__ import annotations

import logging
from datetime import date as date_cls
from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select

from app.auth import get_current_user_id
from app.db.models import NetWorthSnapshot
from app.db.session import SessionLocal

log = logging.getLogger("fincoach.networth")
router = APIRouter(prefix="/networth", tags=["networth"])


class SnapshotPoint(BaseModel):
    date: str
    value: float
    currency: str


class HistoryResponse(BaseModel):
    points: list[SnapshotPoint]


class SnapshotInput(BaseModel):
    value: float
    currency: str = "USD"


@router.post("/snapshot", response_model=SnapshotPoint)
def capture_snapshot(payload: SnapshotInput, user_id: int = Depends(get_current_user_id)):
    """Upsert today's snapshot. The frontend calls this whenever the
    dashboard loads — duplicates on the same day overwrite the value."""
    today = date_cls.today()
    with SessionLocal() as db:
        existing = db.execute(
            select(NetWorthSnapshot).where(
                NetWorthSnapshot.user_id == user_id,
                NetWorthSnapshot.captured_on == today,
            )
        ).scalar_one_or_none()
        if existing:
            existing.value = payload.value
            existing.currency = payload.currency
            row = existing
        else:
            row = NetWorthSnapshot(
                user_id=user_id,
                captured_on=today,
                value=payload.value,
                currency=payload.currency,
            )
            db.add(row)
        db.commit()
        db.refresh(row)
        return SnapshotPoint(
            date=row.captured_on.isoformat(),
            value=row.value,
            currency=row.currency,
        )


@router.get("/history", response_model=HistoryResponse)
def history(
    days: int = Query(30, ge=2, le=365),
    user_id: int = Depends(get_current_user_id),
):
    cutoff = date_cls.today() - timedelta(days=days)
    with SessionLocal() as db:
        rows = db.execute(
            select(NetWorthSnapshot)
            .where(
                NetWorthSnapshot.user_id == user_id,
                NetWorthSnapshot.captured_on >= cutoff,
            )
            .order_by(NetWorthSnapshot.captured_on.asc())
        ).scalars().all()
    return HistoryResponse(
        points=[
            SnapshotPoint(
                date=r.captured_on.isoformat(),
                value=r.value,
                currency=r.currency,
            )
            for r in rows
        ]
    )
