"""Seed realistic 6-month transaction history for the demo user.

Why this exists
---------------
Without it, Budget Coach has nothing to analyze and Dashboard's "today's
brief" can't compute personal cash-flow signals. Run once to populate.

Usage
-----
    cd backend
    uv run python scripts/seed_demo.py            # additive, keeps existing
    uv run python scripts/seed_demo.py --reset    # wipe txs first
    uv run python scripts/seed_demo.py --months 12
    uv run python scripts/seed_demo.py --reset --with-portfolio
        ↑ also seeds 4 starting holdings (NVDA, AAPL, BTC, cash)

Output
------
Prints summary: total txs, monthly avg expense, top categories.

Idempotency
-----------
Without --reset, this APPENDS. Recommended path is --reset on a fresh
install or whenever you need a clean demo state.
"""
from __future__ import annotations

import argparse
import random
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

# Allow `python scripts/seed_demo.py` from the backend dir.
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import delete, select  # noqa: E402

from app.db.models import Holding, Transaction, User  # noqa: E402
from app.db.session import SessionLocal, init_db  # noqa: E402


# ---------------------------------------------------------------------------
# Pattern config — tune these to shape the demo persona's spending
# ---------------------------------------------------------------------------

PERSONA_NAME = "Alex Carter"
MONTHLY_INCOME_USD = 7500.0

# Recurring fixed-amount lines: (day_of_month, amount, category, description)
MONTHLY_RECURRING_INCOME: list[tuple[int, float, str, str]] = [
    (1, MONTHLY_INCOME_USD, "salary", "Acme Corp Payroll"),
]

MONTHLY_RECURRING_EXPENSE: list[tuple[int, float, str, str]] = [
    (1, 2200.00, "rent",          "Apartment Lease"),
    (5,   79.99, "utilities",     "Comcast Internet"),
    (15,  65.00, "utilities",     "T-Mobile"),
    (3,   45.00, "health",        "Equinox Gym"),
    (12,  19.99, "entertainment", "Netflix"),
    (8,    9.99, "entertainment", "Apple TV+"),
    (20,  11.99, "entertainment", "Spotify"),
]

# Variable monthly: utility bills (amount range)
MONTHLY_VARIABLE_EXPENSE: list[tuple[int, tuple[float, float], str, str]] = [
    (10, (90.0, 140.0), "utilities", "PG&E Electric"),
]

# Weekly grocery shop (one trip per week)
GROCERY_AMOUNT = (85.0, 180.0)
GROCERY_MERCHANTS = ["Whole Foods", "Trader Joe's", "Safeway", "Costco", "H Mart"]

# Per-week burst: dining outings
DINING_PER_WEEK = (3, 6)
DINING_AMOUNT = (12.0, 80.0)
DINING_MERCHANTS = [
    "Chipotle", "Sweetgreen", "Joe's Pizza", "Tartine Bakery", "Blue Bottle Coffee",
    "The Slanted Door", "Souvla", "Kismet", "Mensho Ramen", "Boba Guys",
]

# Per-week burst: transport
TRANSPORT_PER_WEEK = (4, 8)
TRANSPORT_AMOUNT = (6.0, 35.0)
TRANSPORT_MERCHANTS = ["Uber", "Lyft", "BART", "Caltrain", "Shell"]

# Sporadic per-month: (count_range, amount_range, category, merchants)
SPORADIC: list[tuple[tuple[int, int], tuple[float, float], str, list[str]]] = [
    ((1, 4), (25.0, 250.0),  "shopping",      ["Amazon", "Target", "Apple Store", "Best Buy", "REI", "Uniqlo"]),
    ((0, 2), (15.0, 80.0),   "health",        ["CVS Pharmacy", "Walgreens", "Rite Aid"]),
    ((0, 2), (40.0, 200.0),  "entertainment", ["AMC Theaters", "Steam", "Concert Tickets", "Local Theatre"]),
    ((0, 1), (200.0, 1500.0), "travel",       ["United Airlines", "Airbnb", "Hilton Hotels", "Delta Airlines"]),
]

# Optional starting portfolio (--with-portfolio)
DEMO_HOLDINGS: list[tuple[str, str, float, float]] = [
    # ticker, asset_class, quantity, cost_basis
    ("NVDA",    "stock",  50.0,  120.50),
    ("AAPL",    "stock",  30.0,  175.20),
    ("VOO",     "etf",    20.0,  410.00),
    ("BTC-USD", "crypto",  0.5,  62000.0),
    ("USD",     "cash",   8000.0, 1.0),
]


