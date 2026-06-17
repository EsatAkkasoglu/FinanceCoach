"""Regression tests for the risk_profiler score-update parser + localized summary.

The headline case is the data-corruption bug: a sentence like "risk profilimi 3
kademe değiştir" must NOT be parsed as "set risk_score = 3".
"""
from __future__ import annotations

import pytest

from app.agents import risk_profiler as rp


def _parsed(text: str) -> int | None:
    m = rp._UPDATE_RE.search(text)
    return int(m.group(1)) if m else None


@pytest.mark.parametrize(
    "text,expected",
    [
        ("set my risk score to 80", 80),
        ("risk skorumu 80 yap", 80),
        ("update risk score 65", 65),
        ("riskini 100 yap", 100),
        ("risk skorumu 3 yap", 3),          # legit explicit set to 3
    ],
)
def test_update_re_matches_explicit_score(text, expected):
    assert _parsed(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "risk profilimi 3 kademe değiştir",  # the corruption bug — '3 kademe' is a step
        "riskimi 2 basamak düşür",
        "ne yapmalıyım",
        "2025 hedefim için riskimi düşür",   # number not tied to a score set
        "bu ay 3 kez fazla harcadım",        # no risk-score intent
    ],
)
def test_update_re_ignores_non_score_phrases(text):
    assert _parsed(text) is None


def test_summary_text_localized_tr(monkeypatch):
    monkeypatch.setattr(rp, "get_ui_language", lambda: "tr")
    out = rp._summary_text(72, "balanced", 40, 70)
    assert "Risk skorun" in out and "dengeli" in out
    assert "score" not in out.lower()


def test_summary_text_localized_en(monkeypatch):
    monkeypatch.setattr(rp, "get_ui_language", lambda: "en")
    out = rp._summary_text(72, "balanced", 40, 70)
    assert "Risk score" in out and "balanced" in out
