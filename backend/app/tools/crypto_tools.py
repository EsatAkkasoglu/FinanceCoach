"""Crypto derivatives tools — funding rate, open interest, health & squeeze risk.

These wrap the CoinDesk Data API derivatives endpoints and implement the
algorithms surfaced from the crypto-derivatives literature (via NotebookLM):

  • Funding-rate normalisation to an 8-hour equivalent + APY.
  • A derivatives-aware health score built from rolling Z-scores of basis,
    open-interest trend and funding rate.
  • A funding-rate × open-interest 2×2 matrix flagging crowded longs/shorts
    and squeeze risk.

Every number is computed HERE in plain Python and returned through the shared
``ok``/``err`` envelope so the prose layer quotes ``formatted_value`` verbatim
and never re-calculates.
"""
from __future__ import annotations

import logging
import math
import statistics
from typing import Any

from langchain_core.tools import tool

import app.services.coindesk as cd
from app.services.coindesk import CoinDeskError
from app.tools._cache import cache_get, cache_set
from app.tools._calc_result import err, format_pct, ok

log = logging.getLogger("fincoach.tools.crypto")

# Z-score thresholds for the squeeze-risk matrix (standard deviations).
_Z_EXTREME = 1.5
_Z_TREND = 1.0
# Rolling window (days) for Z-score standardisation.
_Z_WINDOW = 30


def _zscore_latest(series_newest_first: list[float], window: int = _Z_WINDOW) -> float | None:
    """Z-score of the most recent value vs the trailing ``window`` mean/std.

    ``series`` is newest-first. Returns None when there's too little data or
    zero variance.
    """
    if len(series_newest_first) < 5:
        return None
    window_vals = series_newest_first[: window + 1]
    latest = window_vals[0]
    history = window_vals[1:] if len(window_vals) > 1 else window_vals
    if len(history) < 4:
        return None
    mu = statistics.fmean(history)
    sigma = statistics.pstdev(history)
    if sigma == 0:
        return None
    return (latest - mu) / sigma


def _sigmoid_0_100(x: float) -> float:
    """Map a roughly [-10, +10] health score to a 0–100 display scale."""
    return 100.0 / (1.0 + math.exp(-x / 3.0))


# ---------------------------------------------------------------------------
# Funding rate
# ---------------------------------------------------------------------------


@tool
def get_funding_rate(symbol: str) -> dict[str, Any]:
    """Latest perpetual-swap funding rate for a crypto asset, normalised + annualised.

    Funding rate is the periodic payment exchanged between longs and shorts on
    a perpetual contract to keep it pegged to spot. Perpetuals are >90% of all
    crypto derivatives volume, so this is the single most useful derivative
    signal: a positive rate means longs pay shorts (bullish/crowded-long),
    negative means shorts pay longs (bearish/crowded-short).

    Returns the raw rate, the rate normalised to an 8-hour equivalent, the
    annualised APY (the yield a delta-neutral "carry" position would harvest),
    and current open interest.

    Args:
        symbol: e.g. "BTC", "ETH", "SOL" (or "BTC-USD" — the base is used).
    """
    cache_key = f"funding:{(symbol or '').strip().upper()}"
    cached = cache_get(cache_key)
    if isinstance(cached, dict):
        return cached
    try:
        fr = cd.funding_rate(symbol)
    except CoinDeskError as exc:
        return err(str(exc), symbol=symbol)

    apy = fr["apy_pct"]
    bps = fr["rate_8h_bps"]
    direction_txt = {
        "longs_pay_shorts": "longs pay shorts (bullish positioning)",
        "shorts_pay_longs": "shorts pay longs (bearish positioning)",
        "neutral": "balanced",
    }.get(fr["direction"], fr["direction"])

    result = ok(
        raw_value=fr["rate_8h"],
        formatted_value=f"{bps:+.2f} bps / 8h  ·  {format_pct(apy)} APY",
        formula="r_8h = r_h × (8/h);  APY% = r_8h × 10000 × 3 × 365 / 100",
        explanation=(
            f"{fr['symbol']} perpetual funding on {fr['market']}: "
            f"{bps:+.2f} bps per 8h → {direction_txt}. "
            f"A persistent rate at this level annualises to {format_pct(apy)}."
        ),
        ui_type="metric",
        data={
            "symbol": fr["symbol"],
            "market": fr["market"],
            "raw_rate": fr["raw_rate"],
            "interval_hours": fr["interval_hours"],
            "rate_8h_bps": bps,
            "apy_pct": apy,
            "open_interest": fr["open_interest"],
            "direction": fr["direction"],
        },
        source="coindesk",
    )
    cache_set(cache_key, result)
    return result


