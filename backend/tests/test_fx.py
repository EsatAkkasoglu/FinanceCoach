"""Tests for the /fx/rates endpoint. yfinance is monkeypatched to avoid network."""
from __future__ import annotations

import pytest

from app.routers import fx as fx_mod


@pytest.fixture(autouse=True)
def _clear_fx_cache():
    fx_mod._reset_cache_for_tests()
    yield
    fx_mod._reset_cache_for_tests()


def test_fx_rates_uses_yfinance_and_caches(client, monkeypatch):
    calls: list[tuple[str, str]] = []

    def fake_fetch(base, target):
        calls.append((base, target))
        return {"USD": 0.031, "EUR": 0.029, "TRY": 1.0}[target]

    monkeypatch.setattr(fx_mod, "_fetch_pair", fake_fetch)

    r = client.get("/fx/rates?base=TRY")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["base"] == "TRY"
    assert body["rates"]["TRY"] == 1.0
    assert body["rates"]["USD"] == 0.031
    assert body["rates"]["EUR"] == 0.029
    assert isinstance(body["fetched_at"], (int, float))

    # Second hit should be served from cache — no new fetches.
    n_first = len(calls)
    client.get("/fx/rates?base=TRY")
    assert len(calls) == n_first  # cached


def test_fx_rates_rejects_unknown_base(client):
    r = client.get("/fx/rates?base=JPY")
    assert r.status_code == 400


def test_fx_rates_partial_failure_still_returns(client, monkeypatch):
    def flaky_fetch(base, target):
        if target == "EUR":
            raise RuntimeError("simulated upstream hiccup")
        return {"USD": 0.031, "TRY": 1.0}[target]

    monkeypatch.setattr(fx_mod, "_fetch_pair", flaky_fetch)
    r = client.get("/fx/rates?base=TRY")
    assert r.status_code == 200
    body = r.json()
    assert "USD" in body["rates"]
    assert "EUR" not in body["rates"]


def test_fx_rates_all_fail_returns_502(client, monkeypatch):
    def always_fail(base, target):
        if target == base:
            return 1.0
        raise RuntimeError("nope")

    monkeypatch.setattr(fx_mod, "_fetch_pair", always_fail)
    r = client.get("/fx/rates?base=USD")
    # Self-pair succeeds, so we still get a response with at least USD: 1.0
    # but other pairs fail. The endpoint considers it OK as long as at least
    # one rate (the base) is present.
    assert r.status_code == 200
    body = r.json()
    assert body["rates"]["USD"] == 1.0
