"""Portfolio optimization — mean-variance, risk parity, efficient frontier.

The natural sequel to ``calc_tools.compute_allocation_drift``: that tool answers
"how far am I from my target?", this one answers "what should the target be?".

Estimation error is the real enemy here, not the optimizer. Mean-variance
optimization is an *error maximizer* — it loads up on whichever asset's mean was
most overestimated and whose covariance was most underestimated (Michaud 1989).
Two defences are therefore on by default rather than offered as options:

* **Ledoit-Wolf shrinkage** of the covariance matrix toward a scaled identity,
  which conditions the matrix when the number of assets approaches the number of
  observations.
* **Risk parity** is offered alongside max-Sharpe precisely because it ignores
  expected returns, the noisiest input of all.

Sources
-------
* Markowitz (1952) — mean-variance framing.
* Ledoit & Wolf (2004), *A Well-Conditioned Estimator for Large-Dimensional
  Covariance Matrices* — the shrinkage intensity used here.
* Michaud (1989), *The Markowitz Optimization Enigma: Is Optimized Optimal?*
* Maillard, Roncalli & Teïletche (2010) — equal risk contribution.

Honest limits
-------------
* Historical mean returns are a poor forecast of future mean returns. Every
  output of this module should be read as "what would have been optimal", not
  "what will be optimal".
* Long-only solutions come from SLSQP, a *local* solver. The result is verified
  (weights sum to 1, all within bounds) and the caller is told when it fell back.
* No transaction costs, no taxes, no liquidity or lot-size constraints.
"""
from __future__ import annotations

import logging
import math
from typing import Any

import numpy as np

log = logging.getLogger("fincoach.quant.optimize")

_EPS = 1e-12


# ── moments ──────────────────────────────────────────────────────────────────


def ledoit_wolf_shrink(returns_matrix: np.ndarray) -> tuple[np.ndarray, float]:
    """Ledoit-Wolf shrinkage toward a scaled identity.

    ``returns_matrix`` is (T observations × N assets). Returns the shrunk
    covariance and the shrinkage intensity actually applied (0 = pure sample
    covariance, 1 = pure identity target), so the caller can report it.
    """
    x = np.asarray(returns_matrix, dtype=float)
    t, n = x.shape
    if t < 2 or n < 1:
        return np.cov(x, rowvar=False, ddof=1), 0.0
    xc = x - x.mean(axis=0)
    sample = (xc.T @ xc) / t

    m = float(np.trace(sample) / n)
    d2 = float(((sample - m * np.eye(n)) ** 2).sum() / n)
    if d2 <= _EPS:
        return sample, 0.0
    # Mean squared deviation of the per-observation outer products from S.
    b2_bar = float(
        sum(float(((np.outer(xc[i], xc[i]) - sample) ** 2).sum()) for i in range(t))
        / (t ** 2 * n)
    )
    b2 = min(b2_bar, d2)
    intensity = b2 / d2
    shrunk = intensity * m * np.eye(n) + (1.0 - intensity) * sample
    # Rescale to an unbiased (ddof=1) footing so vols match the rest of the app.
    return shrunk * (t / max(1, t - 1)), float(intensity)


def moments(
    returns_matrix: np.ndarray, ppy: float = 252.0, *, shrink: bool = True
) -> tuple[np.ndarray, np.ndarray, float]:
    """Annualised ``(mu, cov, shrinkage_intensity)`` from a (T × N) return matrix."""
    x = np.asarray(returns_matrix, dtype=float)
    mu = x.mean(axis=0) * ppy
    if shrink:
        cov, intensity = ledoit_wolf_shrink(x)
    else:
        cov, intensity = np.cov(x, rowvar=False, ddof=1), 0.0
    cov = np.atleast_2d(cov) * ppy
    return mu, cov, intensity


# ── portfolio statistics ─────────────────────────────────────────────────────


def portfolio_stats(
    weights: np.ndarray, mu: np.ndarray, cov: np.ndarray, rf: float = 0.0
) -> dict[str, float]:
    w = np.asarray(weights, dtype=float)
    ret = float(w @ mu)
    var = float(w @ cov @ w)
    vol = math.sqrt(max(var, 0.0))
    return {
        "return_pct": round(ret * 100.0, 3),
        "vol_pct": round(vol * 100.0, 3),
        "sharpe": round((ret - rf) / vol, 4) if vol > _EPS else 0.0,
    }


def risk_contributions(weights: np.ndarray, cov: np.ndarray) -> np.ndarray:
    """Each asset's share of total portfolio variance (sums to 1)."""
    w = np.asarray(weights, dtype=float)
    total = float(w @ cov @ w)
    if total <= _EPS:
        return np.full(w.size, 1.0 / max(1, w.size))
    return w * (cov @ w) / total


# ── solvers ──────────────────────────────────────────────────────────────────


def _bounds(n: int, long_only: bool, w_max: float | None) -> list[tuple[float, float]]:
    hi = 1.0 if w_max is None else float(min(1.0, max(1.0 / n, w_max)))
    return [((0.0 if long_only else -1.0), hi)] * n


def _valid(w: np.ndarray | None, bounds: list[tuple[float, float]]) -> bool:
    if w is None or not np.all(np.isfinite(w)):
        return False
    if abs(float(w.sum()) - 1.0) > 1e-6:
        return False
    lo, hi = bounds[0]
    return bool(np.all(w >= lo - 1e-6) and np.all(w <= hi + 1e-6))


