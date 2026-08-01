"""Option pricing — Black-Scholes-Merton, greeks, implied volatility, jumps.

Scope note, stated up front because it matters more than the math: **this app
has no option-chain data source.** Nothing here reads a live quote. These are
calculators over inputs the user (or another tool) supplies, which is why the
tool layer labels them as such. They exist because the app already surfaces
crypto derivatives — funding rate, open interest, squeeze risk — and those
conversations run into implied volatility immediately.

Sources
-------
* Black & Scholes (1973), Merton (1973) — the closed form and its greeks.
* Merton (1976), *Option Pricing When Underlying Stock Returns Are
  Discontinuous* — the Poisson jump-diffusion series used here.

Honest limits
-------------
* Black-Scholes assumes constant volatility and continuous paths. Crypto has
  neither: realised vol clusters and the tape gaps. A single BS number is a
  quoting convention, not a fair value — which is exactly why implied vol (and
  its smile) is the thing worth looking at.
* The jump-diffusion price is a truncated series; it converges quickly for
  sane jump intensities but is not exact.
* American exercise, dividends beyond a continuous yield, and early-exercise
  premia are not modelled.
"""
from __future__ import annotations

import math
from typing import Any

from app.eval.scorecard import _norm_cdf

_SQRT_2PI = math.sqrt(2.0 * math.pi)
_MIN_VOL = 1e-6
_MAX_VOL = 5.0


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / _SQRT_2PI


def _d1_d2(S: float, K: float, T: float, r: float, sigma: float, q: float) -> tuple[float, float]:
    vt = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / vt
    return d1, d1 - vt


def _valid(S: float, K: float, T: float, sigma: float) -> bool:
    return all(math.isfinite(x) for x in (S, K, T, sigma)) and S > 0 and K > 0 and T > 0 and sigma > 0


def bs_price(
    S: float, K: float, T: float, r: float, sigma: float, *, kind: str = "call", q: float = 0.0
) -> float | None:
    """Black-Scholes-Merton price. ``T`` in years, rates/vol as decimals.

    Returns None on degenerate input rather than raising — the tool layer turns
    that into an ``err()`` envelope.
    """
    if not _valid(S, K, T, sigma):
        return None
    d1, d2 = _d1_d2(S, K, T, r, sigma, q)
    disc_q, disc_r = math.exp(-q * T), math.exp(-r * T)
    if kind == "call":
        return float(S * disc_q * _norm_cdf(d1) - K * disc_r * _norm_cdf(d2))
    if kind == "put":
        return float(K * disc_r * _norm_cdf(-d2) - S * disc_q * _norm_cdf(-d1))
    return None


def bs_greeks(
    S: float, K: float, T: float, r: float, sigma: float, *, kind: str = "call", q: float = 0.0
) -> dict[str, float] | None:
    """Greeks in trading units.

    ``vega`` and ``rho`` are per **1 percentage point** move (not per 1.00), and
    ``theta`` is per **calendar day** — the units a desk actually quotes.
    """
    if not _valid(S, K, T, sigma) or kind not in ("call", "put"):
        return None
    d1, d2 = _d1_d2(S, K, T, r, sigma, q)
    disc_q, disc_r = math.exp(-q * T), math.exp(-r * T)
    sqrt_t = math.sqrt(T)
    pdf_d1 = _norm_pdf(d1)

    gamma = disc_q * pdf_d1 / (S * sigma * sqrt_t)
    vega = S * disc_q * pdf_d1 * sqrt_t
    common_theta = -(S * disc_q * pdf_d1 * sigma) / (2.0 * sqrt_t)

    if kind == "call":
        delta = disc_q * _norm_cdf(d1)
        theta = common_theta - r * K * disc_r * _norm_cdf(d2) + q * S * disc_q * _norm_cdf(d1)
        rho = K * T * disc_r * _norm_cdf(d2)
    else:
        delta = disc_q * (_norm_cdf(d1) - 1.0)
        theta = common_theta + r * K * disc_r * _norm_cdf(-d2) - q * S * disc_q * _norm_cdf(-d1)
        rho = -K * T * disc_r * _norm_cdf(-d2)

    return {
        "delta": float(delta),
        "gamma": float(gamma),
        "vega": float(vega / 100.0),      # per 1 vol point
        "theta": float(theta / 365.0),    # per calendar day
        "rho": float(rho / 100.0),        # per 1 rate point
    }


