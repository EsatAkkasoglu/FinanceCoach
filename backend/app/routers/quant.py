"""Quant Lab routes — full-resolution access to the ``app/quant`` layer.

The chat tools in ``app/tools/quant_tools.py`` downsample aggressively to fit
the 4000-character SSE cap. The Quant Lab page has no such constraint, so these
endpoints return the whole equity curve, the whole frontier, and every
walk-forward fold.

Endpoints:
    POST /quant/backtest   — run a strategy, optionally with walk-forward validation
    POST /quant/optimize   — efficient frontier + optimal weights for real holdings
    GET  /quant/risk       — VaR / CVaR / beta for the user's portfolio
    GET  /quant/strategies — the strategy catalogue the UI builds its picker from

Every route degrades to a 200 with ``ok: false``. An unhandled exception would
be rendered by Starlette's outermost error middleware — *outside* the CORS
layer — so the browser would report a misleading CORS failure instead of the
real one.
"""
from __future__ import annotations

import logging
import math
from typing import Any

import numpy as np
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.auth import get_current_user_id
from app.quant import backtest as bt
from app.quant import risk as rk
from app.quant.data import to_returns
from app.tools.quant_tools import (
    _MIN_BARS,
    _TRADING_DAYS,
    _asset_class_for,
    _clean_ticker,
    _load_path,
    _portfolio_returns,
    optimize_portfolio,
)

log = logging.getLogger("fincoach.quant")
router = APIRouter(prefix="/quant", tags=["quant"])

#: The page can render far more than chat can carry, but an unbounded curve is
#: still a bad idea over the wire. 10 years of daily bars fits comfortably.
_MAX_PAGE_POINTS = 3000


def _json_safe(obj: Any) -> Any:
    """NaN/Infinity → None, numpy scalars → Python. Same reason as insights.py:
    Starlette serializes with ``allow_nan=False`` at render time, after the
    route has already returned."""
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, float | np.floating):
        v = float(obj)
        return v if math.isfinite(v) else None
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple | np.ndarray):
        return [_json_safe(v) for v in obj]
    return obj


def _guard(label: str, run):
    try:
        return _json_safe(run())
    except Exception as exc:  # noqa: BLE001 — never surface a raw 500 (bypasses CORS)
        log.warning("quant %s failed: %s", label, exc, exc_info=True)
        return {"ok": False, "error": str(exc)}


def _series(values: np.ndarray, digits: int = 6) -> list[float]:
    from app.quant.data import downsample  # noqa: PLC0415

    thinned, _ = downsample(np.asarray(values, dtype=float), _MAX_PAGE_POINTS)
    return [round(float(x), digits) for x in thinned]


# ── requests ─────────────────────────────────────────────────────────────────


class BacktestRequest(BaseModel):
    ticker: str
    strategy: str = "sma_cross"
    period_days: int = Field(default=730, ge=90, le=3650)
    fast: int = Field(default=0, ge=0, le=400)
    slow: int = Field(default=0, ge=0, le=400)
    lookback: int = Field(default=0, ge=0, le=400)
    fee_bps: float = Field(default=10.0, ge=0.0, le=500.0)
    slippage_bps: float = Field(default=5.0, ge=0.0, le=500.0)
    allow_short: bool = False
    walk_forward: bool = True


class OptimizeRequest(BaseModel):
    objective: str = "max_sharpe"
    period_days: int = Field(default=365, ge=90, le=1825)
    long_only: bool = True
    max_weight_pct: float = Field(default=0.0, ge=0.0, le=100.0)


# ── routes ───────────────────────────────────────────────────────────────────


@router.get("/strategies")
def strategies(user_id: int = Depends(get_current_user_id)) -> dict[str, Any]:
    """Strategy catalogue + the parameter grid each one searches."""
    return {
        "ok": True,
        "strategies": [
            {
                "key": name,
                "grid": bt.PARAM_GRIDS.get(name, {}),
                "n_combinations": max(
                    1,
                    int(np.prod([len(v) for v in bt.PARAM_GRIDS.get(name, {}).values()] or [1])),
                ),
            }
            for name in sorted(bt.SIGNALS)
        ],
    }