def _solve(
    objective, n: int, bounds: list[tuple[float, float]], extra_constraints: list | None = None
) -> np.ndarray | None:
    """SLSQP from an equal-weight start, with the budget constraint always on."""
    from scipy.optimize import minimize  # noqa: PLC0415 — heavy import, defer it

    cons: list[dict[str, Any]] = [{"type": "eq", "fun": lambda w: float(w.sum()) - 1.0}]
    cons.extend(extra_constraints or [])
    x0 = np.full(n, 1.0 / n)
    try:
        res = minimize(
            objective, x0, method="SLSQP", bounds=bounds, constraints=cons,
            options={"maxiter": 500, "ftol": 1e-12},
        )
    except Exception as exc:  # noqa: BLE001 — a solver blow-up must not reach the graph
        log.info("optimize: SLSQP failed: %s", exc)
        return None
    w = np.asarray(res.x, dtype=float)
    return w if _valid(w, bounds) else None


def min_variance(
    cov: np.ndarray, *, long_only: bool = True, w_max: float | None = None
) -> np.ndarray:
    """Minimum-variance weights. Closed form when unconstrained, SLSQP otherwise."""
    n = cov.shape[0]
    if n == 1:
        return np.ones(1)
    bounds = _bounds(n, long_only, w_max)
    if not long_only and w_max is None:
        try:
            inv = np.linalg.pinv(cov)
            ones = np.ones(n)
            w = inv @ ones
            denom = float(ones @ w)
            if abs(denom) > _EPS:
                return w / denom
        except np.linalg.LinAlgError:
            pass
    w = _solve(lambda w: float(w @ cov @ w), n, bounds)
    return w if w is not None else np.full(n, 1.0 / n)


def max_sharpe(
    mu: np.ndarray, cov: np.ndarray, rf: float = 0.0, *,
    long_only: bool = True, w_max: float | None = None,
) -> tuple[np.ndarray, bool]:
    """Tangency portfolio. Returns ``(weights, converged)``.

    ``converged=False`` means SLSQP did not return a feasible point and the
    result fell back to minimum variance — the caller must say so rather than
    presenting a fallback as an optimum.
    """
    n = cov.shape[0]
    if n == 1:
        return np.ones(1), True
    bounds = _bounds(n, long_only, w_max)

    if not long_only and w_max is None:
        try:
            excess = mu - rf
            w = np.linalg.pinv(cov) @ excess
            denom = float(np.ones(n) @ w)
            if abs(denom) > _EPS:
                return w / denom, True
        except np.linalg.LinAlgError:
            pass

    def neg_sharpe(w: np.ndarray) -> float:
        vol = math.sqrt(max(float(w @ cov @ w), 0.0))
        if vol < _EPS:
            return 1e6
        return -(float(w @ mu) - rf) / vol

    w = _solve(neg_sharpe, n, bounds)
    if w is None:
        log.info("optimize: max_sharpe did not converge; falling back to min-variance")
        return min_variance(cov, long_only=long_only, w_max=w_max), False
    return w, True


def risk_parity(cov: np.ndarray, *, tol: float = 1e-9, max_iter: int = 2000) -> np.ndarray:
    """Equal risk contribution weights — no expected-return input at all.

    Multiplicative fixed-point iteration (Maillard et al.): scale each weight by
    the square root of the ratio between its target and actual risk share, then
    renormalise. Long-only by construction.
    """
    n = cov.shape[0]
    if n == 1:
        return np.ones(1)
    target = 1.0 / n
    w = np.full(n, target)
    for _ in range(max_iter):
        rc = risk_contributions(w, cov)
        if float(np.max(np.abs(rc - target))) < tol:
            break
        w = w * np.sqrt(target / np.maximum(rc, _EPS))
        total = float(w.sum())
        if total <= _EPS or not np.all(np.isfinite(w)):
            return np.full(n, target)
        w = w / total
    return w


def efficient_frontier(
    mu: np.ndarray, cov: np.ndarray, *, n_points: int = 20,
    long_only: bool = True, w_max: float | None = None, rf: float = 0.0,
) -> list[dict[str, Any]]:
    """Minimum-variance portfolio for each of ``n_points`` target returns.

    Infeasible targets are skipped rather than approximated, so every returned
    point is a real solution.
    """
    n = cov.shape[0]
    if n < 2:
        return []
    bounds = _bounds(n, long_only, w_max)
    lo, hi = float(np.min(mu)), float(np.max(mu))
    if hi - lo < _EPS:
        return []

    points: list[dict[str, Any]] = []
    for target in np.linspace(lo, hi, max(2, n_points)):
        w = _solve(
            lambda w: float(w @ cov @ w), n, bounds,
            [{"type": "eq", "fun": (lambda w, tr=target: float(w @ mu) - tr)}],
        )
        if w is None:
            continue
        stats = portfolio_stats(w, mu, cov, rf)
        points.append({**stats, "weights": [round(float(x), 6) for x in w]})

    # Keep the frontier monotone in risk so the scatter reads as a curve.
    points.sort(key=lambda p: p["vol_pct"])
    return points
