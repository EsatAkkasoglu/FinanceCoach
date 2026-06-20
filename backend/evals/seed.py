"""Seed a representative Turkish retail investor (user_id=1) for evals.

Deterministic + idempotent: wipes user 1's rows and re-creates a fixed
portfolio / budget / goals so eval runs are reproducible. Mirrors the ICP in
docs/URUN_ODAK.md — TEFAS fund + BIST stocks + crypto + a US stock, a salary,
a month of spending, and two goals.

Run standalone:  uv run python -m evals.seed
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import delete, select

from app.db.models import Goal, Holding, Transaction, User
from app.db.session import SessionLocal, init_db

USER_ID = 1


def _wipe(db) -> None:
    db.execute(delete(Holding).where(Holding.user_id == USER_ID))
    db.execute(delete(Transaction).where(Transaction.user_id == USER_ID))
    db.execute(delete(Goal).where(Goal.user_id == USER_ID))


def seed() -> dict[str, int]:
    """(Re)create the demo investor. Returns counts. Safe to call repeatedly."""
    init_db()
    today = date.today()
    with SessionLocal() as db:
        user = db.execute(select(User).where(User.id == USER_ID)).scalar_one_or_none()
        if user is None:
            user = User(id=USER_ID, username="demo", name="Demo Yatırımcı")
            db.add(user)
        user.monthly_income = 90_000.0          # TRY
        user.risk_score = 72                    # balanced
        user.risk_profile = "balanced"
        user.roast_mode = 0
        db.flush()

        _wipe(db)

        # Holdings: BIST + TEFAS fund + crypto + a US stock (mixed currencies).
        holdings = [
            ("THYAO.IS", "stock", 200, 280.0, "TRY"),
            ("ASELS.IS", "stock", 150, 95.0, "TRY"),
            ("AFA", "fund", 5000, 1.85, "TRY"),     # a TEFAS fund code
            ("BTC-USD", "crypto", 0.05, 61000.0, "USD"),
            ("AAPL", "stock", 10, 190.0, "USD"),
        ]
        for tk, ac, qty, cost, ccy in holdings:
            db.add(Holding(
                user_id=USER_ID, ticker=tk, asset_class=ac, quantity=qty,
                cost_basis=cost, currency=ccy, acquired_at=today - timedelta(days=120),
            ))

        # Goals: emergency fund (62% done) + house down-payment (long horizon).
        db.add(Goal(
            user_id=USER_ID, title="Acil durum fonu", target_amount=100_000.0,
            current_amount=62_000.0, target_date=today + timedelta(days=180),
            currency="TRY", icon="shield",
        ))
        db.add(Goal(
            user_id=USER_ID, title="Ev peşinatı", target_amount=600_000.0,
            current_amount=120_000.0, target_date=today + timedelta(days=730),
            currency="TRY", icon="home",
        ))

        # A month of spending this + last month, across categories (TRY).
        this_month = today.replace(day=1)
        last_month = (this_month - timedelta(days=1)).replace(day=1)
        tx = [
            (this_month + timedelta(days=2), "income", 90_000, "salary", "Maaş"),
            (this_month + timedelta(days=4), "expense", 18_000, "rent", "Kira"),
            (this_month + timedelta(days=6), "expense", 6_200, "food", "Market + yemek"),
            (this_month + timedelta(days=9), "expense", 2_500, "subscriptions", "Abonelikler"),
            (this_month + timedelta(days=12), "expense", 3_100, "transport", "Ulaşım"),
            (this_month + timedelta(days=15), "expense", 4_400, "shopping", "Alışveriş"),
            (last_month + timedelta(days=4), "expense", 18_000, "rent", "Kira"),
            (last_month + timedelta(days=7), "expense", 5_500, "food", "Market + yemek"),
            (last_month + timedelta(days=2), "income", 90_000, "salary", "Maaş"),
        ]
        for occurred, kind, amount, cat, desc in tx:
            db.add(Transaction(
                user_id=USER_ID, occurred_on=occurred, type=kind, amount=float(amount),
                currency="TRY", category=cat, description=desc, source="manual",
            ))

        db.commit()
        counts = {
            "holdings": db.execute(
                select(Holding).where(Holding.user_id == USER_ID)
            ).scalars().all().__len__(),
            "goals": db.execute(
                select(Goal).where(Goal.user_id == USER_ID)
            ).scalars().all().__len__(),
            "transactions": db.execute(
                select(Transaction).where(Transaction.user_id == USER_ID)
            ).scalars().all().__len__(),
        }
    return counts


if __name__ == "__main__":
    print("seeded:", seed())
