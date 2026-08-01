"""Tests for the extra metrics and the overfitting probes — pure, no network.

The PBO tests are the ones that matter: a probe that cannot tell a genuine
signal from pure noise would silently bless every overfit tournament result.
Both directions are asserted.
"""
from __future__ import annotations

import numpy as np
import pytest

from app.quant.metrics import (
    bootstrap_pvalue,
    common_sense_ratio,
    omega_ratio,
    probability_of_backtest_overfitting,
    summary,
    tail_ratio,
    turnover_adjusted_return,
    ulcer_index,
    ulcer_performance_index,
)


# ── shape metrics ────────────────────────────────────────────────────────────


def test_omega_is_one_when_gains_and_losses_balance():
    assert omega_ratio([0.01, -0.01, 0.02, -0.02]) == pytest.approx(1.0)


def test_omega_rises_above_one_for_a_positively_skewed_series():
    assert omega_ratio([0.05, -0.01, -0.01, -0.01, -0.01]) > 1.0


def test_omega_threshold_shifts_the_verdict():
    r = [0.02, 0.01, -0.01]
    assert omega_ratio(r, threshold=0.0) > omega_ratio(r, threshold=0.015)


def test_omega_is_none_without_downside():
    assert omega_ratio([0.01, 0.02, 0.03]) is None


def test_tail_ratio_above_one_when_the_right_tail_is_fatter():
    rng = np.random.default_rng(1)
    base = rng.normal(0, 0.01, 500)
    fat_right = np.concatenate([base, [0.20] * 30])
    assert tail_ratio(fat_right) > 1.0


def test_tail_ratio_needs_a_usable_sample():
    assert tail_ratio([0.01, -0.01]) is None


def test_ulcer_index_is_zero_for_a_monotonic_climb():
    assert ulcer_index([0.01] * 50) == pytest.approx(0.0, abs=1e-12)


def test_ulcer_index_separates_a_quick_recovery_from_a_long_one():
    """Same trough, different time underwater — max drawdown cannot tell these
    apart, which is exactly why the ulcer index exists.

    Both paths must first establish a peak; a drop on bar 0 has nothing to draw
    down FROM, so the running peak simply starts lower and no drawdown registers.
    """
    rise = [0.10] * 5
    quick = rise + [-0.20, 0.25] + [0.0] * 20
    slow = rise + [-0.20] + [0.0] * 20 + [0.25]
    assert ulcer_index(quick) > 0.0
    assert ulcer_index(slow) > ulcer_index(quick)


def test_ulcer_performance_index_is_undefined_without_any_drawdown():
    """A monotonic climb has zero ulcer, so return-per-ulcer is a division by
    zero. None is the honest answer, not an enormous number."""
    assert ulcer_performance_index([0.002] * 100) is None


def test_ulcer_performance_index_rewards_the_smoother_of_two_bumpy_paths():
    rng = np.random.default_rng(31)
    smooth = 0.001 + rng.normal(0.0, 0.002, 300)
    jagged = 0.001 + rng.normal(0.0, 0.020, 300)
    assert ulcer_performance_index(smooth) > ulcer_performance_index(jagged)


def test_common_sense_ratio_and_summary_are_json_safe():
    rng = np.random.default_rng(4)
    r = rng.normal(0.0004, 0.01, 400)
    assert common_sense_ratio(r) is not None
    for key, value in summary(r).items():
        assert value is None or isinstance(value, float), key


def test_turnover_adjusted_return_charges_every_change():
    assert turnover_adjusted_return(0.10, 20, 0.0015) == pytest.approx(0.10 - 0.03)


# ── probability of backtest overfitting ──────────────────────────────────────


def _noise_matrix(t: int = 2000, n: int = 12, seed: int = 3) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.normal(0.0, 0.01, (t, n))


def test_pbo_flags_pure_noise_as_overfit():
    """With no real signal, the in-sample winner should land below median
    out-of-sample about half the time — PBO near 0.5."""
    out = probability_of_backtest_overfitting(_noise_matrix())
    assert out is not None
    assert out["pbo"] > 0.25
    assert out["n_configurations"] == 12


def test_pbo_clears_a_genuinely_dominant_configuration():
    """One column with a real edge should keep winning out-of-sample → low PBO."""
    x = _noise_matrix(seed=9)
    x[:, 5] += 0.004          # a persistent, genuine drift in one configuration
    out = probability_of_backtest_overfitting(x)
    assert out is not None
    assert out["pbo"] < 0.10
    assert "generalises" in out["verdict"]


def test_pbo_returns_a_verdict_string_and_bounded_probability():
    out = probability_of_backtest_overfitting(_noise_matrix())
    assert 0.0 <= out["pbo"] <= 1.0
    assert 0.0 <= out["median_oos_rank"] <= 1.0
    assert isinstance(out["verdict"], str)


@pytest.mark.parametrize(
    ("matrix", "splits"),
    [
        (np.zeros((100, 1)), 10),        # a single configuration cannot be ranked
        (np.zeros((20, 8)), 10),         # too few rows for the block construction
        (np.zeros((2000, 8)), 7),        # odd split count has no symmetric halves
    ],
)
def test_pbo_refuses_degenerate_inputs(matrix, splits):
    assert probability_of_backtest_overfitting(matrix, n_splits=splits) is None


# ── stationary bootstrap ─────────────────────────────────────────────────────


def test_bootstrap_rejects_the_null_for_a_strong_planted_drift():
    rng = np.random.default_rng(11)
    r = rng.normal(0.004, 0.004, 600)     # unmistakable positive mean
    out = bootstrap_pvalue(r, n_boot=800)
    assert out is not None
    assert out["significant_5pct"] is True
    assert out["p_value"] < 0.05


def test_bootstrap_does_not_reject_for_pure_noise():
    rng = np.random.default_rng(13)
    out = bootstrap_pvalue(rng.normal(0.0, 0.01, 600), n_boot=800)
    assert out is not None
    assert out["p_value"] > 0.05


def test_bootstrap_returns_certainty_for_a_negative_mean():
    rng = np.random.default_rng(17)
    out = bootstrap_pvalue(rng.normal(-0.002, 0.01, 400), n_boot=500)
    assert out["p_value"] == 1.0        # "mean > 0" is not remotely supported


def test_bootstrap_is_deterministic_for_a_fixed_seed():
    rng = np.random.default_rng(21)
    r = rng.normal(0.001, 0.01, 400)
    assert bootstrap_pvalue(r, n_boot=300)["p_value"] == (
        bootstrap_pvalue(r, n_boot=300)["p_value"]
    )


def test_bootstrap_needs_a_minimum_sample():
    assert bootstrap_pvalue(np.zeros(10)) is None
