"""Price-series loading and alignment for the quant layer.

The one place that turns the app's three heterogeneous price sources into the
oldest-first numpy arrays every model in this package expects:

  * TEFAS fund NAV  → ``fund_tools.get_fund_history`` (``[{date, price}]``)
  * everything else → ``yfinance_service.history`` (OHLCV, **newest first**)

Crypto rides the yfinance path via its pair symbol (``BTC-USD``); the CoinDesk
service is candle/derivative-oriented and is used by the short-term signal
engine, not here.

This module also owns :func:`close_map`, which used to live in
``app/tools/calc_tools.py`` as ``_holding_close_series``. It moved here so the
backtester and ``analyze_portfolio_risk`` share one loader instead of two.
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np

import app.services.yfinance_service as yf_svc
from app.tools.fund_tools import get_fund_history

log = logging.getLogger("fincoach.quant.data")

# yfinance only accepts a fixed set of period strings. The old ladder in
# calc_tools stopped at "2y", which silently capped every lookback — a
# 5-year backtest quietly became a 2-year one. These rungs go the distance.
_PERIOD_LADDER: tuple[tuple[int, str], ...] = (
    (35, "1mo"),
    (95, "3mo"),
    (190, "6mo"),
    (370, "1y"),
    (740, "2y"),
    (1850, "5y"),
    (3700, "10y"),
)


def yf_period(days: int) -> str:
    """Smallest yfinance period string that covers ``days``."""
    for limit, period in _PERIOD_LADDER:
        if days <= limit:
            return period
    return "max"


def close_map(asset_class: str, ticker: str, days: int) -> dict[str, float] | None:
    """Best-effort ``{date: close}`` for one holding's native-currency price.

    Returns None if it can't be fetched (the caller then excludes the holding).
    """
    try:
        if asset_class == "fund":
            rows = get_fund_history.invoke({"code": ticker, "days": days})
            return {r["date"]: float(r["price"]) for r in rows if r.get("price")}
        rows = yf_svc.history(ticker, period=yf_period(days))
        return {r["date"]: float(r["close"]) for r in rows if r.get("close")}
    except Exception as exc:  # noqa: BLE001 — a missing series must not crash a calc
        log.info("quant.data: history fetch failed for %s: %s", ticker, exc)
        return None


def load_close_series(
    asset_class: str, ticker: str, days: int
) -> tuple[list[str], np.ndarray] | None:
    """Oldest-first ``(dates, closes)`` for one instrument.

    ``close_map`` returns an unordered mapping (yfinance hands back newest-first
    rows); every model here assumes chronological order, so sort explicitly.
    """
    m = close_map(asset_class, ticker, days)
    if not m or len(m) < 2:
        return None
    dates = sorted(m)
    closes = np.asarray([m[d] for d in dates], dtype=float)
    if not np.all(np.isfinite(closes)) or np.any(closes <= 0):
        return None
    return dates, closes


def load_ohlc_series(ticker: str, days: int) -> dict[str, Any] | None:
    """Oldest-first OHLC for a yfinance-priced instrument.

    Needed by the range-based strategies (Donchian, ATR stops) that can't work
    from closes alone. Funds have no intraday range on TEFAS, so this is
    yfinance-only and returns None for anything it can't fetch.
    """
    try:
        rows = yf_svc.history(ticker, period=yf_period(days))
    except Exception as exc:  # noqa: BLE001
        log.info("quant.data: OHLC fetch failed for %s: %s", ticker, exc)
        return None
    usable = [
        r for r in rows
        if r.get("close") and r.get("high") is not None and r.get("low") is not None
    ]
    if len(usable) < 2:
        return None
    usable.sort(key=lambda r: r["date"])  # yfinance_service returns newest-first
    return {
        "dates": [str(r["date"]) for r in usable],
        "closes": np.asarray([float(r["close"]) for r in usable], dtype=float),
        "highs": np.asarray([float(r["high"]) for r in usable], dtype=float),
        "lows": np.asarray([float(r["low"]) for r in usable], dtype=float),
    }


def align_series(
    series: dict[str, dict[str, float]]
) -> tuple[list[str], dict[str, np.ndarray]]:
    """Intersect several ``{date: close}`` maps onto their common dates.

    Mirrors the intersection ``analyze_portfolio_risk`` does inline, so a
    multi-asset covariance is always built from genuinely contemporaneous bars
    (a holiday in one market must not shift another asset's return by a day).

    Returns ``([], {})`` when there is no usable overlap.
    """
    usable = {k: v for k, v in series.items() if v}
    if not usable:
        return [], {}
    common = set.intersection(*(set(v) for v in usable.values()))
    if len(common) < 2:
        return [], {}
    dates = sorted(common)
    return dates, {k: np.asarray([v[d] for d in dates], dtype=float) for k, v in usable.items()}


def to_returns(closes: np.ndarray) -> np.ndarray:
    """Simple period returns from an oldest-first price series."""
    p = np.asarray(closes, dtype=float)
    if p.size < 2 or np.any(p[:-1] == 0):
        return np.asarray([], dtype=float)
    return p[1:] / p[:-1] - 1.0


def downsample(values: np.ndarray, max_points: int) -> tuple[np.ndarray, list[int]]:
    """Evenly thin a series to at most ``max_points``, always keeping both ends.

    Used to fit an equity curve inside the 4000-character cap that
    ``main._summarize_tool_output`` imposes on every tool result before it
    reaches the UI. Returns the thinned values and the indices they came from.
    """
    n = int(values.size)
    if max_points < 2 or n <= max_points:
        return values, list(range(n))
    idx = np.unique(np.linspace(0, n - 1, max_points).round().astype(int))
    return values[idx], [int(i) for i in idx]
