"""Strategy tournament — which rule, on which coin, at which timeframe, actually pays.

The experiment this exists for: run every (coin × timeframe × strategy × parameter
set) through honest walk-forward validation, and find out whether *anything*
survives realistic crypto trading costs at 15m to 4h bars.

The whole design turns on one number that most tournaments get wrong.

**Multiple testing is accounted for across the ENTIRE tournament, not per cell.**
``backtest.walk_forward`` already deflates a Sharpe by the size of the parameter
grid it searched. But a tournament over 8 coins × 4 timeframes × 9 strategies has
tried *thousands* of configurations, and the winner is the maximum of thousands
of draws. Deflating it by its own little grid of 6 is self-flattery. So
:func:`run_tournament` counts every configuration it evaluated anywhere and
re-deflates the leaderboard against that total. A strategy that looks brilliant
against 6 trials and vanishes against 1,400 was never an edge — it was the
right-hand tail of a lot of noise.

Three independent verdicts are produced, because any one of them can be fooled:

  * **Deflated Sharpe (tournament-wide)** — is the Sharpe big enough given how
    many things were tried?
  * **PBO via CSCV** — when the in-sample winner is selected, does it stay above
    median out-of-sample, or is the selection itself noise?
  * **Stationary-bootstrap p-value** — is the mean out-of-sample return
    distinguishable from zero once serial dependence is respected?

A result is only called an edge if all three agree. That is a deliberately high
bar, and the expected outcome is that almost nothing clears it.
"""
from __future__ import annotations

import itertools
import logging
import math
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

from app.eval.scorecard import _skew_kurt, deflated_sharpe_ratio, sharpe
from app.quant import backtest as bt
from app.quant import metrics as mx
from app.quant.exchange import BARS_PER_YEAR, Candles, ExchangeError, fetch_candles

log = logging.getLogger("fincoach.quant.tournament")

#: Liquid, independently-traded majors and large alts. Deliberately not the
#: top-8 by return — that would be survivorship selection baked into the design.
DEFAULT_SYMBOLS = ("BTC", "ETH", "SOL", "XRP", "DOGE", "LINK", "AVAX", "ADA")
DEFAULT_TIMEFRAMES = ("15m", "30m", "1h", "4h")

#: Deeper history at fast timeframes; 4h is limited by listing age, not by us.
BARS_WANTED: dict[str, int] = {"15m": 9000, "30m": 9000, "1h": 9000, "4h": 6000}

#: Taker fee + slippage per side, in bps. OKX/Binance spot taker is ~10bps at the
#: base tier; 5bps of slippage is generous for a small clip in BTC/ETH and thin
#: for a mid-cap alt in a fast tape. A round trip therefore costs ~30bps, which
#: is the number every result below has to clear.
DEFAULT_COSTS = bt.Costs(fee_bps=10.0, slippage_bps=5.0)

_MIN_BARS = 400

#: Nothing in crypto delivers a gross Sharpe above this at intraday frequency,
#: so a configuration needing more than this just to cover costs is dead on
#: arrival — measured, not fitted.
MAX_BREAKEVEN_SHARPE = 1.5
#: …or that is bleeding this much of the notional per year in pure friction.
MAX_ANNUAL_COST_DRAG = 0.30


