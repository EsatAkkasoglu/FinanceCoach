"""Contract tests for POST /onboarding.

The one-screen onboarding (docs/URUN_ODAK.md) sends a reduced payload — no
accounts/income, currency/avatar defaulted. These lock the server-side schema
tolerance so a future OnboardingIn change can't silently break app entry.
"""
from __future__ import annotations


def test_minimal_payload_only_required_fields(client):
    """name + risk_score + risk_profile is enough; everything else defaults."""
    r = client.post(
        "/onboarding",
        json={"name": "Ada", "risk_score": 70, "risk_profile": "balanced"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True


def test_one_screen_payload_with_goal_and_holding(client):
    """The exact shape the one-screen wizard submits persists goal + holdings."""
    r = client.post(
        "/onboarding",
        json={
            "name": "Ada",
            "avatar": "fox",
            "monthly_income": 0,
            "risk_score": 110,
            "risk_profile": "aggressive",
            "spending_pace": 3,
            "goal": {
                "title": "Buy a home",
                "target_amount": 300000,
                "target_date": "2030-01-01",
                "icon": "home",
            },
            "holdings": [
                {"ticker": "thyao", "quantity": 10, "cost_basis": 250.0, "asset_class": "stock"},
            ],
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True

    # Goal persisted and surfaced.
    goals = client.get("/goals")
    assert goals.status_code == 200, goals.text
    assert any(g["title"] == "Buy a home" for g in goals.json())
