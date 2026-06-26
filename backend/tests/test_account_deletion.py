"""KVKK right-to-erasure: DELETE /account wipes the user + all their data."""
from __future__ import annotations

from datetime import date


def _seed(user_id: int) -> None:
    from app.db.models import (
        Account,
        Goal,
        Holding,
        Transaction,
        UsageCounter,
        Watchlist,
    )
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        acc = Account(user_id=user_id, name="Main", kind="checking", balance=100.0)
        db.add(acc)
        db.flush()
        db.add_all([
            Holding(user_id=user_id, ticker="AAPL", quantity=1, cost_basis=100.0),
            Transaction(
                user_id=user_id, occurred_on=date.today(), type="expense",
                amount=50.0, category="market", account_id=acc.id,
            ),
            Goal(user_id=user_id, title="Fund", target_amount=1000.0),
            Watchlist(user_id=user_id, kind="symbol", value="AAPL"),
            UsageCounter(user_id=user_id, period="2026-06", chat_turns=5),
        ])
        db.commit()


def _counts(user_id: int) -> dict[str, int]:
    from sqlalchemy import func, select

    from app.db.models import (
        Account,
        Goal,
        Holding,
        Transaction,
        UsageCounter,
        User,
        Watchlist,
    )
    from app.db.session import SessionLocal

    out: dict[str, int] = {}
    with SessionLocal() as db:
        for label, model in {
            "user": User, "account": Account, "holding": Holding,
            "transaction": Transaction, "goal": Goal,
            "watchlist": Watchlist, "usage": UsageCounter,
        }.items():
            col = User.id if model is User else model.user_id
            out[label] = db.execute(
                select(func.count()).select_from(model).where(col == user_id)
            ).scalar_one()
    return out


def test_delete_account_wipes_all_user_data(client):
    _seed(1)
    before = _counts(1)
    assert before["user"] == 1 and before["holding"] == 1 and before["watchlist"] == 1

    r = client.delete("/account")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    # The summary reports what was removed per table.
    assert body["deleted"]["holding"] == 1
    assert body["deleted"]["user"] == 1

    after = _counts(1)
    assert all(v == 0 for v in after.values()), after


def test_delete_account_requires_auth(client):
    # Strip the bearer token the fixture bakes in.
    r = client.delete("/account", headers={"Authorization": ""})
    assert r.status_code == 401