# ---------------------------------------------------------------------------
# Generators
# ---------------------------------------------------------------------------

@dataclass
class TxRow:
    occurred_on: date
    type: str           # "income" | "expense"
    amount: float
    category: str
    description: str


def _safe_date(year: int, month: int, day: int) -> date:
    """Some months don't have day 30/31. Clamp to month-end."""
    while True:
        try:
            return date(year, month, day)
        except ValueError:
            day -= 1


def _months_back(end: date, count: int) -> list[tuple[int, int]]:
    """Return list of (year, month) tuples covering ``count`` months ending in ``end``."""
    out: list[tuple[int, int]] = []
    y, m = end.year, end.month
    for _ in range(count):
        out.append((y, m))
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    out.reverse()
    return out


def generate_transactions(months: int, end: date, rng: random.Random) -> list[TxRow]:
    rows: list[TxRow] = []
    period_months = _months_back(end, months)
    start = date(period_months[0][0], period_months[0][1], 1)

    # --- Recurring monthly income / expense (fixed amounts) ---
    for (y, m) in period_months:
        for day, amt, cat, desc in MONTHLY_RECURRING_INCOME:
            rows.append(TxRow(_safe_date(y, m, day), "income", amt, cat, desc))
        for day, amt, cat, desc in MONTHLY_RECURRING_EXPENSE:
            jitter_day = max(1, day + rng.randint(-1, 1))
            rows.append(TxRow(_safe_date(y, m, jitter_day), "expense", amt, cat, desc))
        for day, (lo, hi), cat, desc in MONTHLY_VARIABLE_EXPENSE:
            jitter_day = max(1, day + rng.randint(-2, 2))
            rows.append(TxRow(
                _safe_date(y, m, jitter_day), "expense",
                round(rng.uniform(lo, hi), 2), cat, desc,
            ))

    # --- Weekly grocery + per-week dining/transport bursts ---
    cursor = start
    while cursor <= end:
        # Grocery shop on a random day of the week
        gday = cursor + timedelta(days=rng.randint(0, 6))
        if gday <= end:
            rows.append(TxRow(
                gday, "expense",
                round(rng.uniform(*GROCERY_AMOUNT), 2),
                "groceries",
                rng.choice(GROCERY_MERCHANTS),
            ))

        # Dining (3-6 outings per week)
        for _ in range(rng.randint(*DINING_PER_WEEK)):
            d = cursor + timedelta(days=rng.randint(0, 6))
            if d > end:
                continue
            rows.append(TxRow(
                d, "expense",
                round(rng.uniform(*DINING_AMOUNT), 2),
                "dining",
                rng.choice(DINING_MERCHANTS),
            ))

        # Transport (4-8 trips per week)
        for _ in range(rng.randint(*TRANSPORT_PER_WEEK)):
            d = cursor + timedelta(days=rng.randint(0, 6))
            if d > end:
                continue
            rows.append(TxRow(
                d, "expense",
                round(rng.uniform(*TRANSPORT_AMOUNT), 2),
                "transport",
                rng.choice(TRANSPORT_MERCHANTS),
            ))

        cursor += timedelta(days=7)

    # --- Sporadic per-month items (shopping, travel, etc.) ---
    for (y, m) in period_months:
        for (lo_n, hi_n), (lo_a, hi_a), cat, merchants in SPORADIC:
            count = rng.randint(lo_n, hi_n)
            for _ in range(count):
                day = rng.randint(1, 28)
                rows.append(TxRow(
                    _safe_date(y, m, day), "expense",
                    round(rng.uniform(lo_a, hi_a), 2),
                    cat,
                    rng.choice(merchants),
                ))

    rows.sort(key=lambda r: r.occurred_on)
    return rows


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def ensure_user(db) -> User:
    user = db.execute(select(User).where(User.id == 1)).scalar_one_or_none()
    if user is None:
        user = User(id=1, name=PERSONA_NAME, monthly_income=MONTHLY_INCOME_USD,
                    risk_score=70, risk_profile="balanced")
        db.add(user)
        db.flush()
    elif not user.name or user.name == "Demo User":
        user.name = PERSONA_NAME
        user.monthly_income = MONTHLY_INCOME_USD
    return user