def _no_arb_bounds(
    S: float, K: float, T: float, r: float, q: float, kind: str
) -> tuple[float, float]:
    disc_q, disc_r = math.exp(-q * T), math.exp(-r * T)
    if kind == "call":
        return max(0.0, S * disc_q - K * disc_r), S * disc_q
    return max(0.0, K * disc_r - S * disc_q), K * disc_r


def implied_vol(
    price: float, S: float, K: float, T: float, r: float, *,
    kind: str = "call", q: float = 0.0,
) -> float | None:
    """Implied volatility by Brent root-finding, with a bisection fallback.

    Returns None when the quote violates the no-arbitrage bounds or the root
    lies outside ``[1e-6, 5.0]`` — a deep OTM quote often has no solution at
    all. Never returns a fabricated number.
    """
    if not all(math.isfinite(x) for x in (price, S, K, T, r, q)) or S <= 0 or K <= 0 or T <= 0:
        return None
    if kind not in ("call", "put"):
        return None
    lo_bound, hi_bound = _no_arb_bounds(S, K, T, r, q, kind)
    if price < lo_bound - 1e-9 or price > hi_bound + 1e-9:
        return None

    def f(sigma: float) -> float:
        p = bs_price(S, K, T, r, sigma, kind=kind, q=q)
        return float("nan") if p is None else p - price

    f_lo, f_hi = f(_MIN_VOL), f(_MAX_VOL)
    if not (math.isfinite(f_lo) and math.isfinite(f_hi)) or f_lo * f_hi > 0:
        return None

    try:
        from scipy.optimize import brentq  # noqa: PLC0415 — defer the heavy import

        return float(brentq(f, _MIN_VOL, _MAX_VOL, xtol=1e-10, maxiter=200))
    except Exception:  # noqa: BLE001 — fall back rather than fail the tool
        lo, hi = _MIN_VOL, _MAX_VOL
        for _ in range(200):
            mid = 0.5 * (lo + hi)
            if f(lo) * f(mid) <= 0:
                hi = mid
            else:
                lo = mid
        return float(0.5 * (lo + hi))


def merton_jump_price(
    S: float, K: float, T: float, r: float, sigma: float, *,
    lam: float = 0.5, mu_j: float = -0.05, sigma_j: float = 0.15,
    kind: str = "call", q: float = 0.0, n_terms: int = 40,
) -> float | None:
    """Merton (1976) jump-diffusion price — a Poisson mixture of BS prices.

    ``lam`` is the expected number of jumps per year; ``mu_j``/``sigma_j`` are
    the mean and stdev of the log jump size. A negative ``mu_j`` produces the
    left-skewed distribution that generates a volatility smirk. Collapses
    exactly to Black-Scholes when ``lam = 0``.
    """
    if not _valid(S, K, T, sigma) or lam < 0 or sigma_j < 0 or kind not in ("call", "put"):
        return None
    if lam == 0:
        return bs_price(S, K, T, r, sigma, kind=kind, q=q)

    k = math.exp(mu_j + 0.5 * sigma_j * sigma_j) - 1.0
    total, log_factorial = 0.0, 0.0
    for n in range(max(1, n_terms)):
        if n > 0:
            log_factorial += math.log(n)
        log_weight = -lam * T + n * math.log(lam * T) - log_factorial
        weight = math.exp(log_weight)
        if n > 5 and weight < 1e-12:
            break
        sigma_n = math.sqrt(sigma * sigma + n * sigma_j * sigma_j / T)
        r_n = r - lam * k + n * math.log1p(k) / T
        p = bs_price(S, K, T, r_n, sigma_n, kind=kind, q=q)
        if p is None:
            continue
        total += weight * p
    return float(total)


def smile(
    strikes: list[float], prices: list[float], S: float, T: float, r: float, *,
    kind: str = "call", q: float = 0.0,
) -> list[dict[str, Any]]:
    """Implied vol per strike — the volatility smile/smirk.

    Strikes with no solvable implied vol are returned with ``iv_pct: None``
    rather than dropped, so the caller can see the gaps.
    """
    out: list[dict[str, Any]] = []
    for strike, price in zip(strikes, prices, strict=False):
        iv = implied_vol(price, S, float(strike), T, r, kind=kind, q=q)
        out.append({
            "strike": round(float(strike), 6),
            "price": round(float(price), 6),
            "moneyness": round(float(strike) / S, 4) if S > 0 else None,
            "iv_pct": round(iv * 100.0, 3) if iv is not None else None,
        })
    return out
