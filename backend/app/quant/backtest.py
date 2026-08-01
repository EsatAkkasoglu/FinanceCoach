"""Vectorised price-path backtester — the piece ``app/eval/scorecard.py`` says is missing.

The scorecard can already grade a *discrete trade ledger*. What it cannot do is
grade a **rule** over a continuous price path, which is what every question of
the form "what would this strategy have done?" actually asks. This module
produces that per-bar return series and hands it straight to the existing metric
kernel — no metric is re-implemented here.

Three things make the difference between a backtest and a fairy tale, and all
three are enforced structurally rather than left to the caller:

1. **No look-ahead.** A signal computed from bars ``0..t`` can only be traded
   over the return from ``t`` to ``t+1``. :func:`align_positions` does that
   shift once, in one place, and :func:`run_backtest` will not accept an
   unaligned position array of the wrong length.
2. **Costs are not optional.** Fees, slippage and (for perpetual-style
   exposure) funding are charged on every position change, and the difference
   between gross and net is reported as ``cost_drag`` instead of being buried.
3. **Multiple testing is priced in.** Searching a parameter grid and reporting
   the winner's Sharpe is the single most common way a backtest lies.
   :func:`walk_forward` reports out-of-sample results separately and deflates
   the Sharpe by the number of trials actually run
   (Bailey & López de Prado, "The Deflated Sharpe Ratio", SSRN 2460551).

Sources
-------
* Marcos López de Prado, *Advances in Financial Machine Learning* — purged /
  embargoed cross-validation (ch. 7), backtest overfitting (ch. 11).
* Stefan Jansen, *Machine Learning for Trading* — the walk-forward
  train/test discipline this follows.

Honest limits
-------------
* Bar-close execution. No intrabar fills, no partial fills, no order book, no
  market impact beyond a flat slippage assumption.
* Single instrument, long/flat or long/short. This is not a portfolio backtest.
* Survivorship bias is **not** corrected: the ticker is one the user named
  today, which already conditions on it having survived.
* Dividends/splits come in only via yfinance's ``auto_adjust`` total-return
  series; funds use NAV, which is already total-return.
"""
from __future__ import annotations

import itertools
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

from app.eval.scorecard import (
    _skew_kurt,
    calmar,
    deflated_sharpe_ratio,
    max_drawdown,
    probabilistic_sharpe_ratio,
    profit_factor,
    sharpe,
    sortino,
)
from app.quant.data import to_returns
from app.tools.crypto_short_term import ema_series

# ─────────────────────────────────────────────────────────────────────────────
# Costs
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Costs:
    """Round-trip trading frictions, in basis points.

    ``fee_bps`` and ``slippage_bps`` are charged on the *absolute change* in
    position, so a 0→1 entry and a 1→0 exit are each charged once (a full round
    trip therefore costs twice the one-way figure — the usual convention).
    ``funding_bps_per_bar`` is a carry charge on held exposure, for
    perpetual-swap-style positions where the funding rate is a real cost.
    """

    fee_bps: float = 10.0
    slippage_bps: float = 5.0
    funding_bps_per_bar: float = 0.0

    @property
    def per_turn(self) -> float:
        return (max(0.0, self.fee_bps) + max(0.0, self.slippage_bps)) / 1e4

    @property
    def per_bar_carry(self) -> float:
        return max(0.0, self.funding_bps_per_bar) / 1e4


# ─────────────────────────────────────────────────────────────────────────────
# Indicator series (the scalar forms live in tools/crypto_short_term.py)
# ─────────────────────────────────────────────────────────────────────────────


def sma_series(values: np.ndarray, period: int) -> np.ndarray:
    """Rolling simple mean; the first ``period-1`` entries are NaN."""
    v = np.asarray(values, dtype=float)
    out = np.full(v.size, np.nan)
    if period < 1 or v.size < period:
        return out
    c = np.cumsum(np.insert(v, 0, 0.0))
    out[period - 1:] = (c[period:] - c[:-period]) / float(period)
    return out