def reset_transactions(db) -> int:
    """Delete all transactions for user 1. Returns count deleted."""
    rows = db.execute(select(Transaction).where(Transaction.user_id == 1)).scalars().all()
    n = len(rows)
    if n:
        db.execute(delete(Transaction).where(Transaction.user_id == 1))
    return n


def reset_holdings(db) -> int:
    rows = db.execute(select(Holding).where(Holding.user_id == 1)).scalars().all()
    n = len(rows)
    if n:
        db.execute(delete(Holding).where(Holding.user_id == 1))
    return n


def insert_transactions(db, user_id: int, rows: list[TxRow]) -> None:
    for r in rows:
        db.add(Transaction(
            user_id=user_id,
            occurred_on=r.occurred_on,
            type=r.type,
            amount=r.amount,
            currency="USD",
            category=r.category,
            description=r.description,
        ))


def insert_holdings(db, user_id: int) -> None:
    today = date.today()
    for ticker, asset_class, qty, cost in DEMO_HOLDINGS:
        db.add(Holding(
            user_id=user_id,
            ticker=ticker,
            asset_class=asset_class,
            quantity=qty,
            cost_basis=cost,
            acquired_at=today - timedelta(days=180),
        ))


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def summarize(rows: list[TxRow]) -> str:
    if not rows:
        return "No transactions generated."
    total_income = sum(r.amount for r in rows if r.type == "income")
    total_expense = sum(r.amount for r in rows if r.type == "expense")
    months_span = (rows[-1].occurred_on - rows[0].occurred_on).days / 30.0 or 1
    by_cat: dict[str, float] = {}
    for r in rows:
        if r.type == "expense":
            by_cat[r.category] = by_cat.get(r.category, 0.0) + r.amount
    top = sorted(by_cat.items(), key=lambda x: -x[1])[:5]
    out = [
        f"Generated {len(rows)} transactions",
        f"  Span:           {rows[0].occurred_on} → {rows[-1].occurred_on}  ({months_span:.1f} months)",
        f"  Total income:   ${total_income:>10,.2f}",
        f"  Total expense:  ${total_expense:>10,.2f}",
        f"  Net savings:    ${total_income - total_expense:>10,.2f}  "
        f"({(total_income - total_expense) / total_income * 100:.1f}% of income)",
        f"  Avg monthly:    ${total_expense / months_span:>10,.2f}  expense",
        "",
        "  Top categories:",
    ]
    for cat, amt in top:
        out.append(f"    {cat:14} ${amt:>9,.2f}  ({amt / total_expense * 100:4.1f}%)")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Seed FinCoach demo data")
    parser.add_argument("--reset", action="store_true",
                        help="Wipe existing transactions for user 1 first")
    parser.add_argument("--with-portfolio", action="store_true",
                        help="Also seed 5 demo holdings (NVDA, AAPL, VOO, BTC, cash)")
    parser.add_argument("--months", type=int, default=6,
                        help="How many months of history to generate (default 6)")
    parser.add_argument("--seed", type=int, default=42,
                        help="Random seed for reproducible demo data")
    parser.add_argument("--end", type=str, default=None,
                        help="End date YYYY-MM-DD (default: today)")
    args = parser.parse_args()

    end_date = date.fromisoformat(args.end) if args.end else date.today()
    rng = random.Random(args.seed)

    init_db()  # ensure tables + default user exist

    rows = generate_transactions(args.months, end_date, rng)

    with SessionLocal() as db:
        user = ensure_user(db)

        if args.reset:
            n_tx = reset_transactions(db)
            print(f"Reset: removed {n_tx} prior transactions")
            if args.with_portfolio:
                n_h = reset_holdings(db)
                print(f"Reset: removed {n_h} prior holdings")

        insert_transactions(db, user.id, rows)
        if args.with_portfolio:
            insert_holdings(db, user.id)
            print(f"Seeded {len(DEMO_HOLDINGS)} starting holdings")

        db.commit()

    print()
    print(summarize(rows))
    print()
    print(f"Done. Run the backend and ask the Coach:")
    print(f"  - 'How much did I spend last month?'")
    print(f"  - 'What's my biggest expense category?'")
    print(f"  - 'Compare this month to last month'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
