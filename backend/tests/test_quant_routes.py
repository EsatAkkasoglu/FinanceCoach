"""Quant Lab route tests — auth gating, error degradation, payload shape.

No network: the price loader is patched on the ROUTER module, because
``app/routers/quant.py`` does ``from app.tools.quant_tools import _load_path``,
which binds the function object at import time — patching the source module
would not affect the already-bound reference.
"""
from __future__ import annotations

import numpy as np
import pytest


def _synthetic(n: int = 900):
    t = np.arange(n, dtype=float)
    closes = 100.0 * np.exp(0.0004 * t + 0.05 * np.sin(t / 13.0))
    dates = [f"2021-{(i % 12) + 1:02d}-{(i % 28) + 1:02d}" for i in range(n)]
    return dates, closes, closes * 1.01, closes * 0.99


@pytest.fixture
def offline(monkeypatch):
    import app.routers.quant as quant_routes

    monkeypatch.setattr(quant_routes, "_load_path", lambda ticker, days: _synthetic())


# ── auth ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("method", "path"),
    [("get", "/quant/strategies"), ("get", "/quant/risk"),
     ("post", "/quant/backtest"), ("post", "/quant/optimize")],
)
def test_every_quant_route_requires_auth(client, method, path):
    bare = client.__class__(client.app)  # same app, no bearer header
    r = bare.post(path, json={}) if method == "post" else bare.get(path)
    assert r.status_code == 401


# ── catalogue ────────────────────────────────────────────────────────────────


def test_strategy_catalogue_reports_each_search_width(client):
    body = client.get("/quant/strategies").json()
    assert body["ok"] is True
    keys = {s["key"] for s in body["strategies"]}
    assert {"sma_cross", "tsmom", "buy_hold"} <= keys
    for s in body["strategies"]:
        # The UI shows this so a user can see how wide a parameter search is
        # before running it — it must never be zero.
        assert s["n_combinations"] >= 1


# ── backtest ─────────────────────────────────────────────────────────────────


def test_backtest_returns_full_resolution_curves(client, offline):
    body = client.post("/quant/backtest", json={
        "ticker": "TEST", "strategy": "sma_cross", "period_days": 1825,
    }).json()
    assert body["ok"] is True
    assert len(body["equity"]) == len(body["benchmark"]) == len(body["drawdown"])
    assert len(body["dates"]) == len(body["equity"])
    # Far more detail than the 80-point chat envelope carries.
    assert len(body["equity"]) > 80
    assert body["metrics"]["n_bars"] > 0
    assert body["walk_forward"] is not None


def test_backtest_can_skip_walk_forward(client, offline):
    body = client.post("/quant/backtest", json={
        "ticker": "TEST", "strategy": "buy_hold", "walk_forward": False,
    }).json()
    assert body["ok"] is True
    assert body["walk_forward"] is None


def test_backtest_rejects_an_unknown_strategy(client, offline):
    body = client.post("/quant/backtest", json={
        "ticker": "TEST", "strategy": "astrology",
    }).json()
    assert body["ok"] is False
    assert "astrology" in body["error"]


def test_backtest_validates_its_request_bounds(client):
    r = client.post("/quant/backtest", json={"ticker": "TEST", "period_days": 99999})
    assert r.status_code == 422   # pydantic bound, not a silent clamp


def test_backtest_degrades_to_200_when_history_is_missing(client, monkeypatch):
    import app.routers.quant as quant_routes

    monkeypatch.setattr(quant_routes, "_load_path", lambda ticker, days: None)
    r = client.post("/quant/backtest", json={"ticker": "NOPE"})
    assert r.status_code == 200          # never a raw 500 — that would bypass CORS
    assert r.json()["ok"] is False


def test_backtest_response_contains_no_nan(client, offline):
    """Starlette serializes with allow_nan=False; a NaN would 500 at render time."""
    raw = client.post("/quant/backtest", json={"ticker": "TEST", "strategy": "macd"}).text
    assert "NaN" not in raw
    assert "Infinity" not in raw


# ── portfolio-backed routes with no holdings ─────────────────────────────────


def test_risk_route_reports_missing_holdings_cleanly(client):
    body = client.get("/quant/risk").json()
    assert body["ok"] is False
    assert "holdings" in body["error"].lower()


def test_optimize_route_reports_missing_holdings_cleanly(client):
    body = client.post("/quant/optimize", json={"objective": "max_sharpe"}).json()
    assert body["ok"] is False
    assert body["error"]


def test_risk_route_validates_confidence(client):
    assert client.get("/quant/risk?confidence=1.5").status_code == 422
