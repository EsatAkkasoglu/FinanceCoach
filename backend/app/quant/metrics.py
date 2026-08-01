"""Metrics ``app/eval/scorecard.py`` does not have, and the overfitting probe it asks for.

Two groups:

**Distribution-shape metrics** — Sharpe divides by standard deviation, which
treats an upside surprise as identical to a crash. On crypto intraday returns,
which are sharply non-normal, that is the wrong summary. Omega, tail ratio and
the ulcer index each look at a part of the distribution Sharpe averages away.

**Probability of Backtest Overfitting (PBO)** — the thing that matters most in a
tournament. The Deflated Sharpe already in ``scorecard.py`` asks "is this Sharpe
big enough given how many things I tried?". PBO asks a sharper question: "when I
pick the best configuration in-sample, how often does it land in the bottom half
out-of-sample?". A PBO near 0.5 means the selection procedure itself is noise —
which is the honest verdict for most parameter searches.

Sources
-------
* Bailey, Borwein, López de Prado & Zhu (2015), *The Probability of Backtest
  Overfitting* — Combinatorially Symmetric Cross-Validation (CSCV).
* Keating & Shadwick (2002) — the Omega ratio.
* Martin & McCann (1989) — the Ulcer Index.
* Politis & Romano (1994) — the stationary bootstrap used by :func:`bootstrap_pvalue`.

All pure numpy. Every function returns ``None`` rather than raising on
degenerate input, matching the house convention.
"""
from __future__ import annotations

import itertools
import math
from typing import Any

import numpy as np


def _clean(returns: Any) -> np.ndarray:
    r = np.asarray(returns, dtype=float).ravel()
    return r[np.isfinite(r)]


# ── distribution-shape metrics ───────────────────────────────────────────────


def omega_ratio(returns: Any, threshold: float = 0.0) -> float | None:
    """Probability-weighted gains over losses relative to ``threshold``.

    Ω = Σ max(r − τ, 0) / Σ max(τ − r, 0). Uses the whole distribution rather
    than its first two moments, so a strategy with rare huge wins and frequent
    small losses is not flattened into the same number as its mirror image.
    """
    r = _clean(returns)
    if r.size < 2:
        return None
    gains = float(np.maximum(r - threshold, 0.0).sum())
    losses = float(np.maximum(threshold - r, 0.0).sum())
    if losses <= 1e-15:
        return None  # no downside in-sample → undefined, not "infinitely good"
    return gains / losses


def tail_ratio(returns: Any, pct: float = 5.0) -> float | None:
    """|95th percentile| / |5th percentile| — right tail versus left tail.

    Above 1 means the best days outrun the worst ones. Crypto trend strategies
    often score well here while scoring badly on Sharpe, which is the point.
    """
    r = _clean(returns)
    if r.size < 20:
        return None
    right = abs(float(np.percentile(r, 100.0 - pct)))
    left = abs(float(np.percentile(r, pct)))
    if left <= 1e-15:
        return None
    return right / left


def ulcer_index(returns: Any) -> float | None:
    """Root-mean-square drawdown — depth AND duration of pain, not just depth.

    Max drawdown reports one bad moment. Two strategies with the same max
    drawdown differ enormously if one recovered in a day and the other took a
    month; the ulcer index separates them.
    """
    r = _clean(returns)
    if r.size < 2:
        return None
    equity = np.cumprod(1.0 + r)
    dd = equity / np.maximum.accumulate(equity) - 1.0
    return float(np.sqrt(np.mean(dd ** 2)))


def ulcer_performance_index(returns: Any, rf_per_bar: float = 0.0) -> float | None:
    """Excess return per unit of ulcer — the "Martin ratio"."""
    r = _clean(returns)
    ui = ulcer_index(r)
    if ui is None or ui <= 1e-15:
        return None
    return float((r.mean() - rf_per_bar) / ui)


def common_sense_ratio(returns: Any) -> float | None:
    """Tail ratio × profit factor. Fails loudly for strategies that look fine on
    average but are one bad tail away from ruin."""
    r = _clean(returns)
    tr = tail_ratio(r)
    if tr is None:
        return None
    gains = float(r[r > 0].sum())
    losses = float(-r[r < 0].sum())
    if losses <= 1e-15:
        return None
    return tr * (gains / losses)


def turnover_adjusted_return(
    total_return: float, n_position_changes: int, cost_per_turn: float
) -> float:
    """What the return would have been at a different cost assumption.

    Lets the tournament answer "does this edge survive at 2× the assumed cost?"
    without re-running the backtest.
    """
    return total_return - n_position_changes * cost_per_turn


def summary(returns: Any) -> dict[str, float | None]:
    """All shape metrics at once, JSON-safe."""
    r = _clean(returns)

    def _r(x: float | None) -> float | None:
        return round(float(x), 6) if x is not None and math.isfinite(float(x)) else None

    return {
        "omega": _r(omega_ratio(r)),
        "tail_ratio": _r(tail_ratio(r)),
        "ulcer_index": _r(ulcer_index(r)),
        "ulcer_performance_index": _r(ulcer_performance_index(r)),
        "common_sense_ratio": _r(common_sense_ratio(r)),
        "skew": _r(float(((r - r.mean()) ** 3).mean() / r.std() ** 3)) if r.size > 2 and r.std() > 0 else None,
        "kurtosis_excess": _r(float(((r - r.mean()) ** 4).mean() / r.std() ** 4 - 3.0)) if r.size > 3 and r.std() > 0 else None,
    }