@tool
def get_open_interest(symbol: str) -> dict[str, Any]:
    """Current open interest and its recent trend for a crypto perpetual.

    Open interest (OI) is the total value of outstanding derivative contracts.
    Rising OI = new capital entering (trend confirmation); falling OI = capital
    leaving (trend exhaustion). Reports current OI plus its 24h and 7d change.

    Args:
        symbol: e.g. "BTC", "ETH", "SOL".
    """
    cache_key = f"oi:{(symbol or '').strip().upper()}"
    cached = cache_get(cache_key)
    if isinstance(cached, dict):
        return cached
    try:
        hist = cd.open_interest_history(symbol, days=10)
    except CoinDeskError as exc:
        return err(str(exc), symbol=symbol)
    if not hist:
        return err(f"No open-interest history for {symbol}", symbol=symbol)

    closes = [r["close"] for r in hist]  # newest-first
    current = closes[0]
    chg_24h = ((current / closes[1] - 1) * 100) if len(closes) > 1 and closes[1] else None
    chg_7d = ((current / closes[7] - 1) * 100) if len(closes) > 7 and closes[7] else None

    result = ok(
        raw_value=current,
        formatted_value=f"{cd._fmt_money(current)} OI"
        + (f"  ·  24h {format_pct(chg_24h)}" if chg_24h is not None else ""),
        explanation=(
            f"{cd._symbol(symbol)} open interest is {cd._fmt_money(current)}"
            + (f", {format_pct(chg_24h)} vs 24h ago" if chg_24h is not None else "")
            + (f", {format_pct(chg_7d)} vs 7d ago" if chg_7d is not None else "")
            + ". Rising OI confirms a trend; falling OI signals positions unwinding."
        ),
        ui_type="metric",
        data={
            "symbol": cd._symbol(symbol),
            "open_interest": current,
            "change_24h_pct": round(chg_24h, 2) if chg_24h is not None else None,
            "change_7d_pct": round(chg_7d, 2) if chg_7d is not None else None,
        },
        source="coindesk",
    )
    cache_set(cache_key, result)
    return result


# ---------------------------------------------------------------------------
# Derivatives health score
# ---------------------------------------------------------------------------


def _basis_series(symbol: str, days: int) -> list[float]:
    """Newest-first basis series: (futures_close − index_close) / index_close.

    Pairs daily perpetual-futures closes with daily index closes by date.
    """
    fut = cd.futures_history(symbol, days=days)
    idx = cd.coin_history(symbol, days=days)
    idx_by_date = {r["date"]: r["close"] for r in idx if r.get("close")}
    out: list[tuple[str, float]] = []
    for r in fut:
        spot = idx_by_date.get(r["date"])
        if spot and r.get("close"):
            out.append((r["date"], (r["close"] - spot) / spot))
    out.sort(key=lambda t: t[0], reverse=True)
    return [v for _, v in out]


