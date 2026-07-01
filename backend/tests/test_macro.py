"""Unit tests for the macro/regime feeds — pure mappings + graceful no-key paths.
No network: fetchers are monkeypatched or exercised in their no-key branch."""
from __future__ import annotations

import pytest

from app.services import finnhub, macro

# ── pure mappings ────────────────────────────────────────────────────────────


def test_fear_greed_score_mapping():
    assert macro.fear_greed_score(None) == 0.0
    assert macro.fear_greed_score(50) == 0.0
    assert macro.fear_greed_score(100) == 1.0
    assert macro.fear_greed_score(0) == -1.0
    assert macro.fear_greed_score(75) == pytest.approx(0.5)


def test_yield_curve_score_mapping():
    assert macro.yield_curve_score(None) == 0.0
    assert macro.yield_curve_score(1.0) == 1.0
    assert macro.yield_curve_score(-1.0) == -1.0   # inversion = risk-off
    assert macro.yield_curve_score(0.5) == pytest.approx(0.5)
    assert macro.yield_curve_score(5.0) == 1.0     # clamped


def test_macro_regime_blends_components(monkeypatch):
    monkeypatch.setattr(macro, "crypto_fear_greed", lambda: {"value": 80, "score": 0.6})
    monkeypatch.setattr(macro, "yield_curve_10y2y", lambda: 0.5)
    reg = macro.macro_regime()
    # 0.5 * yield_curve_score(0.5)=0.25  +  0.5 * 0.6=0.3  → 0.55
    assert reg["score"] == pytest.approx(0.55, abs=1e-3)
    assert reg["fear_greed"] == 80


def test_macro_regime_degrades_to_neutral(monkeypatch):
    monkeypatch.setattr(macro, "crypto_fear_greed", lambda: None)
    monkeypatch.setattr(macro, "yield_curve_10y2y", lambda: None)
    reg = macro.macro_regime()
    assert reg["score"] == 0.0
    assert reg["fear_greed"] is None and reg["yield_curve_10y2y"] is None


# ── graceful no-key ──────────────────────────────────────────────────────────


def test_fred_returns_none_without_key(monkeypatch):
    monkeypatch.setattr(macro.settings, "fred_api_key", "")
    assert macro._fred_latest("T10Y2Y") is None
    assert macro.yield_curve_10y2y() is None


def test_finnhub_unavailable_without_key(monkeypatch):
    monkeypatch.setattr(finnhub.settings, "finnhub_api_key", "")
    assert finnhub.available() is False
    assert finnhub.quote("AAPL") is None
    assert finnhub.company_news("AAPL") is None