def _rolling_std(values: np.ndarray, period: int) -> np.ndarray:
    """Rolling sample stdev; the first ``period-1`` entries are NaN.

    Computed from rolling sums rather than a Python loop — at 9000 bars × a
    parameter grid × 32 (symbol, timeframe) pairs, the loop version dominates
    the tournament's runtime.
    """
    v = np.asarray(values, dtype=float)
    out = np.full(v.size, np.nan)
    if period < 2 or v.size < period:
        return out
    c1 = np.cumsum(np.insert(v, 0, 0.0))
    c2 = np.cumsum(np.insert(v * v, 0, 0.0))
    s1 = c1[period:] - c1[:-period]
    s2 = c2[period:] - c2[:-period]
    var = (s2 - s1 * s1 / period) / (period - 1)
    out[period - 1:] = np.sqrt(np.maximum(var, 0.0))
    return out


def atr_series(
    highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14
) -> np.ndarray:
    """Wilder's ATR at every bar — the series form of ``crypto_short_term.atr``."""
    h = np.asarray(highs, dtype=float)
    low_arr = np.asarray(lows, dtype=float)
    c = np.asarray(closes, dtype=float)
    n = c.size
    out = np.full(n, np.nan)
    if n <= period or h.size != n or low_arr.size != n:
        return out
    prev = c[:-1]
    tr = np.maximum.reduce([h[1:] - low_arr[1:], np.abs(h[1:] - prev), np.abs(low_arr[1:] - prev)])
    val = float(tr[:period].mean())
    out[period] = val
    for i in range(period, tr.size):
        val = (val * (period - 1) + tr[i]) / period
        out[i + 1] = val
    return out


def rsi_series(values: np.ndarray, period: int = 14) -> np.ndarray:
    """Wilder's RSI at every bar; the first ``period`` entries are NaN.

    The series form of ``app.tools.crypto_short_term.rsi``, which only returns
    the final value. ``test_quant_backtest.py`` asserts the last element of this
    series equals that function's output, so the two can never silently drift.
    """
    v = np.asarray(values, dtype=float)
    out = np.full(v.size, np.nan)
    if v.size <= period or period < 1:
        return out
    delta = np.diff(v)
    gains = np.where(delta > 0, delta, 0.0)
    losses = np.where(delta < 0, -delta, 0.0)
    avg_gain = float(gains[:period].mean())
    avg_loss = float(losses[:period].mean())

    def _rsi(g: float, loss: float) -> float:
        if loss == 0:
            return 100.0 if g > 0 else 50.0
        return 100.0 - (100.0 / (1.0 + g / loss))

    out[period] = _rsi(avg_gain, avg_loss)
    for i in range(period, delta.size):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        out[i + 1] = _rsi(avg_gain, avg_loss)
    return out


