"""Smoke tests for the new /profile and /portfolio/holdings CRUD endpoints.

Uses an isolated tmp SQLite per test (see conftest.client). No network calls.
The /portfolio enrichment endpoint hits yfinance, so we don't assert on prices —
holdings CRUD is exercised through the dedicated CRUD routes only.
"""
from __future__ import annotations


def test_get_profile_returns_seeded_user(client):
    r = client.get("/profile")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == 1
    assert body["name"] == "Demo User"
    assert body["risk_profile"] == "balanced"
    assert body["roast_mode"] is False


def test_patch_profile_updates_only_supplied_fields(client):
    r = client.patch("/profile", json={"name": "Esat", "monthly_income": 12500})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "Esat"
    assert body["monthly_income"] == 12500
    # Untouched field stayed at the seed value.
    assert body["risk_profile"] == "balanced"

    r2 = client.patch("/profile", json={"roast_mode": True, "risk_profile": "aggressive"})
    assert r2.status_code == 200
    body2 = r2.json()
    assert body2["roast_mode"] is True
    assert body2["risk_profile"] == "aggressive"
    assert body2["name"] == "Esat"  # name from previous patch persisted


def test_patch_profile_rejects_invalid_values(client):
    # risk_score must be 0–125
    r = client.patch("/profile", json={"risk_score": 999})
    assert r.status_code == 422

    # risk_profile is a Literal
    r = client.patch("/profile", json={"risk_profile": "yolo"})
    assert r.status_code == 422

    # negative income
    r = client.patch("/profile", json={"monthly_income": -1})
    assert r.status_code == 422


def test_create_update_delete_holding(client):
    # CREATE
    r = client.post(
        "/portfolio/holdings",
        json={"ticker": "aapl", "quantity": 10, "cost_basis": 150.5, "asset_class": "stock"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["ticker"] == "AAPL"  # uppercased server-side
    holding_id = body["id"]

    # PATCH partial
    r = client.patch(f"/portfolio/holdings/{holding_id}", json={"quantity": 12})
    assert r.status_code == 200
    body = r.json()
    assert body["quantity"] == 12
    assert body["cost_basis"] == 150.5  # untouched
    assert body["ticker"] == "AAPL"

    # PATCH ticker normalisation
    r = client.patch(f"/portfolio/holdings/{holding_id}", json={"ticker": "msft"})
    assert r.status_code == 200
    assert r.json()["ticker"] == "MSFT"

    # DELETE
    r = client.delete(f"/portfolio/holdings/{holding_id}")
    assert r.status_code == 200
    assert r.json() == {"ok": True}

    # Subsequent ops on a deleted id 404
    assert client.patch(f"/portfolio/holdings/{holding_id}", json={"quantity": 1}).status_code == 404
    assert client.delete(f"/portfolio/holdings/{holding_id}").status_code == 404


def test_create_holding_validation(client):
    # quantity must be > 0
    r = client.post(
        "/portfolio/holdings",
        json={"ticker": "AAPL", "quantity": 0, "cost_basis": 1, "asset_class": "stock"},
    )
    assert r.status_code == 422

    # asset_class is a Literal
    r = client.post(
        "/portfolio/holdings",
        json={"ticker": "AAPL", "quantity": 1, "asset_class": "nft"},
    )
    assert r.status_code == 422


def test_holding_isolation_per_user(client):
    """user_id filter: a holding belonging to user_id != 1 must not be reachable."""
    from app.db.models import Holding
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        other = Holding(user_id=42, ticker="GOOG", asset_class="stock", quantity=5, cost_basis=100)
        db.add(other)
        db.commit()
        db.refresh(other)
        other_id = other.id

    assert client.patch(f"/portfolio/holdings/{other_id}", json={"quantity": 9}).status_code == 404
    assert client.delete(f"/portfolio/holdings/{other_id}").status_code == 404
