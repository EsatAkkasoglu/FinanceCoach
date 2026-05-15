"""Portfolio tools — read the current user's holdings and transactions.

`user_id` comes from the request-scoped ContextVar.
"""
from __future__ import annotations

from typing import Any

from langchain_core.tools import tool
from sqlalchemy import select

from app.auth import get_current_user_id_or_none
from app.db.models import Holding, Transaction
from app.db.session import SessionLocal


@tool
def list_holdings() -> list[dict[str, Any]]:
    """List all current holdings for the user."""
    user_id = get_current_user_id_or_none()
    if user_id is None:
        return []
    with SessionLocal() as db:
        rows = db.execute(select(Holding).where(Holding.user_id == user_id)).scalars().all()
        return [
            {
                "ticker": h.ticker,
                "asset_class": h.asset_class,
                "quantity": h.quantity,
                "cost_basis": h.cost_basis,
                "acquired_at": h.acquired_at.isoformat() if h.acquired_at else None,
            }
            for h in rows
        ]


@tool
def list_transactions(limit: int = 100) -> list[dict[str, Any]]:
    """Return the most recent transactions for the user."""
    user_id = get_current_user_id_or_none()
    if user_id is None:
        return []
    with SessionLocal() as db:
        rows = (
            db.execute(
                select(Transaction)
                .where(Transaction.user_id == user_id)
                .order_by(Transaction.occurred_on.desc())
                .limit(limit)
            )
            .scalars()
            .all()
        )
        return [
            {
                "date": t.occurred_on.isoformat(),
                "type": t.type,
                "amount": t.amount,
                "currency": t.currency,
                "category": t.category,
                "description": t.description,
            }
            for t in rows
        ]
