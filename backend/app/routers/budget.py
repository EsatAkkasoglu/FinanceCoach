"""Budget routes: accounts, transactions, subscriptions, summary.

All routes are scoped to the single demo user (id=1) for the prototype. When
the app goes multi-user, the dependency to inject is a `current_user` object
fetched from a session cookie or token; only the WHERE clauses change.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, select

from app.db.models import Account, Goal, Subscription, Transaction
from app.db.session import SessionLocal

USER_ID = 1  # single-user prototype

router = APIRouter(tags=["budget"])

# ── Pydantic payloads ───────────────────────────────────────────────────────

AccountKind = Literal["cash", "checking", "savings", "credit_card"]
TxType = Literal["income", "expense", "transfer"]
TxSource = Literal["manual", "upload", "chat", "subscription"]
SubCycle = Literal["weekly", "monthly", "quarterly", "yearly"]


class AccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: AccountKind = "checking"
    balance: float = 0.0
    currency: str = Field(default="TRY", max_length=8)
    institution: str | None = None
    color: str = "emerald"


class AccountUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    kind: AccountKind | None = None
    balance: float | None = None
    currency: str | None = Field(default=None, max_length=8)
    institution: str | None = None
    color: str | None = None
    archived: bool | None = None


class TransactionCreate(BaseModel):
    occurred_on: date
    type: TxType = "expense"
    amount: float = Field(gt=0)
    currency: str = Field(default="TRY", max_length=8)
    category: str = Field(default="uncategorized", max_length=64)
    description: str = ""
    source: TxSource = "manual"
    account_id: int | None = None
    subscription_id: int | None = None


class TransactionUpdate(BaseModel):
    occurred_on: date | None = None
    type: TxType | None = None
    amount: float | None = Field(default=None, gt=0)
    currency: str | None = Field(default=None, max_length=8)
    category: str | None = Field(default=None, max_length=64)
    description: str | None = None
    account_id: int | None = None


class TransactionBulk(BaseModel):
    items: list[TransactionCreate]


SubDirection = Literal["income", "expense"]


class SubscriptionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    amount: float = Field(gt=0)
    currency: str = Field(default="TRY", max_length=8)
    cycle: SubCycle = "monthly"
    direction: SubDirection = "expense"
    next_charge_on: date | None = None
    category: str = "subscriptions"
    icon: str | None = None
    account_id: int | None = None


class GoalCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    target_amount: float = Field(gt=0)
    current_amount: float = Field(default=0.0, ge=0)
    target_date: date | None = None
    icon: str = "target"


class GoalUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    target_amount: float | None = Field(default=None, gt=0)
    current_amount: float | None = Field(default=None, ge=0)
    target_date: date | None = None
    icon: str | None = None


class SubscriptionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    amount: float | None = Field(default=None, gt=0)
    currency: str | None = Field(default=None, max_length=8)
    cycle: SubCycle | None = None
    direction: SubDirection | None = None
    next_charge_on: date | None = None
    category: str | None = None
    icon: str | None = None
    account_id: int | None = None
    active: bool | None = None


# ── Serializers ─────────────────────────────────────────────────────────────


def _account_dict(a: Account) -> dict:
    return {
        "id": a.id,
        "name": a.name,
        "kind": a.kind,
        "balance": a.balance,
        "currency": a.currency,
        "institution": a.institution,
        "color": a.color,
        "archived": bool(a.archived),
    }


def _tx_dict(t: Transaction) -> dict:
    return {
        "id": t.id,
        "occurred_on": t.occurred_on.isoformat() if t.occurred_on else None,
        "type": t.type,
        "amount": t.amount,
        "currency": t.currency,
        "category": t.category,
        "description": t.description,
        "source": t.source,
        "account_id": t.account_id,
        "subscription_id": t.subscription_id,
    }


def _sub_dict(s: Subscription) -> dict:
    return {
        "id": s.id,
        "name": s.name,
        "amount": s.amount,
        "currency": s.currency,
        "cycle": s.cycle,
        "direction": s.direction or "expense",
        "next_charge_on": s.next_charge_on.isoformat() if s.next_charge_on else None,
        "category": s.category,
        "icon": s.icon,
        "account_id": s.account_id,
        "active": bool(s.active),
    }


# ── Accounts ────────────────────────────────────────────────────────────────


@router.get("/accounts")
def list_accounts():
    with SessionLocal() as db:
        rows = db.execute(
            select(Account).where(Account.user_id == USER_ID, Account.archived == 0)
            .order_by(Account.created_at)
        ).scalars().all()
        return [_account_dict(a) for a in rows]


@router.post("/accounts")
def create_account(payload: AccountCreate):
    with SessionLocal() as db:
        a = Account(user_id=USER_ID, **payload.model_dump())
        db.add(a)
        db.commit()
        db.refresh(a)
        return _account_dict(a)


@router.patch("/accounts/{account_id}")
def update_account(account_id: int, payload: AccountUpdate):
    with SessionLocal() as db:
        a = db.execute(
            select(Account).where(Account.id == account_id, Account.user_id == USER_ID)
        ).scalar_one_or_none()
        if a is None:
            raise HTTPException(404, "account not found")
        data = payload.model_dump(exclude_unset=True)
        if "archived" in data:
            a.archived = 1 if data.pop("archived") else 0
        for k, v in data.items():
            setattr(a, k, v)
        db.commit()
        db.refresh(a)
        return _account_dict(a)


@router.delete("/accounts/{account_id}")
def delete_account(account_id: int):
    with SessionLocal() as db:
        a = db.execute(
            select(Account).where(Account.id == account_id, Account.user_id == USER_ID)
        ).scalar_one_or_none()
        if a is None:
            raise HTTPException(404, "account not found")
        # Soft-archive — transactions referencing it remain queryable.
        a.archived = 1
        db.commit()
    return {"ok": True}


# ── Transactions ────────────────────────────────────────────────────────────


@router.get("/transactions")
def list_transactions(
    from_: date | None = Query(default=None, alias="from"),
    to: date | None = None,
    type: TxType | None = None,
    category: str | None = None,
    account_id: int | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
):
    with SessionLocal() as db:
        stmt = select(Transaction).where(Transaction.user_id == USER_ID)
        if from_:
            stmt = stmt.where(Transaction.occurred_on >= from_)
        if to:
            stmt = stmt.where(Transaction.occurred_on <= to)
        if type:
            stmt = stmt.where(Transaction.type == type)
        if category:
            stmt = stmt.where(Transaction.category == category)
        if account_id is not None:
            stmt = stmt.where(Transaction.account_id == account_id)
        stmt = stmt.order_by(Transaction.occurred_on.desc(), Transaction.id.desc()).limit(limit)
        rows = db.execute(stmt).scalars().all()
        return [_tx_dict(t) for t in rows]


@router.post("/transactions")
def create_transaction(payload: TransactionCreate):
    with SessionLocal() as db:
        t = Transaction(user_id=USER_ID, **payload.model_dump())
        _adjust_account_balance(db, t.account_id, t.type, t.amount, t.currency, sign=+1)
        db.add(t)
        db.commit()
        db.refresh(t)
        return _tx_dict(t)


@router.post("/transactions/bulk")
def create_transactions_bulk(payload: TransactionBulk):
    if not payload.items:
        return {"ok": True, "created": 0}
    with SessionLocal() as db:
        created = 0
        for item in payload.items:
            t = Transaction(user_id=USER_ID, **item.model_dump())
            _adjust_account_balance(db, t.account_id, t.type, t.amount, t.currency, sign=+1)
            db.add(t)
            created += 1
        db.commit()
        return {"ok": True, "created": created}


@router.patch("/transactions/{tx_id}")
def update_transaction(tx_id: int, payload: TransactionUpdate):
    with SessionLocal() as db:
        t = db.execute(
            select(Transaction).where(Transaction.id == tx_id, Transaction.user_id == USER_ID)
        ).scalar_one_or_none()
        if t is None:
            raise HTTPException(404, "transaction not found")
        # Reverse previous account effect, apply new.
        _adjust_account_balance(db, t.account_id, t.type, t.amount, t.currency, sign=-1)
        for k, v in payload.model_dump(exclude_unset=True).items():
            setattr(t, k, v)
        _adjust_account_balance(db, t.account_id, t.type, t.amount, t.currency, sign=+1)
        db.commit()
        db.refresh(t)
        return _tx_dict(t)


@router.delete("/transactions/{tx_id}")
def delete_transaction(tx_id: int):
    with SessionLocal() as db:
        t = db.execute(
            select(Transaction).where(Transaction.id == tx_id, Transaction.user_id == USER_ID)
        ).scalar_one_or_none()
        if t is None:
            raise HTTPException(404, "transaction not found")
        _adjust_account_balance(db, t.account_id, t.type, t.amount, t.currency, sign=-1)
        db.delete(t)
        db.commit()
    return {"ok": True}


def _adjust_account_balance(db, account_id, tx_type, amount, currency, *, sign: int) -> None:
    """When the transaction is tied to an account whose currency matches, mutate
    the running balance. Cross-currency transactions don't auto-convert (FX is
    out of scope for phase 1)."""
    if account_id is None:
        return
    a = db.execute(select(Account).where(Account.id == account_id)).scalar_one_or_none()
    if a is None or a.currency != currency:
        return
    if tx_type == "income":
        a.balance += sign * amount
    elif tx_type == "expense":
        a.balance -= sign * amount


# ── Subscriptions ───────────────────────────────────────────────────────────


@router.get("/subscriptions")
def list_subscriptions(active: bool | None = None):
    with SessionLocal() as db:
        stmt = select(Subscription).where(Subscription.user_id == USER_ID)
        if active is True:
            stmt = stmt.where(Subscription.active == 1)
        elif active is False:
            stmt = stmt.where(Subscription.active == 0)
        stmt = stmt.order_by(Subscription.next_charge_on.asc().nullslast(), Subscription.created_at)
        rows = db.execute(stmt).scalars().all()
        return [_sub_dict(s) for s in rows]


@router.post("/subscriptions")
def create_subscription(payload: SubscriptionCreate):
    with SessionLocal() as db:
        s = Subscription(user_id=USER_ID, **payload.model_dump())
        db.add(s)
        db.commit()
        db.refresh(s)
        return _sub_dict(s)


@router.patch("/subscriptions/{sub_id}")
def update_subscription(sub_id: int, payload: SubscriptionUpdate):
    with SessionLocal() as db:
        s = db.execute(
            select(Subscription).where(Subscription.id == sub_id, Subscription.user_id == USER_ID)
        ).scalar_one_or_none()
        if s is None:
            raise HTTPException(404, "subscription not found")
        data = payload.model_dump(exclude_unset=True)
        if "active" in data:
            s.active = 1 if data.pop("active") else 0
        for k, v in data.items():
            setattr(s, k, v)
        db.commit()
        db.refresh(s)
        return _sub_dict(s)


@router.delete("/subscriptions/{sub_id}")
def delete_subscription(sub_id: int):
    with SessionLocal() as db:
        s = db.execute(
            select(Subscription).where(Subscription.id == sub_id, Subscription.user_id == USER_ID)
        ).scalar_one_or_none()
        if s is None:
            raise HTTPException(404, "subscription not found")
        db.delete(s)
        db.commit()
    return {"ok": True}


# ── Goals ───────────────────────────────────────────────────────────────────


def _goal_dict(g: Goal) -> dict:
    return {
        "id": g.id,
        "title": g.title,
        "target_amount": g.target_amount,
        "current_amount": g.current_amount,
        "target_date": g.target_date.isoformat() if g.target_date else None,
        "icon": g.icon,
    }


@router.get("/goals")
def list_goals():
    with SessionLocal() as db:
        rows = db.execute(
            select(Goal).where(Goal.user_id == USER_ID).order_by(Goal.id)
        ).scalars().all()
        return [_goal_dict(g) for g in rows]


@router.post("/goals")
def create_goal(payload: GoalCreate):
    with SessionLocal() as db:
        g = Goal(user_id=USER_ID, **payload.model_dump())
        db.add(g)
        db.commit()
        db.refresh(g)
        return _goal_dict(g)


@router.patch("/goals/{goal_id}")
def update_goal(goal_id: int, payload: GoalUpdate):
    with SessionLocal() as db:
        g = db.execute(
            select(Goal).where(Goal.id == goal_id, Goal.user_id == USER_ID)
        ).scalar_one_or_none()
        if g is None:
            raise HTTPException(404, "goal not found")
        for k, v in payload.model_dump(exclude_unset=True).items():
            setattr(g, k, v)
        db.commit()
        db.refresh(g)
        return _goal_dict(g)


@router.delete("/goals/{goal_id}")
def delete_goal(goal_id: int):
    with SessionLocal() as db:
        g = db.execute(
            select(Goal).where(Goal.id == goal_id, Goal.user_id == USER_ID)
        ).scalar_one_or_none()
        if g is None:
            raise HTTPException(404, "goal not found")
        db.delete(g)
        db.commit()
    return {"ok": True}


# ── Summary ─────────────────────────────────────────────────────────────────


@router.get("/budget/summary")
def budget_summary(month: str | None = None):
    """One-call dashboard payload: balances, MTD flow, MoM deltas, top categories,
    upcoming subscription charges. Currencies are NOT converted — totals are
    grouped by currency so the UI can render side-by-side."""
    today = date.today()
    target = _parse_month(month) or today.replace(day=1)
    next_month = (target.replace(day=28) + timedelta(days=4)).replace(day=1)
    last_month_start = (target - timedelta(days=1)).replace(day=1)

    with SessionLocal() as db:
        # Cash on hand by currency (sum of non-credit-card account balances).
        cash_rows = db.execute(
            select(Account.currency, func.sum(Account.balance))
            .where(
                Account.user_id == USER_ID,
                Account.archived == 0,
                Account.kind != "credit_card",
            )
            .group_by(Account.currency)
        ).all()
        cash_by_ccy = {ccy: round(total or 0.0, 2) for ccy, total in cash_rows}

        debt_rows = db.execute(
            select(Account.currency, func.sum(Account.balance))
            .where(
                Account.user_id == USER_ID,
                Account.archived == 0,
                Account.kind == "credit_card",
            )
            .group_by(Account.currency)
        ).all()
        debt_by_ccy = {ccy: round(abs(total or 0.0), 2) for ccy, total in debt_rows}

        income_mtd = _sum_by_ccy(db, "income", target, next_month)
        expense_mtd = _sum_by_ccy(db, "expense", target, next_month)
        income_prev = _sum_by_ccy(db, "income", last_month_start, target)
        expense_prev = _sum_by_ccy(db, "expense", last_month_start, target)

        # Top spending categories this month.
        cat_rows = db.execute(
            select(Transaction.category, Transaction.currency, func.sum(Transaction.amount))
            .where(
                Transaction.user_id == USER_ID,
                Transaction.type == "expense",
                Transaction.occurred_on >= target,
                Transaction.occurred_on < next_month,
            )
            .group_by(Transaction.category, Transaction.currency)
            .order_by(func.sum(Transaction.amount).desc())
            .limit(5)
        ).all()
        top_categories = [
            {"category": c, "currency": ccy, "amount": round(total or 0.0, 2)}
            for c, ccy, total in cat_rows
        ]

        # Subscriptions due in next 30 days.
        horizon = today + timedelta(days=30)
        subs = db.execute(
            select(Subscription)
            .where(
                Subscription.user_id == USER_ID,
                Subscription.active == 1,
                Subscription.next_charge_on != None,  # noqa: E711
                Subscription.next_charge_on <= horizon,
            )
            .order_by(Subscription.next_charge_on)
        ).scalars().all()
        upcoming_subs = [_sub_dict(s) for s in subs]

        # Active recurring items normalized to monthly, split by direction.
        active_subs = db.execute(
            select(Subscription)
            .where(Subscription.user_id == USER_ID, Subscription.active == 1)
        ).scalars().all()
        expense_monthly: dict[str, float] = {}
        income_monthly: dict[str, float] = {}
        for s in active_subs:
            monthly = _normalize_to_monthly(s.amount, s.cycle)
            bucket = income_monthly if (s.direction or "expense") == "income" else expense_monthly
            bucket[s.currency] = bucket.get(s.currency, 0.0) + monthly

    return {
        "month": target.isoformat(),
        "cash_on_hand": cash_by_ccy,
        "credit_card_debt": debt_by_ccy,
        "income_mtd": income_mtd,
        "expense_mtd": expense_mtd,
        "income_prev_month": income_prev,
        "expense_prev_month": expense_prev,
        "top_categories": top_categories,
        "recurring": {
            "income_monthly_by_currency": {k: round(v, 2) for k, v in income_monthly.items()},
            "expense_monthly_by_currency": {k: round(v, 2) for k, v in expense_monthly.items()},
            "upcoming": upcoming_subs,
        },
    }


def _parse_month(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value + "-01", "%Y-%m-%d").date()
    except ValueError:
        return None


def _sum_by_ccy(db, tx_type: str, start: date, end: date) -> dict[str, float]:
    rows = db.execute(
        select(Transaction.currency, func.sum(Transaction.amount))
        .where(
            Transaction.user_id == USER_ID,
            Transaction.type == tx_type,
            Transaction.occurred_on >= start,
            Transaction.occurred_on < end,
        )
        .group_by(Transaction.currency)
    ).all()
    return {ccy: round(total or 0.0, 2) for ccy, total in rows}


def _normalize_to_monthly(amount: float, cycle: str) -> float:
    if cycle == "weekly":
        return amount * 52 / 12
    if cycle == "monthly":
        return amount
    if cycle == "quarterly":
        return amount / 3
    if cycle == "yearly":
        return amount / 12
    return amount
