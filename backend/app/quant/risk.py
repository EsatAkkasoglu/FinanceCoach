"""Risk analytics — tail risk, benchmark-relative statistics, factor exposure.

Fills the gaps ``calc_tools.analyze_portfolio_risk`` leaves: it already reports
volatility, Sharpe, drawdown and a correlation matrix, but says nothing about
how bad a bad day gets (VaR/CVaR), how much of the move is just the market
(beta), or what the portfolio is *really* exposed to (factors).

Conventions
-----------
* Returns are simple period returns as decimals, oldest first.
* **VaR and CVaR are returned as positive loss magnitudes.** ``0.023`` means
  "a 2.3% loss"; the sign convention is stated in every docstring because
  getting it backwards is the classic risk-report bug.
* ``ppy`` (periods per year) annualises: 252 daily, 52 weekly, 12 monthly.

Sources
-------
* J.P. Morgan/Reuters, *RiskMetrics Technical Document* (1996) — the λ = 0.94
  daily EWMA decay.
* Cornish & Fisher (1938) — the skew/kurtosis expansion of the normal quantile.
* Fama & French (1993) — the factor-regression framing. Note the honest limit
  below: these are **ETF proxies**, not the research factor series.

Honest limits
-------------
* Historical VaR cannot see a loss larger than the worst day in the window; it
  is a description of the sample, not a forecast of the tail.
* Cornish-Fisher is a third/fourth-moment correction, not a fat-tailed model.
  It degrades for extreme skew/kurtosis and can even become non-monotonic.
* Factor betas come from liquid ETF proxies (SPY, IWM, IWD/IWF, MTUM), so they
  carry each ETF's own tracking error and fees. They are indicative, not the
  Kenneth French research series.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

from app.eval.scorecard import _norm_ppf, _skew_kurt

#: ETF stand-ins for the classic long/short factor legs. Chosen for liquidity
#: and because they are already reachable through the existing yfinance path —
#: no new data vendor, no licensed research file.
FACTOR_PROXIES: dict[str, tuple[str, str | None]] = {
    "market": ("SPY", None),      # broad US equity
    "size": ("IWM", "SPY"),       # small minus large
    "value": ("IWD", "IWF"),      # value minus growth
    "momentum": ("MTUM", "SPY"),  # momentum minus market
}


def _clean(returns: Any) -> np.ndarray:
    r = np.asarray(returns, dtype=float).ravel()
    return r[np.isfinite(r)]


# ── tail risk ────────────────────────────────────────────────────────────────


def historical_var(returns: Any, alpha: float = 0.95) -> float | None:
    """Historical Value at Risk as a **positive loss fraction**.

    The empirical ``(1-alpha)`` quantile of the return distribution. No
    distributional assumption — and no ability to see past the worst
    observation in the window.
    """
    r = _clean(returns)
    if r.size < 2 or not 0.5 < alpha < 1.0:
        return None
    return float(-np.percentile(r, (1.0 - alpha) * 100.0))


def historical_cvar(returns: Any, alpha: float = 0.95) -> float | None:
    """Conditional VaR (expected shortfall) as a positive loss fraction.

    The mean loss on the days that breached VaR — "when it's bad, how bad".
    """
    r = _clean(returns)
    if r.size < 2 or not 0.5 < alpha < 1.0:
        return None
    threshold = np.percentile(r, (1.0 - alpha) * 100.0)
    tail = r[r <= threshold]
    if tail.size == 0:
        return None
    return float(-tail.mean())


def cornish_fisher_var(returns: Any, alpha: float = 0.95) -> float | None:
    """Parametric VaR with a skew/kurtosis correction, as a positive fraction.

    Adjusts the normal quantile for the sample's third and fourth moments, so a
    negatively skewed, fat-tailed series gets a larger VaR than Gaussian would
    give. Returns None if the expansion misbehaves (it is only a local
    correction and can invert under extreme moments).
    """
    r = _clean(returns)
    if r.size < 4 or not 0.5 < alpha < 1.0:
        return None
    mu = float(r.mean())
    sd = float(r.std(ddof=1))
    if sd <= 1e-15:
        return None
    skew, kurt = _skew_kurt([float(x) for x in r])
    excess = kurt - 3.0
    z = _norm_ppf(1.0 - alpha)
    z_cf = (
        z
        + (z ** 2 - 1.0) * skew / 6.0
        + (z ** 3 - 3.0 * z) * excess / 24.0
        - (2.0 * z ** 3 - 5.0 * z) * skew ** 2 / 36.0
    )
    if z_cf >= 0:  # the correction flipped the quantile — refuse to report it
        return None
    return float(-(mu + z_cf * sd))


def ewma_vol(returns: Any, lam: float = 0.94, ppy: float = 252.0) -> float | None:
    """Annualised RiskMetrics EWMA volatility.

    Weights recent observations more heavily than a flat sample stdev, so it
    reacts to a regime change instead of averaging it away. λ = 0.94 is the
    RiskMetrics daily default.
    """
    r = _clean(returns)
    if r.size < 2 or not 0.0 < lam < 1.0:
        return None
    var = float(r.var(ddof=1))  # seed with the sample variance
    for x in r:
        var = lam * var + (1.0 - lam) * x * x
    if var <= 0:
        return None
    return float(math.sqrt(var * ppy))


def rolling_drawdown(returns: Any) -> np.ndarray:
    """Drawdown at every bar (≤ 0) of the compounded equity curve."""
    r = _clean(returns)
    if r.size == 0:
        return np.asarray([], dtype=float)
    equity = np.cumprod(1.0 + r)
    return equity / np.maximum.accumulate(equity) - 1.0


# ── regression helpers ───────────────────────────────────────────────────────


def _ols(y: np.ndarray, x: np.ndarray) -> dict[str, Any] | None:
    """OLS of y on x (with intercept). Returns coefficients, t-stats, p, R²."""
    n, k = x.shape[0], x.shape[1] + 1
    if n <= k:
        return None
    design = np.column_stack([np.ones(n), x])
    coef, *_ = np.linalg.lstsq(design, y, rcond=None)
    resid = y - design @ coef
    dof = n - k
    rss = float(resid @ resid)
    tss = float(((y - y.mean()) ** 2).sum())
    sigma2 = rss / dof if dof > 0 else float("nan")

    try:
        xtx_inv = np.linalg.inv(design.T @ design)
    except np.linalg.LinAlgError:
        return None
    se = np.sqrt(np.maximum(sigma2 * np.diag(xtx_inv), 0.0))
    with np.errstate(divide="ignore", invalid="ignore"):
        tstat = np.where(se > 0, coef / se, np.nan)

    from scipy import stats  # noqa: PLC0415 — keep import cost off module load

    pval = 2.0 * stats.t.sf(np.abs(tstat), dof)
    return {
        "coef": coef,
        "tstat": tstat,
        "pval": pval,
        "r2": (1.0 - rss / tss) if tss > 0 else None,
        "resid": resid,
        "dof": dof,
    }


def beta_alpha(
    returns: Any, benchmark: Any, *, rf_annual: float = 0.0, ppy: float = 252.0
) -> dict[str, Any] | None:
    """Single-factor regression of an asset/portfolio on a benchmark.

    Reports beta (market sensitivity), annualised Jensen's alpha, R² (how much
    of the variance is just the benchmark), the t-statistic on beta, annualised
    idiosyncratic volatility, and tracking error. Excess returns are used on
    both sides when ``rf_annual`` is non-zero.
    """
    y = _clean(returns)
    x = _clean(benchmark)
    n = min(y.size, x.size)
    if n < 3:
        return None
    rf_bar = rf_annual / ppy
    y, x = y[-n:] - rf_bar, x[-n:] - rf_bar

    fit = _ols(y, x.reshape(-1, 1))
    if fit is None:
        return None
    alpha_bar, beta = float(fit["coef"][0]), float(fit["coef"][1])
    resid = fit["resid"]
    active = y - x
    corr = float(np.corrcoef(y, x)[0, 1]) if y.std() > 0 and x.std() > 0 else None

    return {
        "n_obs": int(n),
        "beta": round(beta, 4),
        "alpha_annualized_pct": round(alpha_bar * ppy * 100.0, 3),
        "r2": round(float(fit["r2"]), 4) if fit["r2"] is not None else None,
        "beta_t_stat": round(float(fit["tstat"][1]), 3) if np.isfinite(fit["tstat"][1]) else None,
        "beta_p_value": round(float(fit["pval"][1]), 4),
        "correlation": round(corr, 4) if corr is not None and math.isfinite(corr) else None,
        "idiosyncratic_vol_pct": round(float(resid.std(ddof=1)) * math.sqrt(ppy) * 100.0, 3),
        "tracking_error_pct": round(float(active.std(ddof=1)) * math.sqrt(ppy) * 100.0, 3),
    }


def capture_ratios(returns: Any, benchmark: Any) -> dict[str, float | None]:
    """Up/down capture: share of the benchmark's gain (loss) the asset caught.

    100% up / 80% down is the shape every investor wants; above 100% on both
    is just leverage.
    """
    y = _clean(returns)
    x = _clean(benchmark)
    n = min(y.size, x.size)
    if n < 2:
        return {"up_capture_pct": None, "down_capture_pct": None}
    y, x = y[-n:], x[-n:]

    def _cap(mask: np.ndarray) -> float | None:
        if mask.sum() < 2:
            return None
        denom = float(x[mask].mean())
        if abs(denom) < 1e-12:
            return None
        return round(float(y[mask].mean()) / denom * 100.0, 2)

    return {"up_capture_pct": _cap(x > 0), "down_capture_pct": _cap(x < 0)}


def factor_exposures(
    returns: Any, factors: dict[str, Any], *, ppy: float = 252.0
) -> dict[str, Any] | None:
    """Multi-factor OLS of a return series on factor return series.

    Each factor's loading comes with a t-statistic and p-value so a reader can
    tell a real exposure from noise. ``alpha`` is what the factors do *not*
    explain — annualised, and to be read sceptically at short sample lengths.
    """
    y = _clean(returns)
    names = sorted(factors)
    cols = [_clean(factors[k]) for k in names]
    if not cols:
        return None
    n = min([y.size] + [c.size for c in cols])
    if n < len(names) + 3:
        return None
    y = y[-n:]
    x = np.column_stack([c[-n:] for c in cols])

    fit = _ols(y, x)
    if fit is None:
        return None
    return {
        "n_obs": int(n),
        "alpha_annualized_pct": round(float(fit["coef"][0]) * ppy * 100.0, 3),
        "alpha_t_stat": round(float(fit["tstat"][0]), 3) if np.isfinite(fit["tstat"][0]) else None,
        "r2": round(float(fit["r2"]), 4) if fit["r2"] is not None else None,
        "idiosyncratic_vol_pct": round(
            float(fit["resid"].std(ddof=1)) * math.sqrt(ppy) * 100.0, 3
        ),
        "factors": [
            {
                "factor": name,
                "beta": round(float(fit["coef"][i + 1]), 4),
                "t_stat": (
                    round(float(fit["tstat"][i + 1]), 3)
                    if np.isfinite(fit["tstat"][i + 1]) else None
                ),
                "p_value": round(float(fit["pval"][i + 1]), 4),
                "significant": bool(fit["pval"][i + 1] < 0.05),
            }
            for i, name in enumerate(names)
        ],
        "note": (
            "Factors are liquid ETF proxies, not the Kenneth French research "
            "series — loadings are indicative and carry each ETF's own fees."
        ),
    }
