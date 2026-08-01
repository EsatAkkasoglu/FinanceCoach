"""Risk analytics tests — pure, no network.

Every assertion is against a value that can be derived by hand or by identity
(beta of a series against itself is exactly 1, VaR of a known sample is a known
quantile), so a regression here is unambiguous.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from app.quant.risk import (
    beta_alpha,
    capture_ratios,
    cornish_fisher_var,
    ewma_vol,
    factor_exposures,
    historical_cvar,
    historical_var,
    rolling_drawdown,
)


def _series(n: int = 400, seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.normal(0.0005, 0.011, n)


# ── tail risk ────────────────────────────────────────────────────────────────


def test_historical_var_is_the_empirical_quantile_as_a_positive_loss():
    r = np.array([-0.05, -0.03, -0.01, 0.0, 0.01, 0.02, 0.03, 0.04, 0.05, 0.06])
    var = historical_var(r, alpha=0.90)
    assert var == pytest.approx(-float(np.percentile(r, 10.0)))
    assert var > 0  # reported as a loss magnitude, not a negative return


def test_cvar_is_at_least_as_severe_as_var():
    r = _series()
    var = historical_var(r, 0.95)
    cvar = historical_cvar(r, 0.95)
    assert var is not None and cvar is not None
    assert cvar >= var  # expected shortfall can never be milder than the quantile


def test_var_grows_with_confidence():
    r = _series()
    assert historical_var(r, 0.99) > historical_var(r, 0.90)


def test_cornish_fisher_penalises_negative_skew():
    """A left-skewed series must get a bigger VaR than its symmetric twin."""
    rng = np.random.default_rng(3)
    symmetric = rng.normal(0.0, 0.01, 4000)
    skewed = symmetric.copy()
    skewed[::50] -= 0.06  # occasional crashes, same-ish body
    cf_sym = cornish_fisher_var(symmetric, 0.99)
    cf_skew = cornish_fisher_var(skewed, 0.99)
    assert cf_sym is not None and cf_skew is not None
    assert cf_skew > cf_sym


def test_tail_measures_reject_degenerate_input():
    assert historical_var([0.01], 0.95) is None
    assert historical_cvar([], 0.95) is None
    assert cornish_fisher_var(np.zeros(50), 0.95) is None   # no variance
    assert historical_var(_series(), alpha=1.5) is None     # nonsense confidence


def test_ewma_vol_reacts_faster_than_the_flat_sample_stdev():
    calm = np.full(300, 0.001)
    shocked = np.concatenate([calm, np.full(30, 0.05)])
    flat = float(np.std(shocked, ddof=1)) * math.sqrt(252.0)
    assert ewma_vol(shocked, 0.94, 252.0) > flat


def test_rolling_drawdown_is_never_positive_and_ends_at_zero_on_a_new_high():
    dd = rolling_drawdown([0.1, -0.05, 0.2])
    assert (dd <= 1e-12).all()
    assert dd[-1] == pytest.approx(0.0)


# ── benchmark-relative ───────────────────────────────────────────────────────


def test_beta_against_itself_is_exactly_one_with_no_alpha():
    r = _series()
    out = beta_alpha(r, r)
    assert out is not None
    assert out["beta"] == pytest.approx(1.0, abs=1e-6)
    assert out["alpha_annualized_pct"] == pytest.approx(0.0, abs=1e-6)
    assert out["r2"] == pytest.approx(1.0, abs=1e-6)
    assert out["tracking_error_pct"] == pytest.approx(0.0, abs=1e-6)


def test_double_the_benchmark_gives_beta_two():
    b = _series()
    out = beta_alpha(2.0 * b, b)
    assert out is not None
    assert out["beta"] == pytest.approx(2.0, abs=1e-6)
    assert out["correlation"] == pytest.approx(1.0, abs=1e-6)


def test_beta_alpha_recovers_a_planted_alpha():
    b = _series()
    daily_alpha = 0.0004
    out = beta_alpha(0.5 * b + daily_alpha, b, ppy=252.0)
    assert out is not None
    assert out["beta"] == pytest.approx(0.5, abs=1e-6)
    assert out["alpha_annualized_pct"] == pytest.approx(daily_alpha * 252.0 * 100.0, abs=1e-3)


def test_beta_alpha_needs_enough_observations():
    assert beta_alpha([0.01, 0.02], [0.01, 0.02]) is None


def test_capture_ratios_are_one_hundred_percent_against_self():
    b = _series()
    caps = capture_ratios(b, b)
    assert caps["up_capture_pct"] == pytest.approx(100.0, abs=1e-6)
    assert caps["down_capture_pct"] == pytest.approx(100.0, abs=1e-6)


def test_half_beta_captures_half_of_both_directions():
    b = _series()
    caps = capture_ratios(0.5 * b, b)
    assert caps["up_capture_pct"] == pytest.approx(50.0, abs=1e-6)
    assert caps["down_capture_pct"] == pytest.approx(50.0, abs=1e-6)


# ── factors ──────────────────────────────────────────────────────────────────


def test_factor_exposures_recover_planted_loadings():
    rng = np.random.default_rng(11)
    mkt = rng.normal(0.0004, 0.01, 800)
    size = rng.normal(0.0, 0.006, 800)
    y = 1.2 * mkt - 0.4 * size + rng.normal(0.0, 1e-9, 800)

    out = factor_exposures(y, {"market": mkt, "size": size})
    assert out is not None
    loadings = {f["factor"]: f["beta"] for f in out["factors"]}
    assert loadings["market"] == pytest.approx(1.2, abs=1e-3)
    assert loadings["size"] == pytest.approx(-0.4, abs=1e-3)
    assert out["r2"] == pytest.approx(1.0, abs=1e-4)
    assert all(f["significant"] for f in out["factors"])


def test_unrelated_factor_is_not_flagged_significant():
    """A regressor the target doesn't load on must fail the 5% test.

    The target needs genuine idiosyncratic variance for this to be meaningful —
    a noiseless fit determines every coefficient exactly and makes all t-stats
    explode, which says nothing about significance.
    """
    rng = np.random.default_rng(19)
    mkt = rng.normal(0.0, 0.01, 900)
    unrelated = rng.normal(0.0, 0.01, 900)
    y = 1.0 * mkt + rng.normal(0.0, 0.01, 900)  # real residual risk

    out = factor_exposures(y, {"market": mkt, "unrelated": unrelated})
    assert out is not None
    by_name = {f["factor"]: f for f in out["factors"]}
    assert by_name["market"]["significant"] is True
    assert by_name["unrelated"]["significant"] is False
    assert by_name["unrelated"]["p_value"] > 0.05


def test_factor_exposures_refuse_underdetermined_samples():
    assert factor_exposures([0.01, 0.02, 0.03], {"a": [0.01, 0.02, 0.03]}) is None
    assert factor_exposures(_series(), {}) is None
