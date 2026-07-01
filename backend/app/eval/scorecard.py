"""Research-grounded trade-evaluation scorecard — the "jury".

Replays RESOLVED ``TradeTarget`` rows (hit / stopped / expired, with a
``resolved_price``) into a per (horizon × asset-class) scorecard. Win-rate is
NEVER the headline — multi-timeframe filtering inflates win-rate without proving
expectancy. The discriminating metrics are risk-adjusted return and, above all,
**confidence calibration** (LLMs are systematically over-confident — arXiv:2507.04562).

Metrics, with sources:
  • Sharpe / Sortino / Calmar, max drawdown — standard; Sortino leads for the
    skewed, jumpy return distributions trading produces.
  • Probabilistic Sharpe Ratio (PSR) and Deflated Sharpe Ratio (DSR) —
    Bailey & López de Prado (SSRN 2460551 / 2460551): PSR is the probability the
    true Sharpe exceeds a benchmark given skew/kurtosis and sample size; DSR
    deflates the benchmark for the number of trials, correcting selection bias.
  • Brier score + Expected Calibration Error (ECE) — calibration of the stored
    ``confidence`` (0..1) against the realized hit/no-hit outcome.
  • Purged k-fold robustness — the per-trade return Sharpe re-estimated on purged
    folds of the ordered ledger (a CPCV-flavoured stability check; a *full* CPCV
    needs a price-path backtest, which a discrete trade ledger doesn't provide —
    we are honest about that rather than overclaiming).

Pure / numpy only: no DB, no network — :func:`build_scorecard` takes plain rows.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

from app.services import horizon as hz

# A resolved row contributes one realized trade. Confidence is the model's stated
# probability the trade works; the outcome is 1 if it HIT its target, else 0.
_RESOLVED = {"hit", "stopped", "expired"}
_HOURS_PER_YEAR = 365.25 * 24.0


# ── normal CDF (no scipy dependency) ─────────────────────────────────────────


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


# ── per-trade realized return ────────────────────────────────────────────────


def realized_return(row: dict[str, Any]) -> float | None:
    """Signed realized return of a resolved trade as a fraction (long-relative).

    ``(resolved/entry - 1)`` for a long, negated for a short. None if the row is
    unresolved or missing prices.
    """
    if row.get("status") not in _RESOLVED:
        return None
    entry = row.get("entry_price")
    exit_px = row.get("resolved_price")
    if not entry or exit_px is None:
        return None
    raw = exit_px / entry - 1.0
    return raw if row.get("direction") == "long" else -raw


# ── return-series metrics ────────────────────────────────────────────────────


def sharpe(returns: list[float], rf: float = 0.0) -> float | None:
    """Per-trade Sharpe: mean excess return / standard deviation."""
    if len(returns) < 2:
        return None
    a = np.asarray(returns, dtype=float) - rf
    sd = a.std(ddof=1)
    if not np.isfinite(sd) or sd < 1e-12:  # no meaningful variance
        return None
    return float(a.mean() / sd)


def sortino(returns: list[float], rf: float = 0.0) -> float | None:
    """Per-trade Sortino: mean excess return / downside deviation."""
    if len(returns) < 2:
        return None
    a = np.asarray(returns, dtype=float) - rf
    downside = a[a < 0]
    if downside.size == 0:
        return None  # no losing trades → Sortino undefined (infinite)
    dd = math.sqrt(float(np.mean(downside ** 2)))
    if dd < 1e-12:
        return None
    return float(a.mean() / dd)


def max_drawdown(returns: list[float]) -> float | None:
    """Worst peak-to-trough drawdown of the compounded equity curve (≤ 0)."""
    if not returns:
        return None
    equity = np.cumprod(1.0 + np.asarray(returns, dtype=float))
    peak = np.maximum.accumulate(equity)
    return float((equity / peak - 1.0).min())


def calmar(returns: list[float], periods_per_year: float) -> float | None:
    """Annualized return / |max drawdown|."""
    mdd = max_drawdown(returns)
    if mdd is None or mdd == 0:
        return None
    mean = float(np.mean(returns))
    annual = (1.0 + mean) ** periods_per_year - 1.0
    return annual / abs(mdd)


def hit_rate(rows: list[dict[str, Any]]) -> float | None:
    resolved = [r for r in rows if r.get("status") in _RESOLVED]
    if not resolved:
        return None
    return sum(1 for r in resolved if r.get("status") == "hit") / len(resolved)


def profit_factor(returns: list[float]) -> float | None:
    """Gross profit / gross loss. None when there are no losses (undefined)."""
    gains = sum(r for r in returns if r > 0)
    losses = -sum(r for r in returns if r < 0)
    if losses == 0:
        return None
    return gains / losses


# ── calibration ──────────────────────────────────────────────────────────────


def brier_score(probs: list[float], outcomes: list[int]) -> float | None:
    """Mean squared error of predicted probability vs realized 0/1 outcome.
    0 = perfect, 0.25 = always-0.5, → 1 worst. (Superforecasters ≈ 0.02–0.15.)"""
    if not probs or len(probs) != len(outcomes):
        return None
    p = np.asarray(probs, dtype=float)
    o = np.asarray(outcomes, dtype=float)
    return float(np.mean((p - o) ** 2))


def expected_calibration_error(
    probs: list[float], outcomes: list[int], bins: int = 10
) -> float | None:
    """ECE: |confidence − accuracy| averaged over equal-width probability bins,
    weighted by bin population. 0 = perfectly calibrated."""
    if not probs or len(probs) != len(outcomes):
        return None
    p = np.asarray(probs, dtype=float)
    o = np.asarray(outcomes, dtype=float)
    n = len(p)
    edges = np.linspace(0.0, 1.0, bins + 1)
    ece = 0.0
    for i in range(bins):
        lo, hi = edges[i], edges[i + 1]
        mask = (p > lo) & (p <= hi) if i > 0 else (p >= lo) & (p <= hi)
        if not mask.any():
            continue
        conf = float(p[mask].mean())
        acc = float(o[mask].mean())
        ece += (mask.sum() / n) * abs(conf - acc)
    return float(ece)


# ── skew / kurtosis (sample) ─────────────────────────────────────────────────


def _skew_kurt(returns: list[float]) -> tuple[float, float]:
    a = np.asarray(returns, dtype=float)
    n = a.size
    sd = a.std(ddof=0)
    if n < 2 or sd == 0:
        return 0.0, 3.0
    m3 = float(np.mean((a - a.mean()) ** 3)) / sd ** 3
    m4 = float(np.mean((a - a.mean()) ** 4)) / sd ** 4
    return m3, m4  # kurtosis is the NON-excess (normal = 3) form PSR expects


# ── Probabilistic & Deflated Sharpe (Bailey & López de Prado) ────────────────


def probabilistic_sharpe_ratio(
    sr: float, n: int, skew: float, kurt: float, sr_benchmark: float = 0.0
) -> float | None:
    """P(true Sharpe > benchmark) given the observed SR, sample size and the
    return distribution's skew/kurtosis (non-excess). Bailey & López de Prado."""
    if n < 2:
        return None
    denom = 1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr ** 2
    if denom <= 0:
        return None
    z = (sr - sr_benchmark) * math.sqrt(n - 1) / math.sqrt(denom)
    return _norm_cdf(z)


