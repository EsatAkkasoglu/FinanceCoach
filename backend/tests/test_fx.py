"""Tests for the /fx/rates endpoint. Upstream provider is monkeypatched to avoid network."""
from __future__ import annotations

import pytest

from app.routers import fx as fx_mod


@pytest.fixture(autouse=True)
def _clear_fx_cache():
    fx_mod._reset_cache_for_tests()
    yield
    fx_mod._reset_cache_for_tests()


def test_fx_rates_uses_api_and_caches(client, monkeypatch):
    calls: list[str] = []

    def fake_fetch(base: str) -> dict[str, float]:
        calls.append(base)
        rates = {"USD": 0.031, "EUR": 0.029, "TRY": 1.0}
        return {k: v / rates[base] for k, v in rates.items()}

    monkeypatch.setattr(fx_mod, "_fetch_from_api", fake_fetch)

    r = client.get("/fx/rates?base=TRY")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["base"] == "TRY"
    assert body["rates"]["TRY"] == 1.0
    assert abs(body["rates"]["USD"] - 0.031) < 1e-6
    assert abs(body["rates"]["EUR"] - 0.029) < 1e-6
    assert isinstance(body["fetched_at"], (int, float))

    # Second hit should be served from cache — no new fetches.
    n_first = len(calls)
    client.get("/fx/rates?base=TRY")
    assert len(calls) == n_first  # cached


def test_fx_rates_rejects_unknown_base(client):
    r = client.get("/fx/rates?base=JPY")
    assert r.status_code == 400


def test_fx_rates_provider_failure_returns_502(client, monkeypatch):
    def always_fail(base: str) -> dict[str, float]:
        raise RuntimeError("nope")

    monkeypatch.setattr(fx_mod, "_fetch_from_api", always_fail)
    r = client.get("/fx/rates?base=USD")
    assert r.status_code == 502
