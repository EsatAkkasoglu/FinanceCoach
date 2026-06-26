"""Billing flow via the mock provider: checkout → finalize → tier upgrade."""
from __future__ import annotations


def _tier(username: str = "demo") -> str:
    from sqlalchemy import select

    from app.db.models import User
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        return db.execute(select(User.tier).where(User.username == username)).scalar_one()


def test_plans_lists_pro_and_mock_provider(client):
    body = client.get("/billing/plans").json()
    assert body["provider"] == "mock"          # no iyzico keys in tests
    assert body["tier"] == "free"
    codes = [p["code"] for p in body["plans"]]
    assert "pro" in codes


def test_checkout_then_finalize_upgrades_to_pro(client):
    assert _tier() == "free"

    co = client.post("/billing/checkout", json={"plan": "pro", "return_url": "/x/return"})
    assert co.status_code == 200, co.text
    body = co.json()
    assert body["provider"] == "mock"
    ref = body["ref"]
    assert ref.startswith("mock_")
    assert "ref=" in body["redirect_url"]

    fin = client.post("/billing/finalize", json={"ref": ref, "params": {}})
    assert fin.status_code == 200, fin.text
    assert fin.json() == {"status": "paid", "tier": "pro"}
    assert _tier() == "pro"


def test_finalize_is_idempotent(client):
    co = client.post("/billing/checkout", json={"plan": "pro"}).json()
    client.post("/billing/finalize", json={"ref": co["ref"]})
    again = client.post("/billing/finalize", json={"ref": co["ref"]}).json()
    assert again["status"] == "paid" and again.get("already") is True


def test_failed_payment_does_not_upgrade(client):
    co = client.post("/billing/checkout", json={"plan": "pro"}).json()
    fin = client.post(
        "/billing/finalize", json={"ref": co["ref"], "params": {"simulate": "fail"}}
    )
    assert fin.json()["status"] == "failed"
    assert _tier() == "free"


def test_checkout_unknown_plan_404(client):
    r = client.post("/billing/checkout", json={"plan": "enterprise"})
    assert r.status_code == 404


def test_checkout_rejected_when_already_pro(client):
    co = client.post("/billing/checkout", json={"plan": "pro"}).json()
    client.post("/billing/finalize", json={"ref": co["ref"]})
    assert _tier() == "pro"
    r = client.post("/billing/checkout", json={"plan": "pro"})
    assert r.status_code == 409


def test_finalize_unknown_ref_404(client):
    r = client.post("/billing/finalize", json={"ref": "mock_nope"})
    assert r.status_code == 404