def deflated_sharpe_ratio(
    sr: float, n: int, skew: float, kurt: float, n_trials: int, variance_trials: float = 1.0
) -> float | None:
    """DSR = PSR against a benchmark inflated for selection across ``n_trials``.

    The benchmark SR0 is the expected MAXIMUM Sharpe of ``n_trials`` independent
    strategies with the given trial-Sharpe variance (Bailey & López de Prado,
    'The Deflated Sharpe Ratio'). Higher trial count ⇒ higher bar ⇒ lower DSR.
    """
    if n < 2 or n_trials < 1:
        return None
    if n_trials == 1:
        sr0 = 0.0
    else:
        euler_mascheroni = 0.5772156649015329
        e = math.e
        # E[max] ≈ √V · [ (1-γ)·Φ⁻¹(1 - 1/N) + γ·Φ⁻¹(1 - 1/(N·e)) ]
        z1 = _norm_ppf(1.0 - 1.0 / n_trials)
        z2 = _norm_ppf(1.0 - 1.0 / (n_trials * e))
        sr0 = math.sqrt(variance_trials) * ((1.0 - euler_mascheroni) * z1 + euler_mascheroni * z2)
    return probabilistic_sharpe_ratio(sr, n, skew, kurt, sr_benchmark=sr0)


def _norm_ppf(p: float) -> float:
    """Inverse normal CDF (Acklam's rational approximation)."""
    if p <= 0.0:
        return -math.inf
    if p >= 1.0:
        return math.inf
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    q = p - 0.5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
           (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)


# ── purged k-fold robustness ─────────────────────────────────────────────────


