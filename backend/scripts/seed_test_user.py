"""Create or refresh the shared FinCoach test user.

Usage:
    cd backend
    .venv\\Scripts\\python.exe scripts\\seed_test_user.py

The script is idempotent. It only resets data that belongs to the configured
test user, then recreates a broad sample dataset for auth, dashboard, budget,
portfolio, goals, subscriptions, conversations, documents, and net worth.
"""
from __future__ import annotations

import argparse
import sys
import uuid
from datetime import date, timedelta
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import delete, select  # noqa: E402

from app.auth.security import hash_password, verify_password  # noqa: E402
from app.db.models import (  # noqa: E402
    Account,
    ChatMessage,
    Conversation,
    Document,
    Goal,
    Holding,
    MessageFeedback,
    NetWorthSnapshot,
    Subscription,
    Transaction,
    User,
)
from app.db.session import SessionLocal, init_db  # noqa: E402

DEFAULT_LOGIN_USERNAME = "testUser"
DEFAULT_STORED_USERNAME = DEFAULT_LOGIN_USERNAME.lower()
DEFAULT_PASSWORD = "TestUser123!"


def safe_month_day(anchor: date, day: int) -> date:
    while True:
        try:
            return anchor.replace(day=day)
        except ValueError:
            day -= 1


def month_start(months_ago: int, today: date) -> date:
    year = today.year
    month = today.month - months_ago
    while month <= 0:
        month += 12
        year -= 1
    return date(year, month, 1)


def reset_test_user_data(db, user_id: int) -> None:
    for model in [
        MessageFeedback,
        NetWorthSnapshot,
        Conversation,
        ChatMessage,
        Transaction,
        Subscription,
        Account,
        Holding,
        Goal,
        Document,
    ]:
        db.execute(delete(model).where(model.user_id == user_id))


def ensure_test_user(db, username: str, password: str) -> User:
    stored_username = username.strip().lower()
    user = db.execute(select(User).where(User.username == stored_username)).scalar_one_or_none()
    if user is None:
        user = User(username=stored_username)
        db.add(user)
        db.flush()

    reset_test_user_data(db, user.id)
    user.password_hash = hash_password(password)
    user.name = "Test User"
    user.avatar = "sparkles"
    user.monthly_income = 92500.0
    user.risk_score = 82
    user.risk_profile = "aggressive"
    user.roast_mode = 1
    return user


def seed_accounts(db, user_id: int) -> list[Account]:
    rows = [
        Account(
            user_id=user_id,
            name="Garanti Vadesiz",
            kind="checking",
            balance=128450.75,
            currency="TRY",
            institution="Garanti BBVA",
            color="emerald",
        ),
        Account(
            user_id=user_id,
            name="USD Birikim",
            kind="savings",
            balance=18450.20,
            currency="USD",
            institution="Wise",
            color="sky",
        ),
        Account(
            user_id=user_id,
            name="Nakit Cuzdan",
            kind="cash",
            balance=3250.0,
            currency="TRY",
            institution=None,
            color="amber",
        ),
        Account(
            user_id=user_id,
            name="Kredi Karti",
            kind="credit_card",
            balance=-42150.35,
            currency="TRY",
            institution="Yapi Kredi",
            color="rose",
        ),
    ]
    db.add_all(rows)
    db.flush()
    return rows


def seed_holdings(db, user_id: int, today: date) -> list[Holding]:
    rows = [
        Holding(user_id=user_id, ticker="THYAO.IS", asset_class="stock", quantity=420, cost_basis=246.50, acquired_at=today - timedelta(days=260)),
        Holding(user_id=user_id, ticker="ASELS.IS", asset_class="stock", quantity=310, cost_basis=61.25, acquired_at=today - timedelta(days=210)),
        Holding(user_id=user_id, ticker="AAPL", asset_class="stock", quantity=18, cost_basis=176.40, acquired_at=today - timedelta(days=180)),
        Holding(user_id=user_id, ticker="NVDA", asset_class="stock", quantity=12, cost_basis=845.00, acquired_at=today - timedelta(days=95)),
        Holding(user_id=user_id, ticker="VOO", asset_class="etf", quantity=16, cost_basis=428.10, acquired_at=today - timedelta(days=310)),
        Holding(user_id=user_id, ticker="BTC-USD", asset_class="crypto", quantity=0.42, cost_basis=61500.0, acquired_at=today - timedelta(days=400)),
        Holding(user_id=user_id, ticker="USD", asset_class="cash", quantity=7500, cost_basis=1.0, acquired_at=today - timedelta(days=30)),
    ]
    db.add_all(rows)
    return rows