@tool
def get_crypto_derivatives_health(symbol: str) -> dict[str, Any]:
    """Derivatives-aware health score (0–100) for a crypto asset.

    Combines three standardised (rolling Z-score) signals:
      • Basis (+30%): futures premium over spot. Positive = healthy bullish demand.
      • OI trend (+40%): change in open interest. Positive = new capital entering.
      • Funding rate (−30%): subtracted, because an aggressively high funding
        rate means over-leveraged longs paying a steep premium → crash risk.

    Raw score = 0.30·Z_basis + 0.40·Z_ΔOI − 0.30·Z_funding, mapped to 0–100 via
    a logistic curve. >60 = constructive, 40–60 = neutral, <40 = fragile.

    Args:
        symbol: e.g. "BTC", "ETH", "SOL".
    """
    cache_key = f"deriv_health:{(symbol or '').strip().upper()}"
    cached = cache_get(cache_key)
    if isinstance(cached, dict):
        return cached

    try:
        funding_hist = cd.funding_rate_history(symbol, days=_Z_WINDOW + 5)
        oi_hist = cd.open_interest_history(symbol, days=_Z_WINDOW + 5)
        basis_hist = _basis_series(symbol, days=_Z_WINDOW + 5)
    except CoinDeskError as exc:
        return err(str(exc), symbol=symbol)

    # Funding Z-score (newest-first rate series).
    z_fr = _zscore_latest([r["close"] for r in funding_hist])

    # OI-trend Z-score: standardise the latest daily ΔOI against its history.
    oi_closes = [r["close"] for r in oi_hist]  # newest-first
    d_oi: list[float] = [
        (oi_closes[i] - oi_closes[i + 1]) / oi_closes[i + 1]
        for i in range(len(oi_closes) - 1)
        if oi_closes[i + 1]
    ]
    z_doi = _zscore_latest(d_oi)

    # Basis Z-score.
    z_basis = _zscore_latest(basis_hist)

    missing = [n for n, z in (("basis", z_basis), ("oi_trend", z_doi), ("funding", z_fr)) if z is None]
    if z_fr is None and z_doi is None and z_basis is None:
        return err(
            f"Insufficient derivatives history to score {cd._symbol(symbol)}",
            symbol=symbol,
        )

    zb = z_basis or 0.0
    zo = z_doi or 0.0
    zf = z_fr or 0.0
    raw = 0.30 * zb + 0.40 * zo - 0.30 * zf
    score_0_100 = _sigmoid_0_100(raw)

    if score_0_100 >= 60:
        verdict = "constructive"
    elif score_0_100 >= 40:
        verdict = "neutral"
    else:
        verdict = "fragile"

    result = ok(
        raw_value=round(score_0_100, 1),
        formatted_value=f"{score_0_100:.0f}/100 ({verdict})",
        formula="0.30·Z_basis + 0.40·Z_ΔOI − 0.30·Z_funding → logistic → 0–100",
        explanation=(
            f"{cd._symbol(symbol)} derivatives health {score_0_100:.0f}/100 ({verdict}). "
            f"Z(basis)={zb:+.2f}, Z(ΔOI)={zo:+.2f}, Z(funding)={zf:+.2f}. "
            "High funding drags the score because crowded leverage raises crash risk."
            + (f" Note: {', '.join(missing)} unavailable, treated as neutral." if missing else "")
        ),
        ui_type="metric",
        data={
            "symbol": cd._symbol(symbol),
            "score": round(score_0_100, 1),
            "verdict": verdict,
            "raw_score": round(raw, 3),
            "z_basis": round(zb, 3),
            "z_oi_trend": round(zo, 3),
            "z_funding": round(zf, 3),
            "unavailable": missing,
        },
        source="coindesk",
    )
    cache_set(cache_key, result)
    return result


# ---------------------------------------------------------------------------
# Squeeze-risk interpretation matrix
# ---------------------------------------------------------------------------


