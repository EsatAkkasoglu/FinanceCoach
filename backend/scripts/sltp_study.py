#!/usr/bin/env python
"""Trade-level anatomy of stop-loss / take-profit, on the frozen data layer.

The question, as asked: put SL/TP on the rules and count wins and losses.

Design decisions that keep the answer honest:

* **Frozen data only** (FINCOACH_FROZEN_DATA is required) — the audit's first
  continuation condition.
* **Fixed canonical parameters** — the MIDDLE of each strategy's tournament
  grid, with the confirmation/hold band forced to 1. Nothing here is
  optimised, so no selection bias enters and no deflation is owed; the price
  is that these are typical parameters rather than the best ones.
* **The SL/TP grid is reported in full** — every variant on every cell, no
  cherry-picking. This is descriptive anatomy (what do stops do to the trade
  distribution), not a new search for an edge, and it must not be read as one.
* **Ambiguity is pessimistic and counted** — a bar spanning both levels is a
  stop, never a target.
* Long/short variant, aligned calendar window shared across timeframes.
"""
from __future__ import annotations

import json
import os
import statistics as st
import sys
from collections import defaultdict

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.quant import backtest as bt  # noqa: E402
from app.quant.exchange import BARS_PER_YEAR, fetch_candles  # noqa: E402
from app.quant.tournament import (  # noqa: E402
    BARS_WANTED,
    DEFAULT_SYMBOLS,
    DEFAULT_TIMEFRAMES,
    _align_window,
    grid_for,
)

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "experiment")
COSTS = bt.Costs(fee_bps=10.0, slippage_bps=5.0)
STRATEGIES = ("sma_cross", "ema_cross", "rsi_reversion", "macd",
              "tsmom", "donchian", "bollinger_reversion", "vol_regime_tsmom")

#: (label, sl_atr, tp_atr) — None disables that leg. Reported in full.
VARIANTS: list[tuple[str, float | None, float | None]] = [
    ("baseline", None, None),
    ("sl2", 2.0, None),
    ("sl1.5_tp3", 1.5, 3.0),
    ("sl2_tp4", 2.0, 4.0),
    ("sl2_tp2", 2.0, 2.0),
    ("sl3_tp6", 3.0, 6.0),
]


def canonical_params(strategy: str, timeframe: str) -> dict:
    """Middle of the tournament grid; hysteresis bands forced to the identity
    so the SL/TP effect is not confounded with the no-trade band."""
    params = {}
    for key, values in grid_for(strategy, timeframe).items():
        if key in ("confirm_bars", "min_hold_bars"):
            params[key] = 1
        else:
            params[key] = values[len(values) // 2]
    return params


def main() -> None:
    if not os.environ.get("FINCOACH_FROZEN_DATA"):
        raise SystemExit("FINCOACH_FROZEN_DATA must point at a frozen snapshot")

    series = {}
    for tf in DEFAULT_TIMEFRAMES:
        for sym in DEFAULT_SYMBOLS:
            try:
                series[(sym, tf)] = fetch_candles(sym, tf, BARS_WANTED[tf])
            except Exception as exc:  # noqa: BLE001
                print(f"  {sym}/{tf}: {exc}", flush=True)
    window = _align_window(series, lambda m: print(m, flush=True))
    if window:
        series = {
            k: c.window(window["start_ms"], window["end_ms"]) for k, c in series.items()
        }

    rows = []
    for (sym, tf), c in sorted(series.items()):
        if len(c) < 400:
            continue
        for strat in STRATEGIES:
            params = canonical_params(strat, tf)
            try:
                raw, warm = bt.build_positions(
                    strat, c.closes, c.highs, c.lows, params, allow_short=True
                )
            except Exception:  # noqa: BLE001
                continue
            for label, sl, tp in VARIANTS:
                sim = bt.run_sltp_backtest(
                    c.closes, c.highs, c.lows, c.opens, raw,
                    costs=COSTS, warmup=warm, sl_atr=sl, tp_atr=tp,
                )
                if not sim.get("ok"):
                    continue
                sim.pop("returns")
                sim.pop("trades")
                rows.append({
                    "symbol": sym, "timeframe": tf, "strategy": strat,
                    "variant": label, "params": params, **sim,
                })
        print(f"  {sym}/{tf} done", flush=True)

    with open(os.path.join(OUT, "sltp_study.json"), "w", encoding="utf-8") as fh:
        json.dump({
            "window": window,
            "costs_round_trip_bps": (COSTS.fee_bps + COSTS.slippage_bps) * 2,
            "variants": [v[0] for v in VARIANTS],
            "note": (
                "Fixed canonical parameters (grid middle, bands=1), long/short, "
                "frozen data. Descriptive trade anatomy — NOT an edge search; "
                "no variant here has passed, or been submitted to, the "
                "three-gate significance test."
            ),
            "rows": rows,
        }, fh)

    # ── aggregate report ────────────────────────────────────────────────────
    def agg(subset):
        trades = sum(r["n_trades"] for r in subset)
        wins = sum(r["n_wins"] for r in subset)
        rets = [r["net_return_pct"] for r in subset]
        pf = [r["profit_factor"] for r in subset if r["profit_factor"] is not None]
        amb = sum(r["ambiguous_bars"] for r in subset)
        stops = sum(r["exit_reasons"].get("stop", 0) for r in subset)
        targets = sum(r["exit_reasons"].get("target", 0) for r in subset)
        signals = sum(r["exit_reasons"].get("signal", 0) for r in subset)
        return {
            "cells": len(subset), "trades": trades,
            "win_pct": round(100.0 * wins / trades, 1) if trades else None,
            "median_net_return_pct": round(st.median(rets), 2) if rets else None,
            "positive_cells": sum(1 for x in rets if x > 0),
            "median_profit_factor": round(st.median(pf), 3) if pf else None,
            "exits_stop_target_signal": (stops, targets, signals),
            "ambiguous_bars": amb,
        }

    print("\n=== VARYANT BAZINDA (tüm hücreler) ===")
    by_var = defaultdict(list)
    for r in rows:
        by_var[r["variant"]].append(r)
    for label, _sl, _tp in VARIANTS:
        a = agg(by_var[label])
        print(f"{label:>12}: cells={a['cells']:>3} trades={a['trades']:>6} "
              f"win%={a['win_pct']:>5} medRet={a['median_net_return_pct']:>8}% "
              f"pos={a['positive_cells']:>3} PF={a['median_profit_factor']} "
              f"S/T/Sig={a['exits_stop_target_signal']} amb={a['ambiguous_bars']}")

    print("\n=== DİLİM × VARYANT (win% / medyan getiri%) ===")
    for tf in DEFAULT_TIMEFRAMES:
        parts = []
        for label, _sl, _tp in VARIANTS:
            sub = [r for r in rows if r["timeframe"] == tf and r["variant"] == label]
            a = agg(sub)
            parts.append(f"{label}:{a['win_pct']}%/{a['median_net_return_pct']}%")
        print(f"{tf:>4} | " + "  ".join(parts))


if __name__ == "__main__":
    main()
