"""Quant tools — the ``@tool`` surface over ``app/quant``.

Same contract as ``calc_tools``: the math happens in Python, the envelope
carries an already-formatted headline the LLM is told to quote verbatim, and
``ui_type`` tells the frontend which card to draw. Nothing here computes a
metric itself — it loads data, calls ``app.quant``, and shapes the result.

Payload discipline: ``main._summarize_tool_output`` truncates every tool result
at 4000 characters before it reaches the UI, and ``parseToolResult.ts``
degrades a truncated envelope to plain text *silently*. So curves are
downsampled to :data:`_MAX_CURVE_POINTS` and emitted as flat float arrays
rather than arrays of objects. The full-resolution series lives behind
``/quant/*`` for the Quant Lab page.
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
from langchain_core.tools import tool

from app.auth import get_display_currency
from app.quant import backtest as bt
from app.quant import optimize as opt
from app.quant import risk as rk
from app.quant.data import align_series, close_map, load_close_series, load_ohlc_series, to_returns
from app.quant.options import bs_greeks, bs_price, implied_vol
from app.tools._calc_result import err, format_number, format_pct, ok

# Reused rather than re-derived: valuation (FX + live quotes) and the fund-code
# heuristic already live in calc_tools and must stay single-sourced.
from app.tools.calc_tools import _looks_like_fund_code, _valued_holdings

log = logging.getLogger("fincoach.tools.quant")

_MAX_CURVE_POINTS = 80      # keeps the envelope under the 4000-char SSE cap
_TRADING_DAYS = 252.0
_MIN_BARS = 40


def _asset_class_for(ticker: str) -> str:
    return "fund" if _looks_like_fund_code(ticker) else "stock"


def _clean_ticker(ticker: str) -> str:
    return (ticker or "").strip().upper()


def _curve(values: np.ndarray, digits: int = 4) -> list[float]:
    thinned, _ = bt_downsample(values)
    return [round(float(x), digits) for x in thinned]


def bt_downsample(values: np.ndarray) -> tuple[np.ndarray, list[int]]:
    from app.quant.data import downsample  # noqa: PLC0415 — avoid a cycle at import time

    return downsample(values, _MAX_CURVE_POINTS)


def _portfolio_returns(period_days: int) -> tuple[np.ndarray, list[dict[str, Any]], str] | None:
    """Value-weighted return series for the user's real holdings.

    Mirrors ``analyze_portfolio_risk``: price every non-cash holding, intersect
    onto common trading days, and weight by current value. Returns None when
    there isn't enough overlapping history to say anything.
    """
    ccy = get_display_currency() or "USD"
    valued, _total, _cost, _fx = _valued_holdings(ccy)
    non_cash = [r for r in valued if r["asset_class"] != "cash" and r["value"] > 0]
    if not non_cash:
        return None

    series: dict[str, dict[str, float]] = {}
    for r in non_cash:
        s = close_map(r["asset_class"], r["ticker"], period_days)
        if s and len(s) > 2:
            series[r["ticker"]] = s
    if not series:
        return None

    dates, aligned = align_series(series)
    if len(dates) < _MIN_BARS:
        return None

    total = sum(r["value"] for r in non_cash if r["ticker"] in aligned)
    if total <= 0:
        return None
    weights, matrix = [], []
    rows: list[dict[str, Any]] = []
    for r in non_cash:
        t = r["ticker"]
        if t not in aligned:
            continue
        w = r["value"] / total
        weights.append(w)
        matrix.append(to_returns(aligned[t]))
        rows.append({"label": t, "value": round(w * 100.0, 2)})
    if not matrix:
        return None
    port = np.asarray(weights, dtype=float) @ np.vstack(matrix)
    return port, rows, ccy


# ─────────────────────────────────────────────────────────────────────────────
# Backtesting
# ─────────────────────────────────────────────────────────────────────────────


_STRATEGY_PARAMS: dict[str, tuple[str, ...]] = {
    "sma_cross": ("fast", "slow"),
    "ema_cross": ("fast", "slow"),
    "macd": ("fast", "slow"),
    "rsi_reversion": ("period",),
    "tsmom": ("lookback",),
    "donchian": ("lookback",),
    "buy_hold": (),
}


def _params_for(strategy: str, fast: int, slow: int, lookback: int) -> dict[str, Any]:
    """Map the flat tool arguments onto the strategy's own parameter names.

    A single flat signature keeps the tool callable by an LLM; 0 means
    "use the strategy default".
    """
    supplied = {"fast": fast, "slow": slow, "lookback": lookback, "period": lookback}
    return {
        name: supplied[name]
        for name in _STRATEGY_PARAMS.get(strategy, ())
        if supplied.get(name, 0) and supplied[name] > 0
    }


def _load_path(ticker: str, period_days: int) -> tuple[list[str], np.ndarray, np.ndarray | None, np.ndarray | None] | None:
    asset_class = _asset_class_for(ticker)
    if asset_class != "fund":
        ohlc = load_ohlc_series(ticker, period_days)
        if ohlc:
            return ohlc["dates"], ohlc["closes"], ohlc["highs"], ohlc["lows"]
    loaded = load_close_series(asset_class, ticker, period_days)
    if not loaded:
        return None
    dates, closes = loaded
    return dates, closes, None, None


@tool
def backtest_strategy(
    ticker: str,
    strategy: str = "sma_cross",
    period_days: int = 730,
    fast: int = 0,
    slow: int = 0,
    lookback: int = 0,
    fee_bps: float = 10.0,
    slippage_bps: float = 5.0,
    allow_short: bool = False,
) -> dict[str, Any]:
    """Backtest a rule-based strategy on one instrument's real price history.

    Runs the rule bar by bar with NO look-ahead (each signal is traded on the
    NEXT bar), charges fees and slippage on every position change, and reports
    risk-adjusted results next to buy & hold. Use for "what would X have done",
    "is this moving-average strategy any good", "test RSI on BTC".

    This is a single-instrument, bar-close simulation of the PAST. It is not a
    prediction and not advice.

    Args:
        ticker: instrument symbol (AAPL, BTC-USD, THB for a TEFAS fund code).
        strategy: sma_cross, ema_cross, macd, rsi_reversion, tsmom, donchian, buy_hold.
        period_days: lookback window in days (90–3650; default 730).
        fast: fast moving-average length (0 = strategy default).
        slow: slow moving-average length (0 = strategy default).
        lookback: lookback/period for tsmom, donchian and rsi_reversion (0 = default).
        fee_bps: commission per position change, in basis points.
        slippage_bps: assumed slippage per position change, in basis points.
        allow_short: if true, the flat leg becomes a short instead of cash.
    """
    t = _clean_ticker(ticker)
    if not t:
        return err("A ticker is required.", ticker=ticker)
    if strategy not in bt.SIGNALS:
        return err(
            f"Unknown strategy '{strategy}'. Available: {', '.join(sorted(bt.SIGNALS))}.",
            strategy=strategy,
        )
    period_days = max(90, min(int(period_days), 3650))

    path = _load_path(t, period_days)
    if path is None:
        return err(f"No usable price history for {t}.", ticker=t, period_days=period_days)
    dates, closes, highs, lows = path
    if closes.size < _MIN_BARS:
        return err(
            f"Only {closes.size} bars of history for {t} — need at least {_MIN_BARS}.",
            ticker=t,
        )

    params = _params_for(strategy, fast, slow, lookback)
    try:
        raw, warmup = bt.build_positions(strategy, closes, highs, lows, params, allow_short=allow_short)
    except KeyError:
        return err(f"Unknown strategy '{strategy}'.", strategy=strategy)

    costs = bt.Costs(fee_bps=max(0.0, fee_bps), slippage_bps=max(0.0, slippage_bps))
    res = bt.run_backtest(closes, raw, costs=costs, warmup=warmup, dates=dates)
    if res.bar_returns.size < 2:
        return err(
            f"Not enough history left after the {warmup}-bar warm-up for {strategy} on {t}.",
            ticker=t, strategy=strategy,
        )

    summary = bt.summarize(res, ppy=_TRADING_DAYS, n_trials=1)
    total = summary["total_return_pct"]
    bench = summary["benchmark_return_pct"]

    return ok(
        raw_value=total,
        formatted_value=f"{format_pct(total, 1)} vs {format_pct(bench, 1)} buy & hold",
        formula="net_r = position × asset_return − |Δposition| × (fee + slippage)",
        explanation=(
            f"{strategy} on {t}, {res.bar_returns.size} bars"
            f"{' (' + res.dates[0] + ' → ' + res.dates[-1] + ')' if res.dates else ''}. "
            f"Signals are traded on the following bar (no look-ahead). "
            f"Costs: {fee_bps:.0f}bps fee + {slippage_bps:.0f}bps slippage per position change, "
            f"{res.n_trades} changes, {format_pct(summary['cost_drag_pct'], 2)} total cost drag. "
            f"Annualised Sharpe {format_number(summary['sharpe_annualized'])}, "
            f"max drawdown {format_pct(summary['max_drawdown_pct'], 1)}. "
            "Past performance of a single surviving ticker; not a prediction and not advice."
        ),
        ui_type="equity_curve",
        data={
            "ticker": t,
            "strategy": strategy,
            "params": params,
            "start_date": res.dates[0] if res.dates else None,
            "end_date": res.dates[-1] if res.dates else None,
            "points": min(res.equity.size, _MAX_CURVE_POINTS),
            "equity": _curve(res.equity),
            "benchmark": _curve(res.benchmark_equity),
            "drawdown": _curve(res.drawdown * 100.0, digits=2),
            "metrics": summary,
        },
    )


@tool
def walk_forward_backtest(
    ticker: str,
    strategy: str = "sma_cross",
    period_days: int = 1825,
    fee_bps: float = 10.0,
    slippage_bps: float = 5.0,
) -> dict[str, Any]:
    """Out-of-sample validation of a strategy: tune on the past, score on the future.

    Searches the strategy's parameter grid on each expanding training window,
    applies the winner UNCHANGED to the next block, and reports only those
    out-of-sample returns. The Sharpe is deflated for the number of parameter
    combinations tested, which is the honest correction for "I tried 40 things
    and kept the best one". Use when someone asks whether a backtest result is
    real or curve-fitted.

    Args:
        ticker: instrument symbol.
        strategy: sma_cross, ema_cross, macd, rsi_reversion, tsmom, donchian.
        period_days: lookback window in days (365–3650; longer is much better here).
        fee_bps: commission per position change, in basis points.
        slippage_bps: assumed slippage per position change, in basis points.
    """
    t = _clean_ticker(ticker)
    if not t:
        return err("A ticker is required.", ticker=ticker)
    if strategy not in bt.SIGNALS:
        return err(
            f"Unknown strategy '{strategy}'. Available: {', '.join(sorted(bt.SIGNALS))}.",
            strategy=strategy,
        )
    period_days = max(365, min(int(period_days), 3650))

    path = _load_path(t, period_days)
    if path is None:
        return err(f"No usable price history for {t}.", ticker=t)
    dates, closes, highs, lows = path

    costs = bt.Costs(fee_bps=max(0.0, fee_bps), slippage_bps=max(0.0, slippage_bps))
    wf = bt.walk_forward(
        closes, strategy, highs=highs, lows=lows,
        costs=costs, ppy=_TRADING_DAYS,
    )
    if not wf.get("ok"):
        return err(
            f"Walk-forward validation not possible for {t}: {wf.get('reason')}. "
            "A longer history is needed before an out-of-sample claim can be made.",
            ticker=t, strategy=strategy, period_days=period_days,
        )

    rows = [
        {"metric": "Out-of-sample return", "value": wf["oos_return_pct"], "unit": "%"},
        {"metric": "OOS Sharpe (annualised)", "value": wf["oos_sharpe_annualized"]},
        {"metric": "OOS Sortino", "value": wf["oos_sortino"]},
        {"metric": "OOS max drawdown", "value": wf["oos_max_drawdown_pct"], "unit": "%"},
        {"metric": "Deflated Sharpe", "value": wf["oos_dsr"]},
        {"metric": "Parameter sets tried", "value": wf["n_trials"]},
        {"metric": "Folds", "value": wf["n_folds"]},
        {"metric": "OOS bars", "value": wf["oos_bars"]},
    ]
    dsr = wf["oos_dsr"]
    verdict = (
        "The deflated Sharpe stays positive after correcting for the search — the "
        "edge survives, on this sample."
        if dsr is not None and dsr > 0.5 else
        "The deflated Sharpe does NOT clear the multiple-testing bar — this result "
        "is consistent with having found the best of several random-looking rules."
    )

    return ok(
        raw_value=wf["oos_return_pct"],
        formatted_value=f"{format_pct(wf['oos_return_pct'], 1)} out-of-sample",
        formula="DSR = P(true Sharpe > E[max Sharpe of N trials])",
        explanation=(
            f"{strategy} on {t}: {wf['n_folds']} expanding folds, "
            f"{wf['embargo_bars']}-bar embargo between train and test, "
            f"{wf['n_trials']} parameter set(s) searched per fold. "
            f"Only out-of-sample blocks are counted. {verdict} "
            "Historical simulation on one surviving ticker; not advice."
        ),
        ui_type="table",
        data={"ticker": t, "strategy": strategy, "rows": rows, "folds": wf["folds"]},
    )


# ─────────────────────────────────────────────────────────────────────────────
# Risk
# ─────────────────────────────────────────────────────────────────────────────


@tool
def compute_value_at_risk(
    ticker: str = "",
    period_days: int = 365,
    confidence: float = 0.95,
) -> dict[str, Any]:
    """Value at Risk and expected shortfall — how bad a bad day gets.

    With no ticker this runs on the user's ACTUAL portfolio (value-weighted).
    Reports historical VaR, historical CVaR (the average loss on days that
    breached VaR) and a Cornish-Fisher VaR that adjusts for skew and fat tails.

    Use for "how much could I lose", "what's my downside", "how risky is this
    on a bad day". Losses are reported as positive percentages.

    Args:
        ticker: instrument symbol; leave empty for the whole portfolio.
        period_days: lookback window in days (60–1825).
        confidence: VaR confidence level between 0.80 and 0.999 (default 0.95).
    """
    period_days = max(60, min(int(period_days), 1825))
    confidence = float(min(max(confidence, 0.80), 0.999))
    t = _clean_ticker(ticker)

    if t:
        loaded = load_close_series(_asset_class_for(t), t, period_days)
        if not loaded:
            return err(f"No usable price history for {t}.", ticker=t)
        returns = to_returns(loaded[1])
        label = t
        weights: list[dict[str, Any]] = []
    else:
        built = _portfolio_returns(period_days)
        if built is None:
            return err(
                "No priced holdings with enough shared history to measure portfolio risk.",
                period_days=period_days,
            )
        returns, weights, _ccy = built
        label = "Portfolio"

    if returns.size < _MIN_BARS:
        return err(f"Only {returns.size} observations — need at least {_MIN_BARS}.", ticker=t)

    var = rk.historical_var(returns, confidence)
    cvar = rk.historical_cvar(returns, confidence)
    cf = rk.cornish_fisher_var(returns, confidence)
    vol = rk.ewma_vol(returns, ppy=_TRADING_DAYS)
    dd = rk.rolling_drawdown(returns)
    pct = round(confidence * 100.0, 1)

    rows = [
        {"metric": f"Historical VaR ({pct}%)", "value": round(var * 100.0, 2), "unit": "%"},
        {"metric": f"Expected shortfall ({pct}%)", "value": round(cvar * 100.0, 2), "unit": "%"},
        {"metric": "Cornish-Fisher VaR", "value": round(cf * 100.0, 2) if cf else None, "unit": "%"},
        {"metric": "EWMA volatility (annual)", "value": round(vol * 100.0, 2) if vol else None, "unit": "%"},
        {"metric": "Worst single day", "value": round(float(returns.min()) * 100.0, 2), "unit": "%"},
        {"metric": "Max drawdown", "value": round(float(dd.min()) * 100.0, 2), "unit": "%"},
        {"metric": "Observations", "value": int(returns.size)},
    ]

    return ok(
        raw_value=round(var * 100.0, 2),
        formatted_value=f"{format_pct(var * 100.0, 2)} 1-day VaR at {pct}%",
        formula=f"VaR = −percentile(returns, {round((1 - confidence) * 100, 1)}%)",
        explanation=(
            f"{label}: on the worst {round((1 - confidence) * 100, 1)}% of days over the last "
            f"{returns.size} observations, the loss exceeded {format_pct(var * 100.0, 2)}; "
            f"when it did, it averaged {format_pct(cvar * 100.0, 2)}. "
            "Historical VaR cannot see a loss bigger than the worst day in the window — "
            "it describes this sample, it does not forecast the tail."
        ),
        ui_type="table",
        data={"label": label, "rows": rows, "bars": weights[:12], "confidence": confidence},
    )


@tool
def compute_beta_alpha(
    ticker: str = "",
    benchmark: str = "SPY",
    period_days: int = 365,
) -> dict[str, Any]:
    """Beta, alpha and factor exposure against a benchmark.

    Regresses the instrument (or, with no ticker, the user's ACTUAL portfolio)
    on a benchmark: beta (market sensitivity), annualised Jensen's alpha, R²
    (how much is just the market), tracking error, and up/down capture.

    Use for "how correlated am I to the market", "what's my beta", "am I
    actually beating the index or just leveraged to it".

    Args:
        ticker: instrument symbol; leave empty for the whole portfolio.
        benchmark: benchmark symbol (default SPY).
        period_days: lookback window in days (90–1825).
    """
    period_days = max(90, min(int(period_days), 1825))
    t = _clean_ticker(ticker)
    b = _clean_ticker(benchmark) or "SPY"

    bench_loaded = load_close_series("stock", b, period_days)
    if not bench_loaded:
        return err(f"No usable price history for benchmark {b}.", benchmark=b)
    bench_map = {d: p for d, p in zip(bench_loaded[0], bench_loaded[1], strict=True)}

    if t:
        loaded = load_close_series(_asset_class_for(t), t, period_days)
        if not loaded:
            return err(f"No usable price history for {t}.", ticker=t)
        target_map = {d: p for d, p in zip(loaded[0], loaded[1], strict=True)}
        _dates, aligned = align_series({"target": target_map, "bench": bench_map})
        if not aligned:
            return err(f"{t} and {b} share no overlapping trading days.", ticker=t, benchmark=b)
        y, x = to_returns(aligned["target"]), to_returns(aligned["bench"])
        label = t
    else:
        built = _portfolio_returns(period_days)
        if built is None:
            return err("No priced holdings with enough shared history.", period_days=period_days)
        y, _weights, _ccy = built
        x = to_returns(bench_loaded[1])
        n = min(y.size, x.size)
        y, x = y[-n:], x[-n:]
        label = "Portfolio"

    if y.size < _MIN_BARS:
        return err(f"Only {y.size} overlapping observations — need at least {_MIN_BARS}.")

    stats = rk.beta_alpha(y, x, ppy=_TRADING_DAYS)
    if stats is None:
        return err("Regression failed — the series are degenerate.", ticker=t, benchmark=b)
    caps = rk.capture_ratios(y, x)

    rows = [
        {"metric": f"Beta vs {b}", "value": stats["beta"]},
        {"metric": "Alpha (annualised)", "value": stats["alpha_annualized_pct"], "unit": "%"},
        {"metric": "R²", "value": stats["r2"]},
        {"metric": "Beta t-stat", "value": stats["beta_t_stat"]},
        {"metric": "Tracking error", "value": stats["tracking_error_pct"], "unit": "%"},
        {"metric": "Idiosyncratic vol", "value": stats["idiosyncratic_vol_pct"], "unit": "%"},
        {"metric": "Up capture", "value": caps["up_capture_pct"], "unit": "%"},
        {"metric": "Down capture", "value": caps["down_capture_pct"], "unit": "%"},
    ]
    r2_pct = (stats["r2"] or 0.0) * 100.0

    return ok(
        raw_value=stats["beta"],
        formatted_value=f"β {format_number(stats['beta'])} vs {b}",
        formula="r = α + β·r_benchmark + ε  (OLS)",
        explanation=(
            f"{label} vs {b} over {stats['n_obs']} days: a 1% move in {b} came with a "
            f"{format_number(stats['beta'])}% move here, and {r2_pct:.0f}% of the variance "
            f"is explained by {b} alone. Annualised alpha {format_pct(stats['alpha_annualized_pct'], 2)} "
            f"(t = {stats['beta_t_stat']} on beta). Alpha over a short window is mostly noise."
        ),
        ui_type="table",
        data={"label": label, "benchmark": b, "rows": rows},
    )


# ─────────────────────────────────────────────────────────────────────────────
# Optimization
# ─────────────────────────────────────────────────────────────────────────────


@tool
def optimize_portfolio(
    objective: str = "max_sharpe",
    period_days: int = 365,
    long_only: bool = True,
    max_weight_pct: float = 0.0,
) -> dict[str, Any]:
    """Optimal weights for the user's ACTUAL holdings, plus the efficient frontier.

    Computes the max-Sharpe (tangency), minimum-variance or risk-parity
    portfolio over the user's real holdings and shows where their CURRENT
    weights sit against the frontier. Covariance is Ledoit-Wolf shrunk because
    a raw sample covariance makes mean-variance an error maximiser.

    Use for "how should I rebalance", "what's the optimal mix", "am I taking
    risk I'm not paid for".

    Mean-variance optimises the PAST. Expected returns estimated from history
    are a weak forecast; risk_parity ignores them entirely and is the more
    robust choice. Not advice.

    Args:
        objective: max_sharpe, min_variance or risk_parity.
        period_days: lookback window in days (90–1825).
        long_only: forbid short positions (default true).
        max_weight_pct: cap on any single weight, in percent (0 = no cap).
    """
    objective = (objective or "max_sharpe").strip().lower()
    if objective not in ("max_sharpe", "min_variance", "risk_parity"):
        return err(
            "objective must be max_sharpe, min_variance or risk_parity.", objective=objective
        )
    period_days = max(90, min(int(period_days), 1825))

    ccy = get_display_currency() or "USD"
    valued, _total, _cost, _fx = _valued_holdings(ccy)
    non_cash = [r for r in valued if r["asset_class"] != "cash" and r["value"] > 0]
    if len(non_cash) < 2:
        return err(
            "At least two priced non-cash holdings are needed to optimise a portfolio.",
            holdings=len(non_cash),
        )

    series = {}
    for r in non_cash:
        s = close_map(r["asset_class"], r["ticker"], period_days)
        if s and len(s) > 2:
            series[r["ticker"]] = s
    dates, aligned = align_series(series)
    if len(aligned) < 2 or len(dates) < _MIN_BARS:
        return err(
            "Holdings do not share enough overlapping history to estimate a covariance matrix.",
            overlapping_days=len(dates), priced=len(aligned),
        )

    tickers = sorted(aligned)
    matrix = np.column_stack([to_returns(aligned[t]) for t in tickers])
    mu, cov, shrinkage = opt.moments(matrix, ppy=_TRADING_DAYS)

    cap = (max_weight_pct / 100.0) if max_weight_pct and max_weight_pct > 0 else None
    converged = True
    if objective == "max_sharpe":
        weights, converged = opt.max_sharpe(mu, cov, long_only=long_only, w_max=cap)
    elif objective == "min_variance":
        weights = opt.min_variance(cov, long_only=long_only, w_max=cap)
    else:
        weights = opt.risk_parity(cov)

    value_by_ticker = {r["ticker"]: r["value"] for r in non_cash}
    total_value = sum(value_by_ticker[t] for t in tickers)
    current = np.asarray([value_by_ticker[t] / total_value for t in tickers], dtype=float)

    target_stats = opt.portfolio_stats(weights, mu, cov)
    current_stats = opt.portfolio_stats(current, mu, cov)
    frontier = opt.efficient_frontier(mu, cov, n_points=18, long_only=long_only, w_max=cap)

    bars = [
        {"label": t, "value": round(float(w) * 100.0, 2)}
        for t, w in sorted(zip(tickers, weights, strict=True), key=lambda p: -p[1])
    ][:12]
    changes = [
        {
            "ticker": t,
            "current_pct": round(float(c) * 100.0, 2),
            "target_pct": round(float(w) * 100.0, 2),
            "change_pct": round(float(w - c) * 100.0, 2),
        }
        for t, c, w in zip(tickers, current, weights, strict=True)
    ]
    changes.sort(key=lambda r: -abs(r["change_pct"]))

    sharpe_gain = target_stats["sharpe"] - current_stats["sharpe"]
    caveat = (
        "" if converged else
        " The constrained solver did not converge, so this is the minimum-variance "
        "portfolio rather than the true tangency portfolio."
    )

    return ok(
        raw_value=target_stats["sharpe"],
        formatted_value=(
            f"Sharpe {format_number(target_stats['sharpe'])} "
            f"(current {format_number(current_stats['sharpe'])})"
        ),
        formula="max (wᵀμ − r_f) / √(wᵀΣw)  s.t.  Σw = 1, w ≥ 0",
        explanation=(
            f"{objective.replace('_', ' ')} over {len(tickers)} holdings, {len(dates)} shared "
            f"trading days. Target: {target_stats['return_pct']:.1f}% return at "
            f"{target_stats['vol_pct']:.1f}% vol; current weights sit at "
            f"{current_stats['return_pct']:.1f}% / {current_stats['vol_pct']:.1f}%, "
            f"a Sharpe difference of {sharpe_gain:+.2f}. "
            f"Covariance shrunk toward a scaled identity at intensity {shrinkage:.2f} "
            "(Ledoit-Wolf) — without it, mean-variance chases estimation error."
            f"{caveat} This optimises the PAST; historical mean returns are a weak "
            "forecast of future ones. Not advice."
        ),
        ui_type="frontier",
        data={
            "objective": objective,
            "currency": ccy,
            "shrinkage": round(shrinkage, 4),
            "converged": converged,
            "points": [{"vol_pct": p["vol_pct"], "return_pct": p["return_pct"]} for p in frontier],
            "current": {**current_stats, "label": "Current"},
            "optimal": {**target_stats, "label": objective.replace("_", " ")},
            "bars": bars,
            "changes": changes[:12],
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# Options (calculators — this app has no option-chain feed)
# ─────────────────────────────────────────────────────────────────────────────


@tool
def price_option(
    spot: float,
    strike: float,
    days_to_expiry: float,
    volatility_pct: float,
    risk_free_pct: float = 0.0,
    kind: str = "call",
    dividend_yield_pct: float = 0.0,
) -> dict[str, Any]:
    """Black-Scholes-Merton option price and greeks from supplied inputs.

    A calculator, not a market lookup — this app has no option-chain feed, so
    every input comes from the caller. Greeks are in desk units: vega and rho
    per 1 percentage point, theta per calendar day.

    Use for "what's this option worth at 60% vol", "what's the delta of a
    30-day BTC call", "how much does a week of theta cost me".

    Args:
        spot: current underlying price.
        strike: option strike price.
        days_to_expiry: calendar days until expiry.
        volatility_pct: annualised implied volatility, in percent (e.g. 60 for 60%).
        risk_free_pct: annual risk-free rate, in percent.
        kind: "call" or "put".
        dividend_yield_pct: continuous dividend/carry yield, in percent.
    """
    kind = (kind or "call").strip().lower()
    if kind not in ("call", "put"):
        return err("kind must be 'call' or 'put'.", kind=kind)
    t_years = float(days_to_expiry) / 365.0
    sigma = float(volatility_pct) / 100.0
    r = float(risk_free_pct) / 100.0
    q = float(dividend_yield_pct) / 100.0

    price = bs_price(float(spot), float(strike), t_years, r, sigma, kind=kind, q=q)
    greeks = bs_greeks(float(spot), float(strike), t_years, r, sigma, kind=kind, q=q)
    if price is None or greeks is None:
        return err(
            "Invalid inputs — spot, strike, days_to_expiry and volatility must all be positive.",
            spot=spot, strike=strike, days_to_expiry=days_to_expiry,
            volatility_pct=volatility_pct,
        )

    moneyness = float(strike) / float(spot) if spot else None
    rows = [
        {"metric": "Price", "value": round(price, 4)},
        {"metric": "Delta", "value": round(greeks["delta"], 4)},
        {"metric": "Gamma", "value": round(greeks["gamma"], 6)},
        {"metric": "Vega (per 1 vol pt)", "value": round(greeks["vega"], 4)},
        {"metric": "Theta (per day)", "value": round(greeks["theta"], 4)},
        {"metric": "Rho (per 1 rate pt)", "value": round(greeks["rho"], 4)},
        {"metric": "Moneyness (K/S)", "value": round(moneyness, 4) if moneyness else None},
    ]

    return ok(
        raw_value=round(price, 4),
        formatted_value=format_number(price, 4),
        formula="C = S·e^(−qT)·N(d₁) − K·e^(−rT)·N(d₂)",
        explanation=(
            f"{kind.title()} struck at {format_number(strike, 2)} with spot "
            f"{format_number(spot, 2)}, {days_to_expiry:.0f} days to expiry at "
            f"{volatility_pct:.1f}% implied vol. Delta {greeks['delta']:.3f}, "
            f"theta {greeks['theta']:.4f} per day. "
            "Black-Scholes assumes constant volatility and continuous prices — crypto has "
            "neither, so treat this as a quoting convention rather than a fair value."
        ),
        ui_type="table",
        data={"kind": kind, "rows": rows},
    )


@tool
def implied_volatility(
    option_price: float,
    spot: float,
    strike: float,
    days_to_expiry: float,
    risk_free_pct: float = 0.0,
    kind: str = "call",
    dividend_yield_pct: float = 0.0,
) -> dict[str, Any]:
    """Implied volatility backed out of an observed option price.

    Inverts Black-Scholes by Brent root-finding. Returns an error rather than a
    number when the quote violates no-arbitrage bounds or has no solution —
    common for deep out-of-the-money strikes.

    Use for "what vol is this option pricing in", "is this option expensive".

    Args:
        option_price: the observed option premium.
        spot: current underlying price.
        strike: option strike price.
        days_to_expiry: calendar days until expiry.
        risk_free_pct: annual risk-free rate, in percent.
        kind: "call" or "put".
        dividend_yield_pct: continuous dividend/carry yield, in percent.
    """
    kind = (kind or "call").strip().lower()
    if kind not in ("call", "put"):
        return err("kind must be 'call' or 'put'.", kind=kind)
    t_years = float(days_to_expiry) / 365.0
    iv = implied_vol(
        float(option_price), float(spot), float(strike), t_years,
        float(risk_free_pct) / 100.0, kind=kind, q=float(dividend_yield_pct) / 100.0,
    )
    if iv is None:
        return err(
            "No implied volatility solves this quote — it is outside the no-arbitrage "
            "bounds or beyond the 0–500% search range.",
            option_price=option_price, spot=spot, strike=strike,
            days_to_expiry=days_to_expiry, kind=kind,
        )

    iv_pct = iv * 100.0
    return ok(
        raw_value=round(iv_pct, 2),
        formatted_value=f"{iv_pct:.1f}%",
        formula="solve σ such that BS(S, K, T, r, σ) = observed price",
        explanation=(
            f"A {kind} at strike {format_number(strike, 2)} priced at "
            f"{format_number(option_price, 4)} with spot {format_number(spot, 2)} and "
            f"{days_to_expiry:.0f} days left implies {iv_pct:.1f}% annualised volatility. "
            "Implied vol is the market's price of uncertainty, not a forecast."
        ),
        ui_type="metric",
        data={"kind": kind, "iv_pct": round(iv_pct, 2), "days_to_expiry": float(days_to_expiry)},
    )
