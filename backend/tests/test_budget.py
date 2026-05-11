"""End-to-end tests for the Budget routes (accounts, transactions, subscriptions, summary)."""
from __future__ import annotations

from datetime import date, timedelta


def test_account_crud(client):
    # CREATE
    r = client.post("/accounts", json={
        "name": "Ziraat",
        "kind": "checking",
        "balance": 12500,
        "currency": "TRY",
        "institution": "Ziraat Bankası",
    })
    assert r.status_code == 200, r.text
    a = r.json()
    assert a["name"] == "Ziraat"
    assert a["balance"] == 12500
    aid = a["id"]

    # LIST
    rows = client.get("/accounts").json()
    assert any(x["id"] == aid for x in rows)

    # PATCH balance
    r = client.patch(f"/accounts/{aid}", json={"balance": 13000})
    assert r.status_code == 200
    assert r.json()["balance"] == 13000

    # ARCHIVE / DELETE
    r = client.delete(f"/accounts/{aid}")
    assert r.status_code == 200
    rows = client.get("/accounts").json()
    assert all(x["id"] != aid for x in rows)


def test_account_validation(client):
    r = client.post("/accounts", json={"name": "", "kind": "checking"})
    assert r.status_code == 422
    r = client.post("/accounts", json={"name": "X", "kind": "savings_acct"})
    assert r.status_code == 422


def test_transaction_crud_and_balance_link(client):
    # Account in TRY with starting balance 1000.
    aid = client.post("/accounts", json={"name": "Wallet", "kind": "cash", "balance": 1000}).json()["id"]

    # Add an expense linked to the account → balance drops.
    r = client.post("/transactions", json={
        "occurred_on": str(date.today()),
        "type": "expense",
        "amount": 250,
        "currency": "TRY",
        "category": "groceries",
        "description": "Migros",
        "account_id": aid,
    })
    assert r.status_code == 200
    tx_id = r.json()["id"]

    # Balance reflects the spend.
    a = next(x for x in client.get("/accounts").json() if x["id"] == aid)
    assert a["balance"] == 750

    # Add an income → balance climbs.
    client.post("/transactions", json={
        "occurred_on": str(date.today()),
        "type": "income",
        "amount": 5000,
        "currency": "TRY",
        "category": "salary",
        "account_id": aid,
    })
    a = next(x for x in client.get("/accounts").json() if x["id"] == aid)
    assert a["balance"] == 5750

    # Update the expense to a smaller amount → balance recovers proportionally.
    client.patch(f"/transactions/{tx_id}", json={"amount": 100})
    a = next(x for x in client.get("/accounts").json() if x["id"] == aid)
    assert a["balance"] == 5900  # 1000 + 5000 - 100

    # Delete the income → balance drops.
    inc_id = [t for t in client.get("/transactions").json() if t["type"] == "income"][0]["id"]
    client.delete(f"/transactions/{inc_id}")
    a = next(x for x in client.get("/accounts").json() if x["id"] == aid)
    assert a["balance"] == 900


def test_transaction_filters(client):
    today = date.today()
    yesterday = today - timedelta(days=1)
    last_year = date(today.year - 1, today.month, 1)

    for d, t, c in [
        (today, "expense", "groceries"),
        (yesterday, "expense", "transport"),
        (last_year, "income", "salary"),
    ]:
        client.post("/transactions", json={
            "occurred_on": str(d), "type": t, "amount": 50, "currency": "TRY", "category": c,
        })

    # All
    assert len(client.get("/transactions").json()) == 3
    # Date filter
    rows = client.get(f"/transactions?from={yesterday.isoformat()}").json()
    assert len(rows) == 2
    # Type filter
    assert len(client.get("/transactions?type=income").json()) == 1
    # Category filter
    assert len(client.get("/transactions?category=transport").json()) == 1


def test_transaction_bulk(client):
    today = str(date.today())
    payload = {"items": [
        {"occurred_on": today, "type": "expense", "amount": 10, "category": "a"},
        {"occurred_on": today, "type": "expense", "amount": 20, "category": "b"},
        {"occurred_on": today, "type": "income",  "amount": 100, "category": "salary"},
    ]}
    r = client.post("/transactions/bulk", json=payload)
    assert r.status_code == 200
    assert r.json()["created"] == 3
    assert len(client.get("/transactions").json()) == 3


def test_subscription_crud(client):
    r = client.post("/subscriptions", json={
        "name": "Netflix",
        "amount": 149.99,
        "currency": "TRY",
        "cycle": "monthly",
        "next_charge_on": str(date.today() + timedelta(days=5)),
        "category": "streaming",
    })
    assert r.status_code == 200, r.text
    sid = r.json()["id"]

    # Soft cancel via active=false, then list active=False to confirm.
    client.patch(f"/subscriptions/{sid}", json={"active": False})
    actives = client.get("/subscriptions?active=true").json()
    inactives = client.get("/subscriptions?active=false").json()
    assert all(s["id"] != sid for s in actives)
    assert any(s["id"] == sid for s in inactives)


def test_budget_summary_shape(client):
    today = date.today()
    aid = client.post("/accounts", json={"name": "Bank", "balance": 5000, "currency": "TRY"}).json()["id"]

    client.post("/transactions", json={
        "occurred_on": str(today), "type": "income", "amount": 10000,
        "currency": "TRY", "category": "salary", "account_id": aid,
    })
    client.post("/transactions", json={
        "occurred_on": str(today), "type": "expense", "amount": 2500,
        "currency": "TRY", "category": "rent", "account_id": aid,
    })
    client.post("/subscriptions", json={
        "name": "Spotify", "amount": 79, "cycle": "monthly", "currency": "TRY",
        "next_charge_on": str(today + timedelta(days=3)),
    })
    client.post("/subscriptions", json={
        "name": "Domain", "amount": 360, "cycle": "yearly", "currency": "TRY",
    })

    s = client.get("/budget/summary").json()
    assert s["cash_on_hand"]["TRY"] > 0
    assert s["income_mtd"]["TRY"] == 10000
    assert s["expense_mtd"]["TRY"] == 2500
    # Top category present.
    assert any(c["category"] == "rent" for c in s["top_categories"])
    # Recurring expenses: Spotify monthly + Domain yearly normalised to monthly.
    assert s["recurring"]["expense_monthly_by_currency"]["TRY"] == round(79 + 360 / 12, 2)
    # No income-direction subs yet.
    assert s["recurring"]["income_monthly_by_currency"] == {}
    # Spotify is due in 3 days → in upcoming.
    assert any(u["name"] == "Spotify" for u in s["recurring"]["upcoming"])


def test_subscription_direction_income(client):
    today = date.today()
    r = client.post("/subscriptions", json={
        "name": "Salary",
        "amount": 50000,
        "currency": "TRY",
        "cycle": "monthly",
        "direction": "income",
        "category": "salary",
    })
    assert r.status_code == 200, r.text
    assert r.json()["direction"] == "income"

    # Adding another expense-direction sub to ensure the buckets are separate.
    client.post("/subscriptions", json={
        "name": "Netflix", "amount": 149, "currency": "TRY", "cycle": "monthly",
    })

    s = client.get("/budget/summary").json()
    assert s["recurring"]["income_monthly_by_currency"]["TRY"] == 50000
    assert s["recurring"]["expense_monthly_by_currency"]["TRY"] == 149