def seed_goals(db, user_id: int, today: date) -> list[Goal]:
    rows = [
        Goal(user_id=user_id, title="Acil durum fonu", target_amount=250000, current_amount=168000, target_date=today + timedelta(days=120), icon="🛟"),
        Goal(user_id=user_id, title="Ev pesinati", target_amount=1500000, current_amount=410000, target_date=today + timedelta(days=540), icon="🏠"),
        Goal(user_id=user_id, title="Yillik tatil", target_amount=90000, current_amount=38500, target_date=today + timedelta(days=75), icon="✈️"),
    ]
    db.add_all(rows)
    return rows


def seed_subscriptions(db, user_id: int, accounts: list[Account], today: date) -> list[Subscription]:
    checking, usd_savings, _cash_wallet, credit_card = accounts
    rows = [
        Subscription(user_id=user_id, name="Maas", amount=92500, currency="TRY", cycle="monthly", direction="income", next_charge_on=safe_month_day(today, 28), category="salary", icon="briefcase", account_id=checking.id),
        Subscription(user_id=user_id, name="Kira", amount=31500, currency="TRY", cycle="monthly", direction="expense", next_charge_on=today + timedelta(days=7), category="rent", icon="home", account_id=checking.id),
        Subscription(user_id=user_id, name="Netflix", amount=229.99, currency="TRY", cycle="monthly", direction="expense", next_charge_on=today + timedelta(days=11), category="entertainment", icon="tv", account_id=credit_card.id),
        Subscription(user_id=user_id, name="Spotify", amount=59.99, currency="TRY", cycle="monthly", direction="expense", next_charge_on=today + timedelta(days=4), category="entertainment", icon="music", account_id=credit_card.id),
        Subscription(user_id=user_id, name="Yillik sigorta", amount=18400, currency="TRY", cycle="yearly", direction="expense", next_charge_on=today + timedelta(days=23), category="insurance", icon="shield", account_id=checking.id),
        Subscription(user_id=user_id, name="AI Tools", amount=20, currency="USD", cycle="monthly", direction="expense", next_charge_on=today + timedelta(days=14), category="software", icon="software", account_id=usd_savings.id),
    ]
    db.add_all(rows)
    db.flush()
    return rows


def seed_transactions(
    db,
    user_id: int,
    accounts: list[Account],
    subscriptions: list[Subscription],
    today: date,
) -> list[Transaction]:
    checking, usd_savings, _cash_wallet, credit_card = accounts
    salary_sub, rent_sub, netflix_sub, spotify_sub, *_rest = subscriptions
    rows: list[Transaction] = []

    for months_ago in range(5, -1, -1):
        anchor = month_start(months_ago, today)
        rows.extend(
            [
                Transaction(user_id=user_id, occurred_on=safe_month_day(anchor, 1), type="income", amount=92500, currency="TRY", category="salary", description="Fintek A.S. maas", source="subscription", account_id=checking.id, subscription_id=salary_sub.id),
                Transaction(user_id=user_id, occurred_on=safe_month_day(anchor, 3), type="expense", amount=31500, currency="TRY", category="rent", description="Kira odemesi", source="subscription", account_id=checking.id, subscription_id=rent_sub.id),
                Transaction(user_id=user_id, occurred_on=safe_month_day(anchor, 5), type="expense", amount=4200 + months_ago * 120, currency="TRY", category="groceries", description="Market alisverisi", source="manual", account_id=credit_card.id),
                Transaction(user_id=user_id, occurred_on=safe_month_day(anchor, 9), type="expense", amount=1650 + months_ago * 75, currency="TRY", category="transport", description="Ulasim ve yakit", source="manual", account_id=credit_card.id),
                Transaction(user_id=user_id, occurred_on=safe_month_day(anchor, 12), type="expense", amount=2400 + months_ago * 140, currency="TRY", category="dining", description="Disarida yemek", source="manual", account_id=credit_card.id),
                Transaction(user_id=user_id, occurred_on=safe_month_day(anchor, 16), type="expense", amount=1850 + months_ago * 90, currency="TRY", category="utilities", description="Elektrik, su ve internet", source="upload", account_id=checking.id),
                Transaction(user_id=user_id, occurred_on=safe_month_day(anchor, 18), type="expense", amount=7500, currency="TRY", category="investment", description="Otomatik fon/ETF alim birikimi", source="chat", account_id=checking.id),
                Transaction(user_id=user_id, occurred_on=safe_month_day(anchor, 21), type="expense", amount=950 + months_ago * 50, currency="TRY", category="health", description="Spor ve saglik", source="manual", account_id=credit_card.id),
            ]
        )

    rows.extend(
        [
            Transaction(user_id=user_id, occurred_on=today - timedelta(days=2), type="income", amount=12500, currency="TRY", category="freelance", description="Danismanlik geliri", source="manual", account_id=checking.id),
            Transaction(user_id=user_id, occurred_on=today - timedelta(days=1), type="expense", amount=3400, currency="TRY", category="shopping", description="Teknoloji aksesuarlari", source="manual", account_id=credit_card.id),
            Transaction(user_id=user_id, occurred_on=today - timedelta(days=3), type="expense", amount=820, currency="USD", category="software", description="AI arac aboneligi", source="subscription", account_id=usd_savings.id),
            Transaction(user_id=user_id, occurred_on=today - timedelta(days=4), type="transfer", amount=1000, currency="USD", category="fx", description="TRY -> USD birikim transferi", source="manual", account_id=usd_savings.id),
            Transaction(user_id=user_id, occurred_on=today, type="expense", amount=229.99, currency="TRY", category="entertainment", description="Netflix", source="subscription", account_id=credit_card.id, subscription_id=netflix_sub.id),
            Transaction(user_id=user_id, occurred_on=today, type="expense", amount=59.99, currency="TRY", category="entertainment", description="Spotify", source="subscription", account_id=credit_card.id, subscription_id=spotify_sub.id),
        ]
    )
    db.add_all(rows)
    return rows