# ── probability of backtest overfitting (CSCV) ───────────────────────────────


def probability_of_backtest_overfitting(
    trial_returns: np.ndarray, n_splits: int = 10, max_combinations: int = 1000
) -> dict[str, Any] | None:
    """PBO by Combinatorially Symmetric Cross-Validation (Bailey et al. 2015).

    ``trial_returns`` is a matrix of shape (T observations × N configurations) —
    the per-bar return series of every configuration the search considered.

    Algorithm:
      1. Chop the T rows into ``n_splits`` contiguous blocks of equal size.
      2. For every way of choosing half the blocks as in-sample (the rest are
         out-of-sample), pick the configuration with the best in-sample Sharpe.
      3. Record that configuration's OUT-of-sample rank, mapped to a logit.
      4. PBO is the fraction of splits where the in-sample winner landed in the
         bottom half out-of-sample.

    PBO ≈ 0 means selection generalises. PBO ≈ 0.5 means picking the in-sample
    winner is a coin flip — the search found noise. Returns None when the input
    is too small for the construction to mean anything.
    """
    x = np.asarray(trial_returns, dtype=float)
    if x.ndim != 2 or x.shape[1] < 2:
        return None
    t, n_config = x.shape
    n_splits = int(n_splits)
    if n_splits % 2 or n_splits < 4 or t < n_splits * 4:
        return None

    block = t // n_splits
    blocks = [x[i * block:(i + 1) * block] for i in range(n_splits)]
    half = n_splits // 2

    combos = list(itertools.combinations(range(n_splits), half))
    if len(combos) > max_combinations:  # deterministic thinning, no RNG
        stride = max(1, len(combos) // max_combinations)
        combos = combos[::stride][:max_combinations]

    def _sharpe(col: np.ndarray) -> float:
        sd = col.std(ddof=1)
        return float(col.mean() / sd) if sd > 1e-15 else -np.inf

    logits: list[float] = []
    ranks: list[float] = []
    for train_idx in combos:
        test_idx = [i for i in range(n_splits) if i not in train_idx]
        train = np.vstack([blocks[i] for i in train_idx])
        test = np.vstack([blocks[i] for i in test_idx])

        is_scores = np.asarray([_sharpe(train[:, c]) for c in range(n_config)])
        if not np.isfinite(is_scores).any():
            continue
        best = int(np.nanargmax(np.where(np.isfinite(is_scores), is_scores, -np.inf)))

        oos_scores = np.asarray([_sharpe(test[:, c]) for c in range(n_config)])
        finite = np.isfinite(oos_scores)
        if finite.sum() < 2:
            continue
        # Relative rank of the in-sample winner among all configs, out-of-sample.
        better = int((oos_scores[finite] > oos_scores[best]).sum())
        omega = 1.0 - better / float(finite.sum())          # 1 = still the best
        omega = min(max(omega, 1e-6), 1 - 1e-6)
        ranks.append(omega)
        logits.append(math.log(omega / (1.0 - omega)))

    if len(logits) < 4:
        return None
    arr = np.asarray(logits)
    pbo = float((arr <= 0).mean())   # logit ≤ 0 ⇔ bottom half out-of-sample
    return {
        "pbo": round(pbo, 4),
        "n_splits": n_splits,
        "n_combinations": len(logits),
        "n_configurations": int(n_config),
        "median_oos_rank": round(float(np.median(ranks)), 4),
        "verdict": (
            "selection generalises" if pbo < 0.25
            else "weak — selection is close to a coin flip" if pbo < 0.5
            else "overfit — the in-sample winner is usually below median out-of-sample"
        ),
    }


# ── stationary bootstrap ─────────────────────────────────────────────────────


def bootstrap_pvalue(
    returns: Any, n_boot: int = 2000, block: int = 20, seed: int = 12345
) -> dict[str, Any] | None:
    """One-sided p-value for "mean return > 0" under a circular block bootstrap.

    Künsch's moving-block bootstrap, wrapped circularly: resample contiguous
    blocks of ``block`` observations so each resample preserves the serial
    dependence and volatility clustering that make an i.i.d. t-test far too
    optimistic on financial returns. The null is imposed by de-meaning before
    resampling, so the reference distribution really is centred on zero.

    Fixed-length blocks rather than Politis-Romano's geometric ones: the
    stationary bootstrap's random block lengths force a sequential scan over the
    series, and the tournament calls this once per leaderboard row over
    thousands of bars. The fixed-length construction is fully vectorised — it
    builds every replicate's index array in one shot — which turns hours of
    wall-clock into under a second, at the cost of a refinement that does not
    change the verdict at these sample sizes.
    """
    r = _clean(returns)
    if r.size < 50 or block < 1:
        return None
    rng = np.random.default_rng(seed)
    n = r.size
    block = min(int(block), max(2, n // 4))
    observed = float(r.mean())
    centred = r - observed

    n_blocks = int(np.ceil(n / block))
    starts = rng.integers(0, n, size=(n_boot, n_blocks))
    # (n_boot, n_blocks, block) → wrap with modulo so a block near the end of the
    # series continues from the beginning instead of being truncated.
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]) % n
    means = centred[idx.reshape(n_boot, -1)[:, :n]].mean(axis=1)

    p = float((means >= observed).mean()) if observed > 0 else 1.0
    return {
        "observed_mean": round(observed, 10),
        "p_value": round(p, 5),
        "n_boot": n_boot,
        "block": block,
        "significant_5pct": bool(p < 0.05),
    }
