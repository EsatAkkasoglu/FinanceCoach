#!/usr/bin/env python
"""A/B the calendar alignment — the only thing that differs between the arms.

The last time this experiment reported a change between runs, the change came
from my own edits rather than from the thing being studied. So the alignment
claim gets a controlled test: identical universe, identical code, identical
cached candles, one flag flipped.
"""
from __future__ import annotations

import json
import os
import statistics as st
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.quant.tournament import DEFAULT_SYMBOLS, DEFAULT_TIMEFRAMES, run_tournament  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "experiment")


def table(result: dict) -> dict[str, dict]:
    by = defaultdict(list)
    for r in result["leaderboard"]:
        by[r["timeframe"]].append(r)
    out = {}
    for tf in DEFAULT_TIMEFRAMES:
        rs = by.get(tf) or []
        if not rs:
            continue
        out[tf] = {
            "n": len(rs),
            "median_sharpe": round(st.median([r["oos_sharpe_ann"] for r in rs]), 3),
            "positive": sum(1 for r in rs if r["oos_return_pct"] > 0),
            "beat_bh": sum(1 for r in rs if r["oos_return_pct"] > r["oos_buy_hold_return_pct"]),
            "median_return": round(st.median([r["oos_return_pct"] for r in rs]), 2),
            "median_bh": round(st.median([r["oos_buy_hold_return_pct"] for r in rs]), 2),
            "median_bars": int(st.median([r["oos_bars"] for r in rs])),
        }
    return out


def main() -> None:
    arms = {}
    for name, aligned in (("aligned", True), ("unaligned", False)):
        print(f"\n{'=' * 70}\n{name.upper()}  (align_calendar={aligned})\n{'=' * 70}", flush=True)
        res = run_tournament(
            DEFAULT_SYMBOLS, DEFAULT_TIMEFRAMES,
            align_calendar=aligned, use_cache=True,
            progress=lambda m: print(m, flush=True),
        )
        arms[name] = {
            "window": res.get("calendar_window"),
            "bars_by_timeframe": res.get("bars_by_timeframe"),
            "n_evaluated": len(res["leaderboard"]),
            "table": table(res),
            "verdict": res["verdict"],
            "median_pbo": res["verdict"].get("median_pbo"),
        }

    with open(os.path.join(OUT, "ab_alignment.json"), "w", encoding="utf-8") as fh:
        json.dump(arms, fh, indent=1)

    print(f"\n{'=' * 78}")
    print(f"{'tf':>4} | {'HİZALI: gün  medSh  poz  altut':>34} | {'HİZASIZ: gün  medSh  poz  altut':>34}")
    print("-" * 78)
    for tf in DEFAULT_TIMEFRAMES:
        a = arms["aligned"]["table"].get(tf)
        u = arms["unaligned"]["table"].get(tf)
        if not a or not u:
            continue
        mins = {"15m": 15, "30m": 30, "1h": 60, "4h": 240}[tf]
        ad, ud = a["median_bars"] * mins / 1440, u["median_bars"] * mins / 1440
        print(
            f"{tf:>4} | {ad:>8.0f}d {a['median_sharpe']:>6.2f} {a['positive']:>3}/{a['n']:<3}"
            f" {a['beat_bh']:>3}/{a['n']:<3} | "
            f"{ud:>8.0f}d {u['median_sharpe']:>6.2f} {u['positive']:>3}/{u['n']:<3}"
            f" {u['beat_bh']:>3}/{u['n']:<3}"
        )
    print(
        f"\nPBO medyan — hizalı {arms['aligned']['median_pbo']} | "
        f"hizasız {arms['unaligned']['median_pbo']}"
    )


if __name__ == "__main__":
    main()
