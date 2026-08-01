"""Portfolio-optimization tests — pure, no network.

Anchored on cases with a known closed form: two uncorrelated assets have an
analytic minimum-variance solution, and a diagonal covariance makes risk parity
exactly inverse-volatility weighting. If those drift, the solver is wrong.
"""
from __future__ import annotations

import numpy as np
import pytest

from app.quant.optimize import (
    efficient_frontier,
    ledoit_wolf_shrink,
    max_sharpe,
    min_variance,
    moments,
    portfolio_stats,
    risk_contributions,
    risk_parity,
)


def _diag(vols: list[float]) -> np.ndarray:
    return np.diag(np.asarray(vols, dtype=float) ** 2)


# ── minimum variance ─────────────────────────────────────────────────────────


def test_two_uncorrelated_assets_match_the_closed_form():
    """w1 = σ2² / (σ1² + σ2²) for independent assets."""
    s1, s2 = 0.10, 0.20
    cov = _diag([s1, s2])
    w = min_variance(cov, long_only=True)
    expected = s2 ** 2 / (s1 ** 2 + s2 ** 2)
    assert w[0] == pytest.approx(expected, abs=1e-5)
    assert w.sum() == pytest.approx(1.0, abs=1e-9)


def test_min_variance_beats_equal_weight_on_variance():
    cov = np.array([[0.04, 0.006, 0.002], [0.006, 0.09, 0.003], [0.002, 0.003, 0.16]])
    w = min_variance(cov, long_only=True)
    eq = np.full(3, 1.0 / 3.0)
    assert float(w @ cov @ w) <= float(eq @ cov @ eq) + 1e-12


def test_long_only_solution_respects_its_bounds():
    """The unconstrained optimum here shorts; the constrained one must not."""
    cov = np.array([[0.04, 0.038], [0.038, 0.05]])   # near-collinear → shorting is tempting
    w = min_variance(cov, long_only=True)
    assert (w >= -1e-6).all()
    assert w.sum() == pytest.approx(1.0, abs=1e-6)


def test_weight_cap_is_enforced():
    cov = _diag([0.05, 0.40, 0.45])   # asset 0 dominates without a cap
    w = min_variance(cov, long_only=True, w_max=0.5)
    assert w.max() <= 0.5 + 1e-6
    assert w.sum() == pytest.approx(1.0, abs=1e-6)


# ── max Sharpe ───────────────────────────────────────────────────────────────


def test_max_sharpe_beats_equal_weight_on_sharpe():
    mu = np.array([0.08, 0.12, 0.05])
    cov = np.array([[0.04, 0.01, 0.005], [0.01, 0.09, 0.004], [0.005, 0.004, 0.02]])
    w, converged = max_sharpe(mu, cov, rf=0.02, long_only=True)
    assert converged is True
    eq = np.full(3, 1.0 / 3.0)
    assert portfolio_stats(w, mu, cov, 0.02)["sharpe"] >= portfolio_stats(eq, mu, cov, 0.02)["sharpe"]


def test_max_sharpe_concentrates_on_the_dominant_asset():
    """One asset with strictly better return AND lower risk must dominate."""
    mu = np.array([0.15, 0.03])
    cov = _diag([0.10, 0.30])
    w, converged = max_sharpe(mu, cov, rf=0.0, long_only=True)
    assert converged is True
    assert w[0] > 0.9


def test_unconstrained_max_sharpe_uses_the_closed_form():
    mu = np.array([0.10, 0.06])
    cov = np.array([[0.04, 0.01], [0.01, 0.03]])
    w, converged = max_sharpe(mu, cov, rf=0.01, long_only=False)
    expected = np.linalg.inv(cov) @ (mu - 0.01)
    expected = expected / expected.sum()
    assert converged is True
    assert w == pytest.approx(expected, abs=1e-9)