def grid_for(strategy: str, timeframe: str) -> dict[str, list[Any]]:
    """Parameter grid scaled to the bar size.

    The defaults in ``backtest.PARAM_GRIDS`` are daily-oriented — a 252-bar
    lookback is a year on daily bars and two and a half days on 15m bars. These
    grids are expressed in BARS chosen so each timeframe covers a comparable
    span of market time, and are kept small on purpose: every extra combination
    raises the bar the result must clear.
    """
    fast_tf = timeframe in ("15m", "30m")
    # The no-trade band. At 15m a 30bps round trip is ~2x the one-bar sigma, so
    # an unfiltered rule pays away more than it can earn; requiring a target to
    # persist before acting on it is what makes a fast timeframe tradable at
    # all. 1 is the identity, so the unfiltered variant is always in the grid
    # and stays directly comparable.
    band = [1, 4, 12] if fast_tf else [1, 2, 6]
    grids: dict[str, dict[str, list[Any]]] = {
        "sma_cross": {"fast": [20, 50], "slow": [100, 200], "confirm_bars": band},
        "ema_cross": {"fast": [8, 21], "slow": [55, 100], "confirm_bars": band},
        "macd": {"fast": [12], "slow": [26], "signal": [9]},
        "rsi_reversion": {
            "period": [14], "low": [20.0, 30.0], "high": [70.0, 80.0],
            "min_hold_bars": band,
        },
        "tsmom": {"lookback": [48, 96, 192] if fast_tf else [12, 24, 48], "confirm_bars": band},
        "donchian": {"lookback": [55, 100] if fast_tf else [20, 55], "confirm_bars": band},
        "bollinger_reversion": {"period": [20, 50], "k": [2.0, 2.5], "min_hold_bars": band},
        "vol_regime_tsmom": {
            "lookback": [24, 48] if fast_tf else [6, 12],
            "vol_window": [96] if fast_tf else [48],
            "vol_quantile": [0.4, 0.6],
        },
        "buy_hold": {},
    }
    return grids.get(strategy, bt.PARAM_GRIDS.get(strategy, {}))


def grid_size(strategy: str, timeframe: str) -> int:
    grid = grid_for(strategy, timeframe)
    if not grid:
        return 1
    return int(np.prod([len(v) for v in grid.values()]))


def _combos(grid: dict[str, list[Any]]) -> list[dict[str, Any]]:
    if not grid:
        return [{}]
    keys = sorted(grid)
    return [
        dict(zip(keys, vals, strict=True))
        for vals in itertools.product(*(grid[k] for k in keys))
    ]


@dataclass
class CellResult:
    """One (symbol, timeframe, strategy) evaluation."""

    symbol: str
    timeframe: str
    strategy: str
    variant: str          # "long_flat" | "long_short"
    n_bars: int
    n_configs: int
    source: str
    buy_hold_return_pct: float | None = None
    # Full-sample best (in-sample — reported only to show the gap to OOS)
    best_params: dict[str, Any] = field(default_factory=dict)
    is_return_pct: float | None = None
    is_sharpe_ann: float | None = None
    # Walk-forward out-of-sample — the number that counts
    oos_ok: bool = False
    oos_reason: str | None = None
    oos_return_pct: float | None = None
    oos_sharpe_ann: float | None = None
    oos_sortino: float | None = None
    oos_max_dd_pct: float | None = None
    oos_bars: int = 0
    oos_trades: int = 0
    #: Buy & hold over EXACTLY the out-of-sample bars — the only fair benchmark.
    oos_buy_hold_return_pct: float | None = None
    oos_cost_drag_pct: float | None = None
    dsr_local: float | None = None
    n_infeasible: int = 0
    infeasible_examples: list[dict[str, Any]] = field(default_factory=list)
    shape: dict[str, float | None] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def feasibility(
    held: np.ndarray, asset_returns: np.ndarray, costs: bt.Costs, ppy: float
) -> dict[str, Any]:
    """What GROSS annualised Sharpe this configuration must earn just to break even.

    Pure arithmetic on the position path — no fitting, microseconds per combo.
    A rule that flips every other bar at 15-minute frequency has to clear a
    gross Sharpe of ~10 before costs to end up at zero, and nothing in crypto
    delivers that. Screening those cells out BEFORE the walk-forward does two
    good things at once: it saves the compute, and it shrinks the trial count
    that every surviving cell's Deflated Sharpe is deflated against.

    Rejecting on arithmetic is also the one kind of rejection that cannot be
    accused of data mining: it does not look at whether the rule made money.
    """
    if held.size < 10 or asset_returns.size != held.size:
        return {"feasible": False, "reason": "too few bars"}
    prev = np.concatenate(([0.0], held[:-1]))
    flips_per_bar = float(np.mean(np.abs(held - prev)))
    ann_cost = flips_per_bar * ppy * costs.per_turn
    exposure = float(np.sqrt(np.mean(held ** 2)))
    asset_ann_vol = float(np.std(asset_returns, ddof=1)) * math.sqrt(ppy)
    strat_ann_vol = asset_ann_vol * max(exposure, 1e-9)
    breakeven = ann_cost / max(strat_ann_vol, 1e-9)
    avg_hold = 1.0 / max(flips_per_bar, 1e-12)

    reason = None
    if breakeven > MAX_BREAKEVEN_SHARPE:
        reason = f"needs a gross Sharpe of {breakeven:.1f} just to cover costs"
    elif ann_cost > MAX_ANNUAL_COST_DRAG:
        reason = f"{ann_cost:.0%}/yr of pure cost drag"
    return {
        "feasible": reason is None,
        "reason": reason,
        "breakeven_gross_sharpe": round(breakeven, 3),
        "annual_cost_drag": round(ann_cost, 4),
        "avg_holding_bars": round(avg_hold, 2),
        "flips_per_bar": round(flips_per_bar, 5),
    }