def purged_kfold_sharpe(returns: list[float], k: int = 5, embargo: int = 1) -> dict[str, Any] | None:
    """Re-estimate Sharpe on k purged folds of the ORDERED return ledger.

    Each fold drops a contiguous test block plus an embargo gap around it and
    measures the metric on the rest, giving a stability band (mean ± std). A
    CPCV-flavoured robustness check — NOT a full combinatorial-purged CV (that
    needs a price-path backtest, which a discrete trade ledger can't supply)."""
    n = len(returns)
    if n < k or k < 2:
        return None
    fold_sizes = np.array_split(np.arange(n), k)
    estimates: list[float] = []
    for fold in fold_sizes:
        lo, hi = int(fold[0]), int(fold[-1])
        keep = [returns[i] for i in range(n) if i < lo - embargo or i > hi + embargo]
        s = sharpe(keep)
        if s is not None:
            estimates.append(s)
    if not estimates:
        return None
    arr = np.asarray(estimates)
    return {"folds": len(estimates), "mean": float(arr.mean()), "std": float(arr.std(ddof=0))}


# ── scorecard assembly ───────────────────────────────────────────────────────


def _cell_metrics(rows: list[dict[str, Any]], *, n_trials: int) -> dict[str, Any]:
    resolved = [r for r in rows if r.get("status") in _RESOLVED]
    returns = [r for r in (realized_return(x) for x in resolved) if r is not None]
    probs = [float(r.get("confidence") or 0.0) for r in resolved if realized_return(r) is not None]
    outcomes = [1 if r.get("status") == "hit" else 0 for r in resolved if realized_return(r) is not None]

    # Trades-per-year for this cell's horizon → annualization factor.
    hours = float(np.median([r.get("horizon_hours") or 24 for r in resolved])) if resolved else 24.0
    ppy = max(1.0, _HOURS_PER_YEAR / hours)

    sr = sharpe(returns)
    skew, kurt = _skew_kurt(returns) if len(returns) >= 2 else (0.0, 3.0)
    mean_ret = float(np.mean(returns)) if returns else None
    return {
        "n_resolved": len(resolved),
        "n_returns": len(returns),
        "avg_return_pct": round(mean_ret * 100.0, 3) if mean_ret is not None else None,
        "total_return_pct": round((float(np.prod([1 + r for r in returns])) - 1.0) * 100.0, 3) if returns else None,
        "hit_rate": _r(hit_rate(rows)),
        "profit_factor": _r(profit_factor(returns)),
        "sharpe": _r(sr),
        "sharpe_annualized": _r(sr * math.sqrt(ppy)) if sr is not None else None,
        "sortino": _r(sortino(returns)),
        "calmar": _r(calmar(returns, ppy)),
        "max_drawdown_pct": round(max_drawdown(returns) * 100.0, 3) if max_drawdown(returns) is not None else None,
        "brier": _r(brier_score(probs, outcomes)),
        "ece": _r(expected_calibration_error(probs, outcomes)),
        "psr": _r(probabilistic_sharpe_ratio(sr, len(returns), skew, kurt)) if sr is not None else None,
        "dsr": _r(deflated_sharpe_ratio(sr, len(returns), skew, kurt, n_trials)) if sr is not None else None,
        "purged_kfold": purged_kfold_sharpe(returns),
        "avg_confidence": round(float(np.mean(probs)), 3) if probs else None,
    }


def _r(x: float | None, p: int = 4) -> float | None:
    return round(x, p) if x is not None else None


def build_scorecard(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Replay resolved targets into an overall + per (horizon × asset-class) scorecard.

    ``rows`` are TradeTarget-shaped dicts (status, direction, entry_price,
    resolved_price, confidence, horizon_hours, asset_class). ``n_trials`` for the
    DSR is the count of distinct (asset, horizon) strategy cells actually scored —
    the selection breadth the jury is correcting for.
    """
    resolved = [r for r in rows if r.get("status") in _RESOLVED and realized_return(r) is not None]
    # Group into cells keyed by (horizon bucket, asset class).
    cells: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for r in resolved:
        key = (hz.bucket_for_hours(r.get("horizon_hours")), r.get("asset_class") or "unknown")
        cells.setdefault(key, []).append(r)
    n_trials = max(1, len(cells))

    by_cell = [
        {"horizon": h, "asset_class": a, **_cell_metrics(rs, n_trials=n_trials)}
        for (h, a), rs in sorted(cells.items())
    ]
    overall = _cell_metrics(resolved, n_trials=n_trials)
    return {
        "n_total": len(rows),
        "n_resolved": len(resolved),
        "n_cells": len(cells),
        "overall": overall,
        "by_cell": by_cell,
        "notes": (
            "Win-rate is not the headline — calibration (Brier/ECE) and risk-adjusted "
            "return (Sortino, DSR) are. DSR deflates Sharpe for the number of strategy "
            "cells tested. A thin sample is not statistically conclusive."
        ),
    }
