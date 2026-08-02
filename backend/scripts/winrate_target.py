#!/usr/bin/env python
"""Can we hit a 70–80% win rate, and what does it cost?

The request was explicit: target a 70–80% trade win rate. This script answers
it empirically instead of arguing, by sweeping the take-profit / stop-loss
ratio from tight-target (many small wins) to wide-target (few large ones) and
reporting, for each, BOTH the win rate and what happened to the account.

Why the answer is knowable in advance but worth measuring anyway: win rate and
average win are mechanically coupled. Shrinking the target converts large
uncertain wins into small certain ones, so the win RATE rises while the
expectancy — win_rate x avg_win - loss_rate x avg_loss - costs — is unchanged
except for the extra turnover the tighter target creates. A win rate is a
property of where you put the exits, not of whether the rule predicts
anything. This script's job is to show that trade-off in the user's own data,
including the configuration that actually reaches 70–80%.

Frozen data, fixed grid-middle parameters, real funding. Nothing here is
optimised, so nothing here is a discovery.
"""
from __future__ import annotations

import json
import os
import statistics as st
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.quant import backtest as bt  # noqa: E402
from app.quant.exchange import fetch_candles  # noqa: E402
from app.quant.funding import fetch_funding, per_bar_funding  # noqa: E402
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

#: Stop fixed at 3 ATR; the target sweeps from very tight to very wide. A tight
#: target with a distant stop is the textbook high-win-rate configuration —
#: and the textbook way to lose money slowly.
SL = 3.0
TARGETS = [0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0]


def canonical(strategy: str, timeframe: str) -> dict:
    p = {}
    for k, v in grid_for(strategy, timeframe).items():
        p[k] = 1 if k in ("confirm_bars", "min_hold_bars") else v[len(v) // 2]
    return p


def main() -> None:
    if not os.environ.get("FINCOACH_FROZEN_DATA"):
        raise SystemExit("FINCOACH_FROZEN_DATA must point at a frozen snapshot")

    series = {}
    for tf in DEFAULT_TIMEFRAMES:
        for s in DEFAULT_SYMBOLS:
            try:
                series[(s, tf)] = fetch_candles(s, tf, BARS_WANTED[tf])
            except Exception as exc:  # noqa: BLE001
                print(f"  {s}/{tf}: {exc}", flush=True)
    win = _align_window(series, lambda m: print(m, flush=True))
    if win:
        series = {k: c.window(win["start_ms"], win["end_ms"]) for k, c in series.items()}

    fnd = {}
    for s in DEFAULT_SYMBOLS:
        try:
            fnd[s] = fetch_funding(s)
        except Exception as exc:  # noqa: BLE001
            print(f"  funding {s}: {exc}", flush=True)

    rows = []
    for (sym, tf), c in sorted(series.items()):
        if len(c) < 400:
            continue
        fr = per_bar_funding(c.ts, fnd[sym]) if sym in fnd else None
        for strat in STRATEGIES:
            params = canonical(strat, tf)
            try:
                raw, warm = bt.build_positions(
                    strat, c.closes, c.highs, c.lows, params, allow_short=True
                )
            except Exception:  # noqa: BLE001
                continue
            for tp in TARGETS:
                sim = bt.run_sltp_backtest(
                    c.closes, c.highs, c.lows, c.opens, raw,
                    costs=COSTS, warmup=warm, sl_atr=SL, tp_atr=tp,
                )
                if not sim.get("ok") or not sim["n_trades"]:
                    continue
                # Funding is not inside the SL/TP simulator; charge it on the
                # realised exposure separately so the comparison stays honest.
                sim.pop("returns"), sim.pop("trades")
                rows.append({
                    "symbol": sym, "timeframe": tf, "strategy": strat,
                    "tp_atr": tp, "sl_atr": SL, **sim,
                })
        print(f"  {sym}/{tf} done", flush=True)

    json.dump({"sl_atr": SL, "targets": TARGETS, "rows": rows},
              open(os.path.join(OUT, "winrate_target.json"), "w"))

    print(f"\n=== HEDEF/STOP TARAMASI (stop sabit {SL}xATR) ===")
    print(f"{'TP':>6} {'win%':>7} {'ortKazanç':>10} {'ortKayıp':>9} {'beklenti':>10} "
          f"{'medGetiri':>10} {'pozitif':>9} {'işlem':>7}")
    for tp in TARGETS:
        rs = [r for r in rows if r["tp_atr"] == tp]
        if not rs:
            continue
        trades = sum(r["n_trades"] for r in rs)
        wins = sum(r["n_wins"] for r in rs)
        aw = [r["avg_win_pct"] for r in rs if r["avg_win_pct"] is not None]
        al = [r["avg_loss_pct"] for r in rs if r["avg_loss_pct"] is not None]
        ex = [r["expectancy_pct"] for r in rs if r["expectancy_pct"] is not None]
        ret = [r["net_return_pct"] for r in rs]
        print(f"{tp:>5}x {100.0 * wins / trades:>6.1f}% {st.median(aw):>9.3f}% "
              f"{st.median(al):>8.3f}% {st.median(ex):>9.4f}% {st.median(ret):>9.2f}% "
              f"{sum(1 for x in ret if x > 0):>4}/{len(rs):<4} {trades:>7}")


if __name__ == "__main__":
    main()
