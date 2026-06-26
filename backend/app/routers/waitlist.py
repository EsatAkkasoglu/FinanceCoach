"""Public landing waitlist — Phase 0 demand validation.

No auth: the marketing landing posts an email + the tier the visitor wants.
Idempotent per email (re-submitting updates the tier interest). The count
endpoint lets us watch the signal without exposing the list.
"""
from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.db.models import Waitlist
from app.db.session import SessionLocal

router = APIRouter(prefix="/waitlist", tags=["waitlist"])

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class JoinRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    tier: str | None = Field(default=None, max_length=32)
    source: str | None = Field(default=None, max_length=64)


@router.post("", status_code=201)
def join_waitlist(body: JoinRequest):
    """Record an early-access signup. Idempotent on email."""
    email = body.email.strip().lower()
    if not _EMAIL_RE.match(email):
        raise HTTPException(422, "invalid email")
    tier = (body.tier or "").strip().lower()[:32] or None
    source = (body.source or "").strip()[:64] or None

    with SessionLocal() as db:
        existing = db.execute(
            select(Waitlist).where(Waitlist.email == email)
        ).scalar_one_or_none()
        if existing is not None:
            if tier:  # refresh the tier interest on re-submit
                existing.tier = tier
                db.commit()
            return {"ok": True, "already": True}
        db.add(Waitlist(email=email, tier=tier, source=source))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()  # raced another insert for the same email — fine
        return {"ok": True}


@router.get("/count")
def waitlist_count():
    """Total signups (for watching the demand signal). No PII exposed."""
    with SessionLocal() as db:
        n = db.execute(select(func.count()).select_from(Waitlist)).scalar_one()
    return {"count": int(n or 0)}