def test_single_asset_is_fully_allocated():
    w, converged = max_sharpe(np.array([0.1]), np.array([[0.04]]))
    assert converged is True
    assert w.tolist() == [1.0]


# ── risk parity ──────────────────────────────────────────────────────────────


def test_risk_parity_on_a_diagonal_cov_is_inverse_volatility():
    vols = [0.10, 0.20, 0.40]
    w = risk_parity(_diag(vols))
    inv = np.asarray([1.0 / v for v in vols])
    assert w == pytest.approx(inv / inv.sum(), abs=1e-5)


def test_risk_parity_equalises_risk_contributions():
    cov = np.array([[0.04, 0.012, 0.002], [0.012, 0.09, 0.008], [0.002, 0.008, 0.16]])
    rc = risk_contributions(risk_parity(cov), cov)
    assert rc == pytest.approx(np.full(3, 1.0 / 3.0), abs=1e-4)
    assert rc.sum() == pytest.approx(1.0)


def test_risk_parity_is_long_only_by_construction():
    cov = np.array([[0.04, -0.03], [-0.03, 0.09]])
    w = risk_parity(cov)
    assert (w > 0).all()
    assert w.sum() == pytest.approx(1.0, abs=1e-9)


# ── shrinkage ────────────────────────────────────────────────────────────────


def test_shrinkage_intensity_is_a_valid_proportion():
    rng = np.random.default_rng(5)
    x = rng.normal(0.0, 0.01, (150, 8))
    cov, intensity = ledoit_wolf_shrink(x)
    assert 0.0 <= intensity <= 1.0
    assert cov.shape == (8, 8)
    assert np.allclose(cov, cov.T)


def test_shrinkage_conditions_a_short_wide_sample():
    """With fewer observations than assets the sample cov is singular; the
    shrunk one must not be."""
    rng = np.random.default_rng(6)
    x = rng.normal(0.0, 0.01, (12, 20))
    cov, intensity = ledoit_wolf_shrink(x)
    assert intensity > 0.0
    assert np.linalg.matrix_rank(cov) == 20


def test_moments_annualise_and_report_shrinkage():
    rng = np.random.default_rng(8)
    x = rng.normal(0.0005, 0.01, (500, 4))
    mu, cov, intensity = moments(x, ppy=252.0)
    assert mu.shape == (4,) and cov.shape == (4, 4)
    assert mu[0] == pytest.approx(float(x[:, 0].mean()) * 252.0, rel=1e-9)
    assert 0.0 <= intensity <= 1.0
    # Annualised vol of a ~1% daily series lands near 16%.
    assert 0.10 < float(np.sqrt(cov[0, 0])) < 0.25


# ── frontier ─────────────────────────────────────────────────────────────────


def test_frontier_is_monotone_in_risk_and_fully_invested():
    mu = np.array([0.05, 0.09, 0.13])
    cov = np.array([[0.02, 0.004, 0.001], [0.004, 0.06, 0.002], [0.001, 0.002, 0.12]])
    pts = efficient_frontier(mu, cov, n_points=12, long_only=True)
    assert len(pts) >= 5
    vols = [p["vol_pct"] for p in pts]
    assert vols == sorted(vols)
    for p in pts:
        assert sum(p["weights"]) == pytest.approx(1.0, abs=1e-5)
        assert min(p["weights"]) >= -1e-6


def test_frontier_needs_at_least_two_distinct_assets():
    assert efficient_frontier(np.array([0.1]), np.array([[0.04]])) == []
    flat_mu = np.array([0.07, 0.07])
    assert efficient_frontier(flat_mu, np.eye(2) * 0.04) == []


def test_portfolio_stats_are_json_safe():
    stats = portfolio_stats(np.array([0.5, 0.5]), np.array([0.1, 0.06]), np.eye(2) * 0.04)
    assert set(stats) == {"return_pct", "vol_pct", "sharpe"}
    assert all(isinstance(v, float) for v in stats.values())