def seed_misc(db, user_id: int, today: date) -> tuple[str, str, int]:
    db.add(Document(user_id=user_id, filename="test-user-hesap-ozeti.pdf", kind="bank_statement", parsed_count=18))

    conversation_id = str(uuid.uuid4())
    thread_id = str(uuid.uuid4())
    db.add(
        Conversation(
            id=conversation_id,
            user_id=user_id,
            thread_id=thread_id,
            title="Test kullanici demo sohbeti",
        )
    )
    db.add_all(
        [
            ChatMessage(user_id=user_id, role="user", content="Portfoyum ve butcem icin hizli bir ozet cikar.", agent=None),
            ChatMessage(
                user_id=user_id,
                role="assistant",
                content="Portfoyun hisse, ETF, kripto ve nakit dagilimi iceriyor; butcede kira en buyuk kalem, yatirim disiplinin guclu.",
                agent="advisor",
                citations='[{"tool":"portfolio_summary"}]',
            ),
        ]
    )
    db.add(
        MessageFeedback(
            user_id=user_id,
            thread_id=thread_id,
            message_id="a-test-demo",
            rating="up",
            reason="Demo yaniti faydali",
            agent="advisor",
            excerpt="Portfoyun hisse, ETF, kripto ve nakit dagilimi iceriyor.",
        )
    )

    snapshot_count = 0
    for days_ago in range(29, -1, -3):
        value = 735000 + (29 - days_ago) * 4200 + (days_ago % 5) * 1800
        db.add(
            NetWorthSnapshot(
                user_id=user_id,
                captured_on=today - timedelta(days=days_ago),
                value=value,
                currency="TRY",
            )
        )
        snapshot_count += 1
    return conversation_id, thread_id, snapshot_count


def seed_test_user(username: str, password: str) -> dict:
    today = date.today()
    init_db()

    with SessionLocal() as db:
        user = ensure_test_user(db, username, password)
        accounts = seed_accounts(db, user.id)
        holdings = seed_holdings(db, user.id, today)
        goals = seed_goals(db, user.id, today)
        subscriptions = seed_subscriptions(db, user.id, accounts, today)
        transactions = seed_transactions(db, user.id, accounts, subscriptions, today)
        conversation_id, thread_id, snapshot_count = seed_misc(db, user.id, today)

        db.commit()
        db.refresh(user)

        return {
            "user_id": user.id,
            "login_username": username,
            "stored_username": user.username,
            "password_verified": verify_password(password, user.password_hash),
            "accounts": len(accounts),
            "holdings": len(holdings),
            "goals": len(goals),
            "subscriptions": len(subscriptions),
            "transactions": len(transactions),
            "net_worth_points": snapshot_count,
            "conversation_id": conversation_id,
            "thread_id": thread_id,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed the FinCoach test user.")
    parser.add_argument("--username", default=DEFAULT_LOGIN_USERNAME)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    args = parser.parse_args()

    result = seed_test_user(args.username, args.password)
    print("Seeded test user.")
    print(f"  Login username: {result['login_username']}")
    print(f"  Password:       {args.password}")
    print(f"  Stored user:    {result['stored_username']} (id={result['user_id']})")
    print(f"  Password OK:    {result['password_verified']}")
    print(
        "  Rows:           "
        f"{result['accounts']} accounts, "
        f"{result['holdings']} holdings, "
        f"{result['goals']} goals, "
        f"{result['subscriptions']} subscriptions, "
        f"{result['transactions']} transactions, "
        f"{result['net_worth_points']} net-worth points"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
