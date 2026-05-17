"""Admin-only reporting endpoints.

Gated by `FINCOACH_ADMIN_USERNAMES` (comma-separated). No password material is
ever returned. Designed for ops/support queries like "who holds ticker X?".
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select

from app.auth.deps import get_current_user
from app.db.models import Holding, User
from app.db.session import SessionLocal
from app.settings import settings

router = APIRouter(prefix="/admin", tags=["admin"])


def _admin_usernames() -> set[str]:
    return {u.strip() for u in settings.admin_usernames.split(",") if u.strip()}


def require_admin(user: User = Depends(get_current_user)) -> User:
    allowed = _admin_usernames()
    if not allowed or user.username not in allowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "admin access required")
    return user


class HolderPosition(BaseModel):
    user_id: int
    username: str
    name: str
    quantity: float
    cost_basis: float
    asset_class: str


class TickerHoldersResponse(BaseModel):
    ticker: str
    user_count: int
    total_quantity: float
    holders: list[HolderPosition]


@router.get("/holdings/by-ticker", response_model=TickerHoldersResponse)
def holders_for_ticker(
    ticker: str = Query(..., min_length=1, max_length=32),
    _: User = Depends(require_admin),
) -> TickerHoldersResponse:
    """List users holding `ticker` (case-insensitive). No credentials returned."""
    normalized = ticker.strip().upper()

    with SessionLocal() as db:
        rows = db.execute(
            select(User, Holding)
            .join(Holding, Holding.user_id == User.id)
            .where(func.upper(Holding.ticker) == normalized)
            .order_by(Holding.quantity.desc())
        ).all()

        holders = [
            HolderPosition(
                user_id=u.id,
                username=u.username,
                name=u.name or "",
                quantity=h.quantity,
                cost_basis=h.cost_basis,
                asset_class=h.asset_class,
            )
            for u, h in rows
        ]

    return TickerHoldersResponse(
        ticker=normalized,
        user_count=len({h.user_id for h in holders}),
        total_quantity=sum(h.quantity for h in holders),
        holders=holders,
    )