def macd_series(
    values: np.ndarray, fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[np.ndarray, np.ndarray]:
    """(MACD line, signal line) using the same EMA seeding as the live tools."""
    v = [float(x) for x in values]
    ef = np.asarray(ema_series(v, fast), dtype=float)
    es = np.asarray(ema_series(v, slow), dtype=float)
    line = ef - es
    sig = np.asarray(ema_series([float(x) for x in line], signal), dtype=float)
    return line, sig


# ─────────────────────────────────────────────────────────────────────────────
# Strategies — each returns (raw target position per bar, warmup bars)
# ─────────────────────────────────────────────────────────────────────────────

SignalFn = Callable[..., tuple[np.ndarray, int]]

#: How often the vol-regime filter recomputes its expanding quantile (in bars).
_QUANTILE_REFRESH = 24


def _carry_forward(entries: np.ndarray, exits: np.ndarray) -> np.ndarray:
    """State machine for entry/exit rules: hold until the opposite signal fires."""
    pos = np.zeros(entries.size, dtype=float)
    state = 0.0
    for i in range(entries.size):
        if entries[i]:
            state = 1.0
        elif exits[i]:
            state = 0.0
        pos[i] = state
    return pos


def _sig_sma_cross(closes, highs, lows, *, fast: int = 20, slow: int = 50, **_):
    if fast >= slow:
        fast, slow = min(fast, slow), max(fast, slow) + 1
    f, s = sma_series(closes, fast), sma_series(closes, slow)
    raw = np.where(np.isfinite(f) & np.isfinite(s) & (f > s), 1.0, 0.0)
    return raw, slow


def _sig_ema_cross(closes, highs, lows, *, fast: int = 12, slow: int = 26, **_):
    if fast >= slow:
        fast, slow = min(fast, slow), max(fast, slow) + 1
    v = [float(x) for x in closes]
    f = np.asarray(ema_series(v, fast), dtype=float)
    s = np.asarray(ema_series(v, slow), dtype=float)
    return np.where(f > s, 1.0, 0.0), slow


def _sig_rsi_reversion(closes, highs, lows, *, period: int = 14, low: float = 30.0,
                       high: float = 70.0, **_):
    r = rsi_series(closes, period)
    ok_mask = np.isfinite(r)
    return _carry_forward(ok_mask & (r < low), ok_mask & (r > high)), period + 1


def _sig_macd(closes, highs, lows, *, fast: int = 12, slow: int = 26, signal: int = 9, **_):
    line, sig = macd_series(closes, fast, slow, signal)
    return np.where(line > sig, 1.0, 0.0), slow + signal


def _sig_tsmom(closes, highs, lows, *, lookback: int = 126, **_):
    c = np.asarray(closes, dtype=float)
    raw = np.zeros(c.size, dtype=float)
    if c.size > lookback:
        raw[lookback:] = np.where(c[lookback:] > c[:-lookback], 1.0, 0.0)
    return raw, lookback


def _sig_donchian(closes, highs, lows, *, lookback: int = 20, **_):
    c = np.asarray(closes, dtype=float)
    h = np.asarray(highs if highs is not None else closes, dtype=float)
    low_arr = np.asarray(lows if lows is not None else closes, dtype=float)
    n = c.size
    entries = np.zeros(n, dtype=bool)
    exits = np.zeros(n, dtype=bool)
    if n <= lookback:
        return entries.astype(float), lookback
    # Channel is built from the PRIOR `lookback` bars — never including bar i,
    # which would make the breakout test trivially self-referential. The
    # sliding windows below end at i-1 for exactly that reason.
    hi = sliding_window_view(h[:-1], lookback).max(axis=1)
    lo = sliding_window_view(low_arr[:-1], lookback).min(axis=1)
    entries[lookback:] = c[lookback:] > hi
    exits[lookback:] = c[lookback:] < lo
    return _carry_forward(entries, exits), lookback


def _sig_bollinger_reversion(closes, highs, lows, *, period: int = 20, k: float = 2.0, **_):
    """Buy the lower band, exit at the mean. Classic intraday mean reversion.

    Both legs are close-vs-level tests, so a bar-close engine can evaluate them
    with no intrabar ambiguity — unlike a stop-and-target pair, which can both
    sit inside one bar's range with no way to know which printed first.
    """
    c = np.asarray(closes, dtype=float)
    mid = sma_series(c, period)
    sd = _rolling_std(c, period)
    lower = mid - k * sd
    defined = np.isfinite(mid) & np.isfinite(sd)
    return _carry_forward(defined & (c < lower), defined & (c > mid)), period


def _sig_vol_regime_tsmom(
    closes, highs, lows, *, lookback: int = 48, vol_window: int = 96,
    vol_quantile: float = 0.5, **_
):
    """Time-series momentum, but only while realised volatility is elevated.

    Tests the standing claim that trend-following pays in high-vol regimes and
    bleeds in quiet ones. The regime threshold is an EXPANDING quantile of past
    volatility — a full-sample quantile would leak the future into every bar.
    """
    c = np.asarray(closes, dtype=float)
    n = c.size
    warmup = max(lookback, vol_window) + 2
    raw = np.zeros(n, dtype=float)
    if n <= warmup:
        return raw, warmup

    rets = np.zeros(n, dtype=float)
    rets[1:] = np.diff(c) / c[:-1]
    vol = _rolling_std(rets, vol_window)

    trend = np.zeros(n, dtype=bool)
    trend[lookback:] = c[lookback:] > c[:-lookback]

    # Expanding quantile, refreshed every `_QUANTILE_REFRESH` bars and held in
    # between. A per-bar recompute is O(n² log n) and dominates the tournament;
    # refreshing on a schedule stays strictly causal (the threshold in force at
    # bar i was computed from bars < i) while being ~two orders faster.
    threshold = np.full(n, np.nan)
    current = np.nan
    for i in range(warmup, n):
        if (i - warmup) % _QUANTILE_REFRESH == 0:
            window = vol[:i]
            window = window[np.isfinite(window)]
            current = float(np.quantile(window, vol_quantile)) if window.size >= 10 else np.nan
        threshold[i] = current

    live = np.isfinite(vol) & np.isfinite(threshold)
    raw[live & (vol >= threshold) & trend] = 1.0
    raw[:warmup] = 0.0
    return raw, warmup


def _sig_buy_hold(closes, highs, lows, **_):
    return np.ones(np.asarray(closes).size, dtype=float), 0


SIGNALS: dict[str, SignalFn] = {
    "sma_cross": _sig_sma_cross,
    "ema_cross": _sig_ema_cross,
    "rsi_reversion": _sig_rsi_reversion,
    "macd": _sig_macd,
    "tsmom": _sig_tsmom,
    "donchian": _sig_donchian,
    "bollinger_reversion": _sig_bollinger_reversion,
    "vol_regime_tsmom": _sig_vol_regime_tsmom,
    "buy_hold": _sig_buy_hold,
}

#: Parameter grids used by :func:`walk_forward`. Deliberately small — every
#: extra combination raises the Deflated-Sharpe bar the strategy must clear.
PARAM_GRIDS: dict[str, dict[str, list[Any]]] = {
    "sma_cross": {"fast": [10, 20, 50], "slow": [50, 100, 200]},
    "ema_cross": {"fast": [8, 12, 21], "slow": [26, 55]},
    "rsi_reversion": {"period": [7, 14], "low": [25.0, 30.0], "high": [70.0, 75.0]},
    "macd": {"fast": [12], "slow": [26], "signal": [9]},
    "tsmom": {"lookback": [21, 63, 126, 252]},
    "donchian": {"lookback": [20, 55]},
    "bollinger_reversion": {"period": [20, 50], "k": [1.5, 2.0, 2.5]},
    "vol_regime_tsmom": {"lookback": [24, 48], "vol_window": [96], "vol_quantile": [0.4, 0.6]},
    "buy_hold": {},
}


def apply_confirmation(raw: np.ndarray, bars: int) -> np.ndarray:
    """Act on a new target only after it has held for ``bars`` consecutive bars.

    This is the no-trade band, expressed on the position rather than on a score
    so it works uniformly across every rule here without rewriting them.

    Why it is the highest-value knob in the whole engine: at 15-minute bars a
    30bps round trip is roughly twice BTC's one-bar sigma, so a rule that flips
    on noise pays away more than it can possibly earn. Bysik & Ślepaczuk
    (70,872 hourly BTC/USDT bars, 27 walk-forward folds) took one unchanged
    forecast from ARC -64.0% to +65.4% purely by adding execution hysteresis,
    which cut trades from 10,619 to 251. The alpha did not improve; the
    turnover stopped destroying it.

    ``bars <= 1`` is the identity, so every previously recorded result stays
    exactly reproducible and the two are directly comparable.
    """
    p = np.asarray(raw, dtype=float)
    if bars <= 1 or p.size == 0:
        return p
    out = np.empty_like(p)
    current = p[0]
    streak_value = p[0]
    streak = 1
    out[0] = current
    for i in range(1, p.size):
        if p[i] == streak_value:
            streak += 1
        else:
            streak_value, streak = p[i], 1
        if streak >= bars and streak_value != current:
            current = streak_value
        out[i] = current
    return out


def apply_min_hold(raw: np.ndarray, bars: int) -> np.ndarray:
    """Once a position is opened, keep it for at least ``bars`` bars.

    A target is allowed to persist past its own signal — a 15-minute rule does
    not have to be flat again 15 minutes later. Combined with
    :func:`apply_confirmation` this is what lets a fast-timeframe rule hold a
    position across many bars instead of round-tripping the spread every bar.
    """
    p = np.asarray(raw, dtype=float)
    if bars <= 1 or p.size == 0:
        return p
    out = np.empty_like(p)
    current = p[0]
    held_for = 1
    out[0] = current
    for i in range(1, p.size):
        if p[i] != current and held_for >= bars:
            current = p[i]
            held_for = 1
        else:
            held_for += 1
        out[i] = current
    return out


def build_positions(
    strategy: str,
    closes: np.ndarray,
    highs: np.ndarray | None = None,
    lows: np.ndarray | None = None,
    params: dict[str, Any] | None = None,
    *,
    allow_short: bool = False,
) -> tuple[np.ndarray, int]:
    """Target position per bar, before the execution shift.

    ``allow_short`` maps the flat leg to -1 instead of 0, turning a long/flat
    rule into long/short.

    Two turnover controls are read out of ``params`` rather than passed
    separately, so they travel through the parameter grid like any other knob:
    ``confirm_bars`` (act only on a target that has persisted) and
    ``min_hold_bars`` (do not reverse before this many bars). Both default to 1,
    which is the identity. Returns ``(positions, warmup_bars)``.
    """
    fn = SIGNALS.get(strategy)
    if fn is None:
        raise KeyError(f"unknown strategy: {strategy}")
    params = dict(params or {})
    confirm_bars = int(params.pop("confirm_bars", 1) or 1)
    min_hold_bars = int(params.pop("min_hold_bars", 1) or 1)

    raw, warmup = fn(closes, highs, lows, **params)
    raw = np.nan_to_num(np.asarray(raw, dtype=float), nan=0.0)
    if allow_short and strategy != "buy_hold":
        raw = np.where(raw > 0, 1.0, -1.0)
    raw[:warmup] = 0.0  # nothing is tradable before the indicator is defined

    if confirm_bars > 1:
        raw = apply_confirmation(raw, confirm_bars)
    if min_hold_bars > 1:
        raw = apply_min_hold(raw, min_hold_bars)
    raw[:warmup] = 0.0
    return raw, warmup


def align_positions(raw_positions: np.ndarray) -> np.ndarray:
    """Shift target positions by one bar — **the look-ahead guard**.

    ``raw_positions[t]`` is decided from data up to and including bar ``t``, so
    the earliest return it can earn is the one from ``t`` to ``t+1``. Returns an
    array of length ``n-1``, aligned element-wise with :func:`data.to_returns`.
    """
    p = np.asarray(raw_positions, dtype=float)
    return p[:-1].copy() if p.size >= 2 else np.asarray([], dtype=float)


# ─────────────────────────────────────────────────────────────────────────────
# Engine
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class BacktestResult:
    """Everything downstream needs, all JSON-safe once ``as_dict`` is applied."""

    bar_returns: np.ndarray          # net of costs
    gross_returns: np.ndarray        # before costs
    benchmark_returns: np.ndarray    # buy & hold over the same bars
    equity: np.ndarray
    benchmark_equity: np.ndarray
    drawdown: np.ndarray
    positions: np.ndarray
    dates: list[str] = field(default_factory=list)
    warmup: int = 0
    n_trades: int = 0
    turnover: float = 0.0
    cost_drag: float = 0.0           # gross total return − net total return

    @property
    def net_total_return(self) -> float:
        return float(self.equity[-1] - 1.0) if self.equity.size else 0.0

    @property
    def gross_total_return(self) -> float:
        if not self.gross_returns.size:
            return 0.0
        return float(np.prod(1.0 + self.gross_returns) - 1.0)


def run_backtest(
    closes: np.ndarray,
    raw_positions: np.ndarray,
    *,
    costs: Costs,
    warmup: int = 0,
    dates: list[str] | None = None,
) -> BacktestResult:
    """Run one parameterisation over a price path.

    ``raw_positions`` are *unshifted* targets from :func:`build_positions`; the
    one-bar execution shift happens here so no caller can forget it.
    """
    c = np.asarray(closes, dtype=float)
    asset_r = to_returns(c)
    held = align_positions(raw_positions)
    if asset_r.size == 0 or held.size != asset_r.size:
        empty = np.asarray([], dtype=float)
        return BacktestResult(empty, empty, empty, empty, empty, empty, empty, [], warmup)

    # Trim the warm-up stretch: positions there are structurally zero, and
    # leaving them in would dilute vol and flatter the drawdown.
    start = min(max(0, warmup), max(0, held.size - 1))
    asset_r = asset_r[start:]
    held = held[start:]
    bar_dates = (dates or [])[start + 1:] if dates else []

    prev = np.concatenate(([0.0], held[:-1]))
    traded = np.abs(held - prev)
    cost = traded * costs.per_turn + np.abs(held) * costs.per_bar_carry

    gross = held * asset_r
    net = gross - cost
    equity = np.cumprod(1.0 + net)
    bench_equity = np.cumprod(1.0 + asset_r)
    peak = np.maximum.accumulate(equity)
    drawdown = equity / peak - 1.0

    gross_total = float(np.prod(1.0 + gross) - 1.0)
    net_total = float(equity[-1] - 1.0)

    return BacktestResult(
        bar_returns=net,
        gross_returns=gross,
        benchmark_returns=asset_r,
        equity=equity,
        benchmark_equity=bench_equity,
        drawdown=drawdown,
        positions=held,
        dates=[str(d) for d in bar_dates],
        warmup=start,
        n_trades=int(np.count_nonzero(traded > 1e-12)),
        turnover=float(traded.sum()),
        cost_drag=gross_total - net_total,
    )


def summarize(
    result: BacktestResult, *, ppy: float, n_trials: int = 1,
    variance_trials: float | None = None,
) -> dict[str, Any]:
    """Risk-adjusted summary, computed by ``app.eval.scorecard`` — not re-derived.

    ``sharpe`` is per-bar (the form PSR/DSR are defined on);
    ``sharpe_annualized`` scales it by √ppy, matching ``scorecard._cell_metrics``.
    """
    r = [float(x) for x in result.bar_returns]
    if len(r) < 2:
        return {"n_bars": len(r), "insufficient_data": True}

    sr = sharpe(r)
    skew, kurt = _skew_kurt(r)
    mdd = max_drawdown(r)
    bench = [float(x) for x in result.benchmark_returns]
    bench_total = float(np.prod(1.0 + np.asarray(bench)) - 1.0) if bench else None

    def _r(x: float | None, p: int = 4) -> float | None:
        return round(float(x), p) if x is not None and math.isfinite(float(x)) else None

    total = result.net_total_return
    years = len(r) / ppy if ppy > 0 else 0.0
    cagr = ((1.0 + total) ** (1.0 / years) - 1.0) if years > 0 and total > -1.0 else None

    return {
        "n_bars": len(r),
        "total_return_pct": _r(total * 100.0, 3),
        "gross_return_pct": _r(result.gross_total_return * 100.0, 3),
        "benchmark_return_pct": _r(bench_total * 100.0, 3) if bench_total is not None else None,
        "excess_vs_buy_hold_pct": (
            _r((total - bench_total) * 100.0, 3) if bench_total is not None else None
        ),
        "cagr_pct": _r(cagr * 100.0, 3) if cagr is not None else None,
        "ann_vol_pct": _r(float(np.std(r, ddof=1)) * math.sqrt(ppy) * 100.0, 3),
        "sharpe": _r(sr),
        "sharpe_annualized": _r(sr * math.sqrt(ppy)) if sr is not None else None,
        "sortino": _r(sortino(r)),
        "calmar": _r(calmar(r, ppy)),
        "max_drawdown_pct": _r(mdd * 100.0, 3) if mdd is not None else None,
        "profit_factor": _r(profit_factor(r)),
        "win_rate": _r(sum(1 for x in r if x > 0) / len(r)),
        "psr": _r(probabilistic_sharpe_ratio(sr, len(r), skew, kurt)) if sr is not None else None,
        "dsr": (
            _r(deflated_sharpe_ratio(
                sr, len(r), skew, kurt, max(1, n_trials),
                # Same units trap as walk_forward: the library default of 1.0 is
                # unit variance of ANNUAL Sharpes and pins DSR at 0.0 when fed a
                # per-bar one.
                variance_trials=(
                    variance_trials if variance_trials is not None
                    else trial_variance([], ppy)
                ),
            ))
            if sr is not None else None
        ),
        "n_trials": max(1, n_trials),
        "n_trades": result.n_trades,
        "turnover": _r(result.turnover, 2),
        "cost_drag_pct": _r(result.cost_drag * 100.0, 3),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Walk-forward
# ─────────────────────────────────────────────────────────────────────────────


def trial_variance(trial_sharpes: list[float], ppy: float) -> float:
    """Variance of the trial Sharpe ratios, in the SAME units as the Sharpe passed
    alongside it.

    This is the input ``deflated_sharpe_ratio`` needs and the one everybody gets
    wrong. Its ``variance_trials`` defaults to 1.0, which reads as "the Sharpes
    across trials have unit variance" — true for ANNUAL Sharpes, absurd for the
    per-bar Sharpes this engine works in. At 15-minute bars a per-bar Sharpe of
    0.0955 is an annualised 17.9; leaving variance_trials at 1.0 puts the
    benchmark SR0 at 3.5 per-bar, i.e. an **annualised Sharpe of ~660**. Nothing
    clears that, so DSR comes back 0.0000 for every cell and any survivor gate
    built on it can never fire.

    That is a false negative dressed as rigour, which is worse than no test at
    all: the tournament would report "nothing works" and look honest doing it.

    Falls back to the variance implied by a 0.5 spread in ANNUALISED Sharpe
    across trials when the sample is too thin to estimate — conservative, and in
    the right units.
    """
    if len(trial_sharpes) >= 2:
        var = float(np.var(np.asarray(trial_sharpes, dtype=float), ddof=1))
        if var > 0 and math.isfinite(var):
            return var
    return (0.5 / math.sqrt(max(ppy, 1.0))) ** 2


def _grid_combos(grid: dict[str, list[Any]]) -> list[dict[str, Any]]:
    if not grid:
        return [{}]
    keys = sorted(grid)
    return [dict(zip(keys, vals, strict=True)) for vals in itertools.product(*(grid[k] for k in keys))]


def walk_forward(
    closes: np.ndarray,
    strategy: str,
    *,
    highs: np.ndarray | None = None,
    lows: np.ndarray | None = None,
    grid: dict[str, list[Any]] | None = None,
    combos: list[dict[str, Any]] | None = None,
    n_folds: int = 4,
    embargo: int = 5,
    costs: Costs | None = None,
    ppy: float = 252.0,
    allow_short: bool = False,
    min_test_bars: int = 30,
    return_series: bool = False,
) -> dict[str, Any]:
    """Expanding-window walk-forward: tune on the past, score on the future.

    Each fold selects the best parameter combination on everything seen so far
    (by per-bar Sharpe), then applies it — unchanged — to the next block. An
    ``embargo`` gap is dropped at the start of every test block so a slow
    indicator cannot straddle the boundary (López de Prado's purging).

    The concatenated test-block returns form a genuine out-of-sample track
    record, and its Sharpe is deflated by the number of combinations tried.
    Returns ``{"ok": False, "reason": ...}`` when the history is too short —
    it never fabricates a fold.
    """
    costs = costs or Costs()
    grid = grid if grid is not None else PARAM_GRIDS.get(strategy, {})
    # An explicit combo list is NOT the same as a grid. A screen that rejects
    # individual combinations leaves a non-rectangular set, and collapsing it
    # back into per-key value lists re-expands the full cross product — quietly
    # re-admitting the very combinations that were rejected.
    combos = list(combos) if combos is not None else _grid_combos(grid)
    c = np.asarray(closes, dtype=float)

    # Positions are causal, so computing them once on the full path and slicing
    # is identical to recomputing per window — and far cheaper.
    precomputed: list[tuple[dict[str, Any], np.ndarray, int]] = []
    for params in combos:
        try:
            raw, warmup = build_positions(strategy, c, highs, lows, params, allow_short=allow_short)
        except KeyError:
            return {"ok": False, "reason": f"unknown strategy: {strategy}"}
        precomputed.append((params, align_positions(raw), warmup))

    asset_r = to_returns(c)
    max_warmup = max((w for _, _, w in precomputed), default=0)
    usable = asset_r.size - max_warmup
    folds_possible = int(usable // max(1, min_test_bars)) - 1
    n_folds = max(0, min(n_folds, folds_possible))
    if n_folds < 1:
        return {
            "ok": False,
            "reason": (
                f"not enough history for out-of-sample folds "
                f"({usable} usable bars after a {max_warmup}-bar warm-up; "
                f"need at least {2 * min_test_bars})"
            ),
            "n_trials": len(combos),
        }

    bounds = np.linspace(max_warmup, asset_r.size, n_folds + 2).round().astype(int)
    oos: list[float] = []
    bench: list[float] = []
    fold_rows: list[dict[str, Any]] = []
    #: Every in-sample Sharpe the search looked at. Their VARIANCE is what the
    #: Deflated Sharpe needs — see trial_variance() for why the default of 1.0
    #: silently makes DSR identically zero.
    trial_sharpes: list[float] = []
    oos_trades = 0
    last_params: dict[str, Any] | None = None

    for f in range(1, n_folds + 1):
        train_end = int(bounds[f])
        test_start = min(train_end + embargo, asset_r.size)
        test_end = int(bounds[f + 1])
        if test_end - test_start < 2:
            continue

        best_params, best_sr = None, None
        for params, held, warmup in precomputed:
            # Score the training window NET of costs. Selecting on a cost-free
            # Sharpe and then reporting the net result picks whichever rule
            # trades most — precisely the rule that cannot survive its own
            # turnover once it is scored honestly.
            hs = held[warmup:train_end]
            prev_hs = np.concatenate(([0.0], hs[:-1])) if hs.size else hs
            seg_net = (
                hs * asset_r[warmup:train_end]
                - np.abs(hs - prev_hs) * costs.per_turn
                - np.abs(hs) * costs.per_bar_carry
            )
            s = sharpe([float(x) for x in seg_net])
            if s is None:
                continue
            trial_sharpes.append(s)
            if best_sr is None or s > best_sr:
                best_sr, best_params = s, params
        if best_params is None:
            continue

        held = next(h for p, h, _ in precomputed if p == best_params)
        seg_pos = held[test_start:test_end]
        seg_ret = asset_r[test_start:test_end]
        prev = np.concatenate(([0.0], seg_pos[:-1]))
        traded = np.abs(seg_pos - prev)
        net = seg_pos * seg_ret - traded * costs.per_turn - np.abs(seg_pos) * costs.per_bar_carry
        oos.extend(float(x) for x in net)
        oos_trades += int(np.count_nonzero(traded > 1e-12))
        last_params = best_params
        # Buy & hold over the very same test bars. Without this, "excess return"
        # would compare an out-of-sample record against a full-sample benchmark —
        # two different windows, so the difference is mostly just market drift.
        bench.extend(float(x) for x in seg_ret)
        fold_rows.append({
            "fold": f,
            "train_bars": train_end - max_warmup,
            "test_bars": int(test_end - test_start),
            "params": best_params,
            "train_sharpe": round(float(best_sr), 4) if best_sr is not None else None,
            "test_sharpe": (lambda s: round(s, 4) if s is not None else None)(
                sharpe([float(x) for x in net])
            ),
            "test_return_pct": round(float(np.prod(1.0 + net) - 1.0) * 100.0, 3),
        })

    if len(oos) < 2:
        return {"ok": False, "reason": "no usable out-of-sample block", "n_trials": len(combos)}

    sr = sharpe(oos)
    skew, kurt = _skew_kurt(oos)
    mdd = max_drawdown(oos)
    return {
        "ok": True,
        "n_folds": len(fold_rows),
        "n_trials": len(combos),
        "embargo_bars": embargo,
        "oos_bars": len(oos),
        "oos_return_pct": round(float(np.prod(1.0 + np.asarray(oos)) - 1.0) * 100.0, 3),
        "oos_sharpe": round(sr, 4) if sr is not None else None,
        "oos_sharpe_annualized": round(sr * math.sqrt(ppy), 4) if sr is not None else None,
        "oos_sortino": (lambda s: round(s, 4) if s is not None else None)(sortino(oos)),
        "oos_max_drawdown_pct": round(mdd * 100.0, 3) if mdd is not None else None,
        "oos_dsr": (
            (lambda d: round(d, 4) if d is not None else None)(
                deflated_sharpe_ratio(
                    sr, len(oos), skew, kurt, len(combos),
                    variance_trials=trial_variance(trial_sharpes, ppy),
                )
            ) if sr is not None else None
        ),
        "trial_sharpe_variance": round(trial_variance(trial_sharpes, ppy), 12),
        "folds": fold_rows,
        "oos_trades": oos_trades,
        # The parameters the most recent fold selected on data before its own
        # test window. This — not a full-sample argmax — is what a live book
        # would be running, and it is the only choice whose forward result the
        # walk-forward record actually speaks to.
        "last_fold_params": last_params,
        "benchmark_return_pct": round(float(np.prod(1.0 + np.asarray(bench)) - 1.0) * 100.0, 3),
        "excess_vs_buy_hold_pct": round(
            (float(np.prod(1.0 + np.asarray(oos))) - float(np.prod(1.0 + np.asarray(bench)))) * 100.0, 3
        ),
        **(
            {"oos_returns": oos, "benchmark_returns": bench} if return_series else {}
        ),
        "note": (
            "Out-of-sample only: each fold's parameters were chosen on prior bars "
            f"and applied unchanged to the next block. The Deflated Sharpe accounts "
            f"for {len(combos)} parameter combination(s) tested."
        ),
    }
