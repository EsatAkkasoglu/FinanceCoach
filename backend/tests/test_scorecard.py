"""Deterministic unit tests for the evaluation scorecard (pure, no DB/network)."""
from __future__ import annotations

import pytest

from app.eval import scorecard as sc

# ── realized return ──────────────────────────────────────────────────────────


def test_realized_return_long_short_and_unresolved():
    long = {"status": "hit", "direction": "long", "entry_price": 100.0, "resolved_price": 110.0}
    short = {"status": "hit", "direction": "short", "entry_price": 100.0, "resolved_price": 90.0}
    assert sc.realized_return(long) == pytest.approx(0.10)
    assert sc.realized_return(short) == pytest.approx(0.10)  # short profits when price falls
    assert sc.realized_return({"status": "active", "direction": "long",
                               "entry_price": 100, "resolved_price": None}) is None


# ── return-series metrics ────────────────────────────────────────────────────


def test_sharpe_none_for_zero_variance_and_short():
    assert sc.sharpe([0.1, 0.1, 0.1]) is None
    assert sc.sharpe([0.1]) is None
    assert sc.sharpe([0.1, -0.05, 0.2, 0.0]) is not None


def test_sortino_only_penalizes_downside():
    # No losing trades → Sortino undefined.
    assert sc.sortino([0.1, 0.2, 0.05]) is None
    s = sc.sortino([0.1, -0.1, 0.2, -0.05])
    assert s is not None


def test_max_drawdown_known_series():
    assert sc.max_drawdown([0.1, -0.2, 0.1]) == pytest.approx(-0.2, abs=1e-9)
    assert sc.max_drawdown([0.1, 0.1, 0.1]) == pytest.approx(0.0)


def test_profit_factor():
    assert sc.profit_factor([0.2, -0.1, 0.1]) == pytest.approx(0.3 / 0.1)
    assert sc.profit_factor([0.1, 0.2]) is None  # no losses → undefined


# ── calibration ──────────────────────────────────────────────────────────────


def test_brier_score_known():
    assert sc.brier_score([1.0, 1.0], [1, 0]) == pytest.approx(0.5)
    assert sc.brier_score([0.5, 0.5], [1, 0]) == pytest.approx(0.25)


def test_expected_calibration_error_known():
    # All confidences 0.8, 3/4 hit → |0.8 - 0.75| = 0.05.
    assert sc.expected_calibration_error([0.8, 0.8, 0.8, 0.8], [1, 1, 1, 0]) == pytest.approx(0.05)
    # Perfectly calibrated → 0.
    assert sc.expected_calibration_error([0.0, 1.0], [0, 1]) == pytest.approx(0.0)


# ── normal CDF / PPF ─────────────────────────────────────────────────────────


def test_norm_cdf_ppf_roundtrip():
    assert sc._norm_cdf(0.0) == pytest.approx(0.5)
    assert sc._norm_ppf(0.5) == pytest.approx(0.0, abs=1e-6)
    assert sc._norm_cdf(sc._norm_ppf(0.975)) == pytest.approx(0.975, abs=1e-4)


# ── PSR / DSR ────────────────────────────────────────────────────────────────


def test_psr_in_unit_interval_and_rises_with_sharpe():
    low = sc.probabilistic_sharpe_ratio(0.1, 50, 0.0, 3.0)
    high = sc.probabilistic_sharpe_ratio(0.5, 50, 0.0, 3.0)
    assert 0.0 <= low <= 1.0 and 0.0 <= high <= 1.0
    assert high > low


def test_dsr_equals_psr_for_single_trial_and_is_lower_for_many():
    sr, n, skew, kurt = 0.4, 60, 0.0, 3.0
    psr = sc.probabilistic_sharpe_ratio(sr, n, skew, kurt)
    dsr1 = sc.deflated_sharpe_ratio(sr, n, skew, kurt, n_trials=1)
    dsr_many = sc.deflated_sharpe_ratio(sr, n, skew, kurt, n_trials=50)
    assert dsr1 == pytest.approx(psr, abs=1e-9)   # one trial → benchmark 0
    assert dsr_many < dsr1                          # selection bias deflates it


# ── purged k-fold ────────────────────────────────────────────────────────────


def test_purged_kfold_returns_band():
    rets = [0.05, -0.02, 0.03, -0.01, 0.04, 0.02, -0.03, 0.01, 0.02, -0.01]
    out = sc.purged_kfold_sharpe(rets, k=5)
    assert out is not None and out["folds"] >= 2
    assert "mean" in out and "std" in out


# ── full scorecard assembly ──────────────────────────────────────────────────


def _row(status, direction, entry, resolved, conf, hours, klass):
    return {
        "status": status, "direction": direction, "entry_price": entry,
        "resolved_price": resolved, "confidence": conf, "horizon_hours": hours,
        "asset_class": klass,
    }


def test_build_scorecard_groups_into_cells():
    rows = [
        _row("hit", "long", 100, 110, 0.7, 4, "crypto"),
        _row("stopped", "long", 100, 95, 0.6, 4, "crypto"),
        _row("hit", "long", 50, 55, 0.8, 168, "stock"),
        _row("active", "long", 10, None, 0.5, 4, "crypto"),  # unresolved → ignored
    ]
    card = sc.build_scorecard(rows)
    assert card["n_total"] == 4
    assert card["n_resolved"] == 3
    assert card["n_cells"] == 2  # (intraday, crypto) and (position, stock)
    cells = {(c["horizon"], c["asset_class"]) for c in card["by_cell"]}
    assert ("intraday", "crypto") in cells and ("position", "stock") in cells
    assert card["overall"]["hit_rate"] == pytest.approx(2 / 3, abs=1e-3)


def test_build_scorecard_handles_empty():
    card = sc.build_scorecard([])
    assert card["n_resolved"] == 0 and card["n_cells"] == 0
    assert card["overall"]["sharpe"] is None


def test_dsr_uses_cell_count_as_trials():
    # Two cells → n_trials = 2 → the per-cell DSR benchmark is inflated vs a
    # single-trial PSR (so DSR ≤ PSR where both are defined).
    rows = [_row("hit", "long", 100, 100 + i, 0.6, 4, "crypto") for i in range(1, 8)]
    rows += [_row("hit", "long", 100, 100 + i, 0.6, 168, "stock") for i in range(1, 8)]
    card = sc.build_scorecard(rows)
    assert card["n_cells"] == 2
    for cell in card["by_cell"]:
        if cell["psr"] is not None and cell["dsr"] is not None:
            assert cell["dsr"] <= cell["psr"] + 1e-9