@tool
def get_squeeze_risk(symbol: str) -> dict[str, Any]:
    """Classify funding-rate × open-interest positioning into a squeeze-risk signal.

    Uses rolling Z-scores of open-interest trend (Z_ΔOI) and funding rate
    (Z_FR) and a 2×2 interpretation matrix:

      • Crowded longs / long-squeeze risk: Z_ΔOI > 1.5 AND Z_FR > 1.5 →
        leveraged longs piling in; a small drop can cascade liquidations down.
      • Crowded shorts / short-squeeze risk: Z_ΔOI > 1.5 AND Z_FR < −1.5 →
        aggressive shorts; a small rally can force a violent buy-back spike.
      • Healthy spot-driven trend: Z_ΔOI > 1.0 AND |Z_FR| ≤ 1.0 → real demand.
      • Trend exhaustion / capital flight: Z_ΔOI < −1.5 → positions unwinding.

    Args:
        symbol: e.g. "BTC", "ETH", "SOL".
    """
    cache_key = f"squeeze:{(symbol or '').strip().upper()}"
    cached = cache_get(cache_key)
    if isinstance(cached, dict):
        return cached

    try:
        funding_hist = cd.funding_rate_history(symbol, days=_Z_WINDOW + 5)
        oi_hist = cd.open_interest_history(symbol, days=_Z_WINDOW + 5)
    except CoinDeskError as exc:
        return err(str(exc), symbol=symbol)

    z_fr = _zscore_latest([r["close"] for r in funding_hist])
    oi_closes = [r["close"] for r in oi_hist]
    d_oi = [
        (oi_closes[i] - oi_closes[i + 1]) / oi_closes[i + 1]
        for i in range(len(oi_closes) - 1)
        if oi_closes[i + 1]
    ]
    z_doi = _zscore_latest(d_oi)

    if z_fr is None or z_doi is None:
        return err(
            f"Insufficient derivatives history to assess squeeze risk for {cd._symbol(symbol)}",
            symbol=symbol,
        )

    if z_doi < -_Z_EXTREME:
        signal = "trend_exhaustion"
        label = "Trend exhaustion / capital flight"
        detail = (
            "Open interest is collapsing — positions are being closed and "
            "liquidity is leaving. A rising price here is likely short-covering, "
            "not new buyers, and prone to reversal."
        )
        risk = "elevated"
    elif z_doi > _Z_EXTREME and z_fr > _Z_EXTREME:
        signal = "long_squeeze_risk"
        label = "Crowded longs / long-squeeze risk"
        detail = (
            "OI is surging while funding is steeply positive: new capital is "
            "almost all leveraged longs paying a premium. A minor drop can "
            "trigger cascading long liquidations."
        )
        risk = "high"
    elif z_doi > _Z_EXTREME and z_fr < -_Z_EXTREME:
        signal = "short_squeeze_risk"
        label = "Crowded shorts / short-squeeze risk"
        detail = (
            "OI is surging while funding is deeply negative: the market is "
            "aggressively short. A small rally can force shorts to buy back, "
            "causing a violent upward spike."
        )
        risk = "high"
    elif z_doi > _Z_TREND and abs(z_fr) <= _Z_TREND:
        signal = "healthy_trend"
        label = "Healthy spot-driven trend"
        detail = (
            "Capital is entering (OI rising) while funding stays near baseline — "
            "the move is driven by structural spot demand, not excess leverage."
        )
        risk = "low"
    else:
        signal = "neutral"
        label = "Neutral positioning"
        detail = "No extreme crowding in funding or open interest right now."
        risk = "low"

    result = ok(
        raw_value=signal,
        formatted_value=f"{label} (risk: {risk})",
        formula="2×2 matrix on Z_ΔOI and Z_FR with θ=1.5 (extreme), 1.0 (trend)",
        explanation=(
            f"{cd._symbol(symbol)}: {label}. Z(ΔOI)={z_doi:+.2f}, "
            f"Z(funding)={z_fr:+.2f}. {detail}"
        ),
        ui_type="metric",
        data={
            "symbol": cd._symbol(symbol),
            "signal": signal,
            "label": label,
            "risk_level": risk,
            "z_oi_trend": round(z_doi, 3),
            "z_funding": round(z_fr, 3),
        },
        source="coindesk",
    )
    cache_set(cache_key, result)
    return result
