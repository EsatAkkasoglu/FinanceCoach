#!/usr/bin/env python
"""One cycle of the multi-timeframe crypto strategy experiment.

Designed to be run repeatedly on a schedule. Each invocation:

  1. refreshes 15m/30m/1h/4h candles for the coin universe (incremental — the
     disk cache is extended, not re-downloaded),
  2. optionally re-runs the full strategy tournament (expensive, so only every
     ``--tournament-every`` cycles),
  3. re-selects what the paper book should hold,
  4. advances the paper book one step and marks it to market,
  5. records market context — fear & greed, headline count — alongside the row.

The design commitment worth stating: the tournament is *selection*, the paper
book is *evidence*. Nothing selected in step 3 has proven an edge; the whole
point of steps 4-5 is to run those choices forward on bars that did not exist
when the choice was made. A backtest can be re-run until it flatters you. A
forward log cannot.

Usage:
    uv run python scripts/run_experiment.py --cycle              # one step
    uv run python scripts/run_experiment.py --tournament         # force a re-rank
    uv run python scripts/run_experiment.py --report             # print status
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.quant import paper  # noqa: E402
from app.quant import tournament as tn  # noqa: E402
from app.quant.paper import Allocation  # noqa: E402
from app.services import rapidapi  # noqa: E402

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
log = logging.getLogger("experiment")

DATA_DIR = paper.DATA_DIR
TOURNAMENT_PATH = os.path.join(DATA_DIR, "tournament_latest.json")
HISTORY_PATH = os.path.join(DATA_DIR, "tournament_history.jsonl")

#: How many strategy cells the paper book runs forward at once. Small on purpose:
#: spreading a fixed book across 20 rules guarantees the average, which answers
#: nothing about whether any single rule works.
N_ALLOCATIONS = 6

#: Re-rank every N cycles. The tournament takes minutes and its inputs barely
#: move in 30 minutes, so re-running it every cycle would burn time to reproduce
#: the same leaderboard — and would tempt the book into churning on noise.
DEFAULT_TOURNAMENT_EVERY = 8


# ── market context ───────────────────────────────────────────────────────────


def resolve_universe(n: int = 8) -> tuple[tuple[str, ...], str]:
    """Pick the coin universe from market-cap data when it is reachable.

    Hand-picking coins bakes the author's priors into the result before a single
    backtest runs. Ranking by market cap and 24h volume is still a choice, but
    it is a stated, repeatable one. Falls back to the fixed list when the vendor
    is unsubscribed or down — and says which it used, because a silently
    different universe would make two cycles incomparable.
    """
    try:
        universe = rapidapi.liquid_universe(n=n)
    except Exception as exc:  # noqa: BLE001
        log.info("universe lookup failed: %s", exc)
        universe = []
    if len(universe) >= 4:
        return tuple(universe), "coinranking:marketcap"
    return tn.DEFAULT_SYMBOLS, "static-default"


def market_context() -> dict[str, Any]:
    """Fear & greed plus a headline sample. Best-effort — never blocks a cycle."""
    ctx: dict[str, Any] = {}
    try:
        import requests  # noqa: PLC0415

        r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=12)
        data = (r.json() or {}).get("data") or []
        if data:
            ctx["fear_greed"] = int(data[0]["value"])
            ctx["fear_greed_label"] = data[0]["value_classification"]
    except Exception as exc:  # noqa: BLE001
        ctx["fear_greed_error"] = f"{type(exc).__name__}"

    try:
        import feedparser  # noqa: PLC0415
        import requests  # noqa: PLC0415

        r = requests.get(
            "https://www.coindesk.com/arc/outboundfeeds/rss/",
            timeout=12, headers={"User-Agent": "Mozilla/5.0"},
        )
        feed = feedparser.parse(r.content)
        ctx["headlines"] = [e.title[:140] for e in feed.entries[:5]]
    except Exception as exc:  # noqa: BLE001
        ctx["news_error"] = f"{type(exc).__name__}"

    try:
        ctx["trending"] = rapidapi.trending_coins(limit=10)
    except Exception:  # noqa: BLE001
        pass
    return ctx


# ── tournament + selection ───────────────────────────────────────────────────


def run_and_store_tournament(**kwargs: Any) -> dict[str, Any]:
    result = tn.run_tournament(progress=lambda m: log.info(m), **kwargs)
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(TOURNAMENT_PATH, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=1)
    with open(HISTORY_PATH, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "ts": result["generated_at"],
            "elapsed_sec": result["elapsed_sec"],
            "total_configurations_tested": result["total_configurations_tested"],
            "verdict": result["verdict"],
            "top": result["leaderboard"][:10],
        }) + "\n")
    return result


def load_tournament() -> dict[str, Any] | None:
    if not os.path.exists(TOURNAMENT_PATH):
        return None
    try:
        with open(TOURNAMENT_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001
        return None


def select_allocations(result: dict[str, Any], n: int = N_ALLOCATIONS) -> list[Allocation]:
    """Choose what to run forward.

    Ranking is by out-of-sample Sharpe, NOT by out-of-sample total return. In a
    falling market the highest-return rule is usually the one that was flat the
    longest, which says nothing about skill; Sharpe at least asks what was earned
    per unit of risk taken.

    Survivors of the full three-test bar are preferred when any exist. When none
    do — the expected case — the top Sharpe cells are run forward anyway and
    flagged ``selected_without_significance``. That is the honest experiment:
    the backtest could not resolve an edge, so the forward log is asked to.
    """
    board = [r for r in result.get("leaderboard", []) if r.get("oos_sharpe_ann") is not None]
    if not board:
        return []

    survivors = [r for r in board if r.get("survives")]
    pool = survivors or board
    ranked = sorted(pool, key=lambda r: r["oos_sharpe_ann"], reverse=True)

    # At most one cell per symbol: six rules on BTC is one bet, not six.
    chosen: list[dict[str, Any]] = []
    seen_symbols: set[str] = set()
    for row in ranked:
        if row["symbol"] in seen_symbols:
            continue
        chosen.append(row)
        seen_symbols.add(row["symbol"])
        if len(chosen) >= n:
            break

    weight = 1.0 / max(1, len(chosen))
    return [
        Allocation(
            symbol=row["symbol"],
            timeframe=row["timeframe"],
            strategy=row["strategy"],
            variant=row.get("variant", "long_flat"),
            params=row.get("best_params") or {},
            weight=weight,
            selected_on={
                "oos_sharpe_ann": row["oos_sharpe_ann"],
                "oos_return_pct": row["oos_return_pct"],
                "oos_buy_hold_return_pct": row.get("oos_buy_hold_return_pct"),
                "excess_vs_buy_hold_pct": row.get("excess_vs_buy_hold_pct"),
                "dsr_tournament": row.get("dsr_tournament"),
                "bootstrap_p": row.get("bootstrap_p"),
                "selected_without_significance": not row.get("survives"),
            },
        )
        for row in chosen
    ]


# ── cycle ────────────────────────────────────────────────────────────────────


def cycle(force_tournament: bool = False, tournament_every: int = DEFAULT_TOURNAMENT_EVERY,
          **tn_kwargs: Any) -> dict[str, Any]:
    started = time.time()
    state = paper.load_state()
    cycle_no = int(state.get("cycle", 0)) + 1

    result = load_tournament()
    due = force_tournament or result is None or (cycle_no - 1) % tournament_every == 0
    if due:
        if "symbols" not in tn_kwargs:
            universe, source = resolve_universe()
            tn_kwargs = {**tn_kwargs, "symbols": universe}
            log.info("cycle %d: universe from %s -> %s", cycle_no, source, ",".join(universe))
        log.info("cycle %d: running tournament", cycle_no)
        result = run_and_store_tournament(**tn_kwargs)
    else:
        log.info("cycle %d: reusing tournament from %s", cycle_no, result.get("generated_at"))

    allocations = select_allocations(result)
    if not allocations:
        log.warning("cycle %d: no allocations selected", cycle_no)

    ctx = market_context()
    ctx["tournament_generated_at"] = result.get("generated_at")
    ctx["tournament_verdict"] = result.get("verdict", {}).get("headline")
    ctx["n_survivors"] = result.get("verdict", {}).get("n_survivors")
    ctx["allocations"] = [
        {"key": a.key, "weight": round(a.weight, 4), **a.selected_on} for a in allocations
    ]

    row = paper.run_cycle(allocations, costs=tn.DEFAULT_COSTS, state=state, context=ctx)
    row["cycle_seconds"] = round(time.time() - started, 1)
    log.info(
        "cycle %d done in %.1fs — equity %.2f (%.3f%%), %d trades, fg=%s",
        row["cycle"], row["cycle_seconds"], row["equity"], row["return_pct"],
        len(row["trades"]), ctx.get("fear_greed"),
    )
    return row


def report() -> dict[str, Any]:
    result = load_tournament() or {}
    perf = paper.performance()
    state = paper.load_state()
    return {
        "paper": perf,
        "book": {
            "cycle": state.get("cycle"),
            "equity": state.get("equity"),
            "n_trades": state.get("n_trades"),
            "fees_paid": round(float(state.get("fees_paid", 0.0)), 4),
            "allocations": [a.get("symbol") for a in state.get("allocations", [])],
        },
        "tournament": {
            "generated_at": result.get("generated_at"),
            "total_configurations_tested": result.get("total_configurations_tested"),
            "verdict": result.get("verdict"),
            "top5": [
                {
                    k: r.get(k) for k in (
                        "key", "oos_return_pct", "oos_buy_hold_return_pct",
                        "excess_vs_buy_hold_pct", "oos_sharpe_ann",
                        "dsr_tournament", "bootstrap_p", "survives",
                    )
                }
                for r in (result.get("leaderboard") or [])[:5]
            ],
            "median_pbo": (result.get("verdict") or {}).get("median_pbo"),
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cycle", action="store_true", help="advance the experiment one step")
    ap.add_argument("--tournament", action="store_true", help="force a tournament re-run")
    ap.add_argument("--report", action="store_true", help="print current status as JSON")
    ap.add_argument("--symbols", default="", help="comma-separated override")
    ap.add_argument("--timeframes", default="", help="comma-separated override")
    ap.add_argument("--tournament-every", type=int, default=DEFAULT_TOURNAMENT_EVERY)
    args = ap.parse_args()

    tn_kwargs: dict[str, Any] = {}
    if args.symbols:
        tn_kwargs["symbols"] = tuple(s.strip().upper() for s in args.symbols.split(",") if s.strip())
    if args.timeframes:
        tn_kwargs["timeframes"] = tuple(t.strip() for t in args.timeframes.split(",") if t.strip())

    if args.report:
        print(json.dumps(report(), indent=1))
        return 0
    if args.tournament and not args.cycle:
        result = run_and_store_tournament(**tn_kwargs)
        print(json.dumps(result["verdict"], indent=1))
        return 0

    row = cycle(
        force_tournament=args.tournament,
        tournament_every=args.tournament_every,
        **tn_kwargs,
    )
    print(json.dumps({k: v for k, v in row.items() if k != "context"}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