def _net_returns(
    candles: Candles, strategy: str, params: dict[str, Any], costs: bt.Costs,
    *, allow_short: bool = False,
) -> tuple[np.ndarray, int]:
    """Per-bar net returns for one configuration over the whole series."""
    raw, warmup = bt.build_positions(
        strategy, candles.closes, candles.highs, candles.lows, params,
        allow_short=allow_short,
    )
    res = bt.run_backtest(candles.closes, raw, costs=costs, warmup=warmup)
    return res.bar_returns, res.n_trades


def evaluate_cell(
    candles: Candles,
    strategy: str,
    *,
    costs: bt.Costs = DEFAULT_COSTS,
    n_folds: int = 5,
    embargo: int = 24,
    allow_short: bool = False,
) -> tuple[CellResult, list[np.ndarray], np.ndarray, np.ndarray]:
    """Walk-forward one strategy on one series.

    Returns ``(cell, per-config series for the PBO test, out-of-sample returns,
    buy & hold over those same bars)``. The out-of-sample series comes straight
    out of ``walk_forward`` rather than being recomputed, so the leaderboard's
    bootstrap and shape metrics can never drift from the metrics the fold logic
    reported.
    """
    ppy = BARS_PER_YEAR.get(candles.timeframe, 365.25)
    grid = grid_for(strategy, candles.timeframe)
    combos = _combos(grid)
    cell = CellResult(
        symbol=candles.symbol, timeframe=candles.timeframe, strategy=strategy,
        variant="long_short" if allow_short else "long_flat",
        n_bars=len(candles), n_configs=len(combos), source=candles.source,
    )

    bh_raw, _ = bt.build_positions("buy_hold", candles.closes)
    bh = bt.run_backtest(candles.closes, bh_raw, costs=costs)
    cell.buy_hold_return_pct = round(bh.net_total_return * 100.0, 3)

    from app.quant.data import to_returns as _to_returns  # noqa: PLC0415

    asset_r = _to_returns(candles.closes)
    trial_series: list[np.ndarray] = []
    feasible_combos: list[dict[str, Any]] = []
    infeasible: list[dict[str, Any]] = []
    best_sr, best_params, best_ret = None, {}, None
    for params in combos:
        try:
            rets, _ = _net_returns(candles, strategy, params, costs, allow_short=allow_short)
        except Exception as exc:  # noqa: BLE001 — one bad config must not kill the cell
            log.info("cell %s/%s/%s config %s failed: %s",
                     candles.symbol, candles.timeframe, strategy, params, exc)
            continue
        if rets.size < 50:
            continue
        held = bt.align_positions(
            bt.build_positions(
                strategy, candles.closes, candles.highs, candles.lows, params,
                allow_short=allow_short,
            )[0]
        )
        feas = feasibility(held, asset_r, costs, ppy)
        if not feas["feasible"]:
            infeasible.append({"params": params, **feas})
            continue
        feasible_combos.append(params)
        trial_series.append(rets)
        sr = sharpe([float(x) for x in rets])
        if sr is not None and (best_sr is None or sr > best_sr):
            best_sr, best_params = sr, params
            best_ret = float(np.prod(1.0 + rets) - 1.0)

    cell.n_infeasible = len(infeasible)
    cell.infeasible_examples = infeasible[:3]
    cell.best_params = best_params
    if not feasible_combos:
        cell.oos_reason = (
            "every parameter set fails the cost-feasibility screen: "
            + (infeasible[0]["reason"] if infeasible else "unknown")
        )
        return cell, trial_series, np.asarray([]), np.asarray([])
    cell.is_return_pct = round(best_ret * 100.0, 3) if best_ret is not None else None
    cell.is_sharpe_ann = round(best_sr * math.sqrt(ppy), 4) if best_sr is not None else None

    feasible_grid = {
        k: sorted({c[k] for c in feasible_combos}) for k in (grid or {})
    } if grid else {}
    wf = bt.walk_forward(
        candles.closes, strategy,
        highs=candles.highs, lows=candles.lows, grid=feasible_grid,
        n_folds=n_folds, embargo=embargo, costs=costs, ppy=ppy,
        allow_short=allow_short,
        min_test_bars=max(60, len(candles) // (n_folds * 4)),
        return_series=True,
    )
    oos_series = np.asarray(wf.pop("oos_returns", []), dtype=float)
    bench_series = np.asarray(wf.pop("benchmark_returns", []), dtype=float)
    if wf.get("ok"):
        cell.oos_ok = True
        cell.oos_buy_hold_return_pct = wf.get("benchmark_return_pct")
        cell.oos_return_pct = wf["oos_return_pct"]
        cell.oos_sharpe_ann = wf["oos_sharpe_annualized"]
        cell.oos_sortino = wf["oos_sortino"]
        cell.oos_max_dd_pct = wf["oos_max_drawdown_pct"]
        cell.oos_bars = wf["oos_bars"]
        cell.dsr_local = wf["oos_dsr"]
    else:
        cell.oos_reason = wf.get("reason")

    if oos_series.size > 20:
        cell.shape = mx.summary(oos_series)
    return cell, trial_series, oos_series, bench_series


def run_tournament(
    symbols: tuple[str, ...] = DEFAULT_SYMBOLS,
    timeframes: tuple[str, ...] = DEFAULT_TIMEFRAMES,
    strategies: tuple[str, ...] | None = None,
    *,
    costs: bt.Costs = DEFAULT_COSTS,
    n_folds: int = 5,
    embargo: int = 24,
    use_cache: bool = True,
    include_short: bool = True,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Run the full grid and rank what survives.

    Every configuration evaluated anywhere in the run counts toward the
    multiple-testing correction applied to the leaderboard.
    """
    strategies = strategies or tuple(k for k in bt.SIGNALS if k != "buy_hold")
    # Long/flat cannot win in a downtrend — it can only lose less. Testing the
    # long/short variant is what makes "which strategy is profitable" answerable
    # in a falling market, and both variants count toward the trial total.
    variants: tuple[bool, ...] = (False, True) if include_short else (False,)
    started = time.time()
    cells: list[CellResult] = []
    oos_by_key: dict[str, np.ndarray] = {}
    pbo_by_series: dict[str, Any] = {}
    fetch_errors: list[str] = []
    rejected: dict[str, Any] = {}
    total_trials = 0

    def _say(msg: str) -> None:
        log.info(msg)
        if progress:
            progress(msg)

    for timeframe in timeframes:
        for symbol in symbols:
            key = f"{symbol}/{timeframe}"
            try:
                candles = fetch_candles(
                    symbol, timeframe, BARS_WANTED.get(timeframe, 5000), use_cache=use_cache
                )
            except ExchangeError as exc:
                fetch_errors.append(f"{key}: {exc}")
                _say(f"  {key}: no data — {exc}")
                continue
            if len(candles) < _MIN_BARS:
                fetch_errors.append(f"{key}: only {len(candles)} bars")
                continue
            # A stale or frozen book produces spectacular mean-reversion
            # backtests that are pure bid-ask bounce. Skipping loudly beats
            # crowning an untradeable series — see exchange.assess.
            if not candles.tradeable:
                why = "; ".join(candles.quality.reasons) if candles.quality else "unknown"
                rejected[key] = {
                    "source": candles.source,
                    "reasons": candles.quality.reasons if candles.quality else [],
                    "quality": candles.quality.as_dict() if candles.quality else None,
                }
                _say(f"  {key}: REJECTED ({candles.source}) — {why}")
                continue

            series_for_pbo: list[np.ndarray] = []
            for strategy in strategies:
                for allow_short in variants:
                    variant = "long_short" if allow_short else "long_flat"
                    cell, trials, oos, _bench = evaluate_cell(
                        candles, strategy, costs=costs, n_folds=n_folds,
                        embargo=embargo, allow_short=allow_short,
                    )
                    cells.append(cell)
                    total_trials += cell.n_configs
                    series_for_pbo.extend(trials)
                    if cell.oos_ok and oos.size > 20:
                        oos_by_key[f"{key}/{strategy}/{variant}"] = oos

            if series_for_pbo:
                width = min(len(s) for s in series_for_pbo)
                if width >= 200 and len(series_for_pbo) >= 4:
                    matrix = np.column_stack([s[-width:] for s in series_for_pbo])
                    pbo_by_series[key] = mx.probability_of_backtest_overfitting(matrix)

            q = candles.quality
            _say(
                f"  {key}: {len(candles)} bars from {candles.source}"
                + (f" (stale {q.stale_fraction:.0%}, range {q.median_range_pct:.3f}%)" if q else "")
            )

    leaderboard = _rank(
        cells, oos_by_key, total_trials,
        {tf: BARS_PER_YEAR.get(tf, 365.25) for tf in timeframes},
    )
    verdict = _verdict(leaderboard, pbo_by_series, total_trials, len(rejected))
    return {
        "ok": True,
        "generated_at": int(time.time()),
        "elapsed_sec": round(time.time() - started, 1),
        "symbols": list(symbols),
        "timeframes": list(timeframes),
        "strategies": list(strategies),
        "costs": {
            "fee_bps": costs.fee_bps,
            "slippage_bps": costs.slippage_bps,
            "round_trip_bps": round((costs.fee_bps + costs.slippage_bps) * 2, 2),
        },
        "total_configurations_tested": total_trials,
        "n_cells": len(cells),
        "n_rejected_series": len(rejected),
        "fetch_errors": fetch_errors,
        "rejected_for_data_quality": rejected,
        "cells": [c.as_dict() for c in cells],
        "leaderboard": leaderboard,
        "pbo": pbo_by_series,
        "verdict": verdict,
    }


def _rank(
    cells: list[CellResult], oos_by_key: dict[str, np.ndarray], total_trials: int,
    ppy_by_tf: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """Leaderboard, deflated against the WHOLE tournament and bootstrap-tested.

    The tournament-wide deflation needs the spread of Sharpe ratios ACROSS the
    whole search, in per-bar units. Passing the library default of 1.0 puts the
    benchmark at an annualised Sharpe of several hundred and pins every DSR at
    exactly 0.0 — a survivor gate that can never fire. See
    ``backtest.trial_variance``.
    """
    ppy_by_tf = ppy_by_tf or {}
    per_bar_sharpes: list[float] = []
    for cell in cells:
        key = f"{cell.symbol}/{cell.timeframe}/{cell.strategy}/{cell.variant}"
        oos = oos_by_key.get(key)
        if oos is not None and oos.size >= 50:
            s = sharpe([float(x) for x in oos])
            if s is not None:
                per_bar_sharpes.append(s)
    tournament_variance = (
        float(np.var(np.asarray(per_bar_sharpes), ddof=1))
        if len(per_bar_sharpes) >= 2 else 0.0
    )

    rows: list[dict[str, Any]] = []
    for cell in cells:
        if not cell.oos_ok or cell.oos_return_pct is None:
            continue
        key = f"{cell.symbol}/{cell.timeframe}/{cell.strategy}/{cell.variant}"
        oos = oos_by_key.get(key)
        if oos is None or oos.size < 50:
            continue

        r = [float(x) for x in oos]
        sr = sharpe(r)
        if sr is None:
            continue
        skew, kurt = _skew_kurt(r)
        ppy = ppy_by_tf.get(cell.timeframe) or BARS_PER_YEAR.get(cell.timeframe, 365.25)
        variance_trials = tournament_variance or (0.5 / math.sqrt(ppy)) ** 2
        dsr_global = deflated_sharpe_ratio(
            sr, len(r), skew, kurt, max(1, total_trials), variance_trials=variance_trials
        )
        boot = mx.bootstrap_pvalue(oos, n_boot=1500)
        # Compare against buy & hold over the SAME out-of-sample bars, never the
        # full-sample figure — different windows would make the excess meaningless.
        beats_bh = (
            cell.oos_return_pct - cell.oos_buy_hold_return_pct
            if cell.oos_buy_hold_return_pct is not None else None
        )

        rows.append({
            "key": key,
            "symbol": cell.symbol,
            "timeframe": cell.timeframe,
            "strategy": cell.strategy,
            "variant": cell.variant,
            "best_params": cell.best_params,
            "oos_return_pct": cell.oos_return_pct,
            "oos_buy_hold_return_pct": cell.oos_buy_hold_return_pct,
            "excess_vs_buy_hold_pct": round(beats_bh, 3) if beats_bh is not None else None,
            "oos_sharpe_ann": cell.oos_sharpe_ann,
            "oos_sortino": cell.oos_sortino,
            "oos_max_dd_pct": cell.oos_max_dd_pct,
            "oos_bars": cell.oos_bars,
            "dsr_local": cell.dsr_local,
            "dsr_tournament": round(dsr_global, 4) if dsr_global is not None else None,
            "trial_sharpe_variance": round(variance_trials, 12),
            "bootstrap_p": boot["p_value"] if boot else None,
            "omega": cell.shape.get("omega"),
            "ulcer_index": cell.shape.get("ulcer_index"),
            "survives": bool(
                dsr_global is not None and dsr_global > 0.95
                and boot is not None and boot["significant_5pct"]
                and cell.oos_return_pct > 0
            ),
        })

    rows.sort(key=lambda r: (r["dsr_tournament"] or 0.0, r["oos_sharpe_ann"] or 0.0), reverse=True)
    return rows


def _verdict(
    leaderboard: list[dict[str, Any]], pbo: dict[str, Any], total_trials: int,
    n_rejected: int = 0,
) -> dict[str, Any]:
    """The honest headline. A null result is a result."""
    survivors = [r for r in leaderboard if r["survives"]]
    positive = [r for r in leaderboard if (r["oos_return_pct"] or 0) > 0]
    beat_bh = [r for r in leaderboard if (r["excess_vs_buy_hold_pct"] or 0) > 0]
    pbos = [v["pbo"] for v in pbo.values() if v and "pbo" in v]

    return {
        "n_evaluated": len(leaderboard),
        "n_rejected_series": n_rejected,
        "n_positive_oos": len(positive),
        "n_beat_buy_hold": len(beat_bh),
        "n_survivors": len(survivors),
        "total_configurations_tested": total_trials,
        "median_pbo": round(float(np.median(pbos)), 4) if pbos else None,
        "survivors": [r["key"] for r in survivors],
        "headline": (
            f"{len(survivors)} of {len(leaderboard)} evaluated strategy cells cleared all three "
            f"tests (tournament-deflated Sharpe, bootstrap significance, positive out-of-sample "
            f"return) after {total_trials} configurations were tried."
            + (
                " A zero count is the expected outcome and is reported as such — it means no "
                "rule in this search beat ~30bps round-trip costs at these timeframes on this "
                "sample, not that the pipeline failed."
                if not survivors else ""
            )
        ),
    }