@router.post("/backtest")
def run_backtest_route(
    req: BacktestRequest, user_id: int = Depends(get_current_user_id)
) -> dict[str, Any]:
    """Full-resolution backtest: equity curve, drawdown, metrics, folds."""

    def _run() -> dict[str, Any]:
        ticker = _clean_ticker(req.ticker)
        if not ticker:
            return {"ok": False, "error": "A ticker is required."}
        if req.strategy not in bt.SIGNALS:
            return {"ok": False, "error": f"Unknown strategy '{req.strategy}'."}

        path = _load_path(ticker, req.period_days)
        if path is None:
            return {"ok": False, "error": f"No usable price history for {ticker}."}
        dates, closes, highs, lows = path
        if closes.size < _MIN_BARS:
            return {
                "ok": False,
                "error": f"Only {closes.size} bars for {ticker} — need at least {_MIN_BARS}.",
            }

        from app.tools.quant_tools import _params_for  # noqa: PLC0415

        params = _params_for(req.strategy, req.fast, req.slow, req.lookback)
        raw, warmup = bt.build_positions(
            req.strategy, closes, highs, lows, params, allow_short=req.allow_short
        )
        costs = bt.Costs(fee_bps=req.fee_bps, slippage_bps=req.slippage_bps)
        res = bt.run_backtest(closes, raw, costs=costs, warmup=warmup, dates=dates)
        if res.bar_returns.size < 2:
            return {
                "ok": False,
                "error": (
                    f"Not enough history after the {warmup}-bar warm-up "
                    f"for {req.strategy} on {ticker}."
                ),
            }

        wf = None
        if req.walk_forward:
            wf = bt.walk_forward(
                closes, req.strategy, highs=highs, lows=lows,
                costs=costs, ppy=_TRADING_DAYS,
            )

        from app.quant.data import downsample  # noqa: PLC0415

        _thinned, idx = downsample(res.equity, _MAX_PAGE_POINTS)
        return {
            "ok": True,
            "ticker": ticker,
            "strategy": req.strategy,
            "params": params,
            "costs": {"fee_bps": req.fee_bps, "slippage_bps": req.slippage_bps},
            "dates": [res.dates[i] for i in idx] if res.dates else [],
            "equity": _series(res.equity),
            "benchmark": _series(res.benchmark_equity),
            "drawdown": _series(res.drawdown * 100.0, digits=4),
            "positions": _series(res.positions, digits=2),
            "metrics": bt.summarize(res, ppy=_TRADING_DAYS, n_trials=1),
            "walk_forward": wf,
        }

    return _guard("backtest", _run)


@router.post("/optimize")
def optimize_route(
    req: OptimizeRequest, user_id: int = Depends(get_current_user_id)
) -> dict[str, Any]:
    """Efficient frontier + optimal weights over the user's real holdings.

    Delegates to the same tool the chat agent calls, so the page and the
    conversation can never disagree about the numbers.
    """

    def _run() -> dict[str, Any]:
        env = optimize_portfolio.invoke({
            "objective": req.objective,
            "period_days": req.period_days,
            "long_only": req.long_only,
            "max_weight_pct": req.max_weight_pct,
        })
        if not env.get("ok"):
            return {"ok": False, "error": env.get("error", "optimization failed")}
        return {
            "ok": True,
            "explanation": env.get("explanation"),
            "formatted_value": env.get("formatted_value"),
            **env.get("data", {}),
        }

    return _guard("optimize", _run)


@router.get("/risk")
def risk_route(
    period_days: int = Query(365, ge=60, le=1825),
    confidence: float = Query(0.95, ge=0.80, le=0.999),
    benchmark: str = Query("SPY"),
    user_id: int = Depends(get_current_user_id),
) -> dict[str, Any]:
    """Tail risk and benchmark statistics for the user's portfolio."""

    def _run() -> dict[str, Any]:
        built = _portfolio_returns(period_days)
        if built is None:
            return {
                "ok": False,
                "error": "No priced holdings with enough shared history to measure risk.",
            }
        returns, weights, currency = built
        if returns.size < _MIN_BARS:
            return {"ok": False, "error": f"Only {returns.size} shared observations."}

        bench_stats, caps = None, None
        b = _clean_ticker(benchmark) or "SPY"
        from app.quant.data import load_close_series  # noqa: PLC0415

        loaded = load_close_series(_asset_class_for(b), b, period_days)
        if loaded:
            bench_returns = to_returns(loaded[1])
            n = min(returns.size, bench_returns.size)
            if n >= _MIN_BARS:
                bench_stats = rk.beta_alpha(returns[-n:], bench_returns[-n:], ppy=_TRADING_DAYS)
                caps = rk.capture_ratios(returns[-n:], bench_returns[-n:])

        dd = rk.rolling_drawdown(returns)
        return {
            "ok": True,
            "currency": currency,
            "n_obs": int(returns.size),
            "confidence": confidence,
            "weights": weights,
            "var_pct": round((rk.historical_var(returns, confidence) or 0.0) * 100.0, 3),
            "cvar_pct": round((rk.historical_cvar(returns, confidence) or 0.0) * 100.0, 3),
            "cornish_fisher_var_pct": (
                lambda v: round(v * 100.0, 3) if v is not None else None
            )(rk.cornish_fisher_var(returns, confidence)),
            "ewma_vol_pct": (
                lambda v: round(v * 100.0, 3) if v is not None else None
            )(rk.ewma_vol(returns, ppy=_TRADING_DAYS)),
            "worst_day_pct": round(float(returns.min()) * 100.0, 3),
            "max_drawdown_pct": round(float(dd.min()) * 100.0, 3),
            "drawdown_curve": _series(dd * 100.0, digits=3),
            "benchmark": b,
            "benchmark_stats": bench_stats,
            "capture": caps,
        }

    return _guard("risk", _run)
