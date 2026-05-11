"""Portfolio tools — read/write the user's holdings and transactions."""
from __future__ import annotations

from typing import Any

from langchain_core.tools import tool
from sqlalchemy import select

from app.db.models import Holding, Transaction
from app.db.session import SessionLocal


@tool
def list_holdings(user_id: int = 1) -> list[dict[str, Any]]:
    """List all current holdings for the user."""
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
def list_transactions(user_id: int = 1, limit: int = 100) -> list[dict[str, Any]]:
    """Return the most recent transactions for the user."""
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
