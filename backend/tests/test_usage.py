"""Tests for per-user monthly usage metering + plan gating.

The pure helpers (period/limit/check_and_increment) run against the temp-SQLite
``client`` fixture's DB. The /usage endpoint is covered through the client.
"""
from __future__ import annotations

from app.services.usage import (
    check_and_increment,
    current_period,
    get_usage,
    monthly_limit,
)


def test_current_period_is_year_month():
    p = current_period()
    assert len(p) == 7 and p[4] == "-"


def test_free_tier_capped_pro_uncapped(monkeypatch):
    # Patch the settings object usage.py actually reads — the conftest reloads
    # the settings module for client-based tests, so `from app.settings import
    # settings` can resolve to a different instance than usage holds.
    import app.services.usage as usage_mod

    monkeypatch.setattr(usage_mod.settings, "free_monthly_chat_turns", 3)
    assert monthly_limit("free") == 3
    assert monthly_limit(None) == 3        # default tier is free
    assert monthly_limit("pro") is None    # uncapped


def test_zero_limit_disables_gate(monkeypatch):
    import app.services.usage as usage_mod

    monkeypatch.setattr(usage_mod.settings, "free_monthly_chat_turns", 0)
    assert monthly_limit("free") is None


def test_check_and_increment_blocks_after_cap(client, monkeypatch):
    import app.services.usage as usage_mod
    from app.db.session import SessionLocal

    monkeypatch.setattr(usage_mod.settings, "free_monthly_chat_turns", 2)
    with SessionLocal() as db:
        ok1, u1 = check_and_increment(db, 1, "free")
        ok2, u2 = check_and_increment(db, 1, "free")
        ok3, u3 = check_and_increment(db, 1, "free")

    assert ok1 and u1["used"] == 1 and u1["remaining"] == 1
    assert ok2 and u2["used"] == 2 and u2["remaining"] == 0
    assert not ok3                      # third turn refused
    assert u3["used"] == 2              # not incremented past the cap


def test_pro_tier_never_counted(client, monkeypatch):
    import app.services.usage as usage_mod
    from app.db.session import SessionLocal

    monkeypatch.setattr(usage_mod.settings, "free_monthly_chat_turns", 1)
    with SessionLocal() as db:
        for _ in range(5):
            ok, usage = check_and_increment(db, 1, "pro")
            assert ok
        assert usage["unlimited"] is True
        # No counter row churn for uncapped tiers.
        snap = get_usage(db, 1, "pro")
        assert snap["used"] == 0


def test_usage_endpoint(client, monkeypatch):
    import app.services.usage as usage_mod

    monkeypatch.setattr(usage_mod.settings, "free_monthly_chat_turns", 10)
    body = client.get("/usage").json()
    assert body["tier"] == "free"
    assert body["limit"] == 10
    assert body["used"] == 0
    assert body["remaining"] == 10
    assert body["unlimited"] is False
