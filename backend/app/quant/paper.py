"""Paper-trading ledger — the forward test the backtest cannot give us.

Why this exists, stated plainly: the tournament in :mod:`app.quant.tournament`
searches thousands of configurations and then reports that essentially nothing
clears a tournament-wide Deflated Sharpe. That is the correct result, but it is
also a *negative* one, and a negative in-sample result cannot distinguish
"no edge" from "an edge too small for this sample to resolve".

Forward paper trading can. Every bar this ledger trades on is data that did not
exist when the strategy was selected, so there is no selection bias to correct
for — no purging, no embargo, no deflation. It is the cleanest evidence
available, and it is also the slowest: eight hours of 15-minute bars is 32
observations, which is nowhere near enough to prove anything. The ledger is
therefore built to be *honest about its own sample size* rather than to produce
a headline.

Mechanics:
  * Notional book, no real orders. Starting equity is a constant.
  * Positions are taken at the close of the most recently CLOSED bar, with the
    same fee + slippage the backtest charged, so paper results and backtest
    results are directly comparable.
  * Every cycle appends one immutable row to a JSONL journal. State is a
    separate small JSON file, so a crashed or rescheduled cycle can resume.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

from app.quant import backtest as bt
from app.quant.exchange import Candles, fetch_candles

log = logging.getLogger("fincoach.quant.paper")

DATA_DIR = os.environ.get(
    "FINCOACH_EXPERIMENT_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "experiment"),
)
STATE_PATH = os.path.join(DATA_DIR, "paper_state.json")
JOURNAL_PATH = os.path.join(DATA_DIR, "cycles.jsonl")

START_EQUITY = 10_000.0


@dataclass
class Allocation:
    """One strategy the paper book is running forward."""

    symbol: str
    timeframe: str
    strategy: str
    variant: str
    params: dict[str, Any] = field(default_factory=dict)
    weight: float = 0.0
    #: What the selection process believed at the time — recorded so the forward
    #: result can be compared against the claim that justified the allocation.
    selected_on: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.symbol}/{self.timeframe}/{self.strategy}/{self.variant}"


@dataclass
class Position:
    symbol: str
    target: float = 0.0        # -1 short, 0 flat, +1 long, scaled by weight
    entry_price: float = 0.0
    notional: float = 0.0
    opened_at: int = 0


def _ensure_dir() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)


def _fresh_state() -> dict[str, Any]:
    return {
        "started_at": int(time.time()),
        "equity": START_EQUITY,
        "start_equity": START_EQUITY,
        "cash": START_EQUITY,
        "cycle": 0,
        "allocations": [],
        "positions": {},
        "realised_pnl": 0.0,
        "fees_paid": 0.0,
        "n_trades": 0,
    }


def load_state() -> dict[str, Any]:
    _ensure_dir()
    if not os.path.exists(STATE_PATH):
        return _fresh_state()
    try:
        with open(STATE_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as exc:  # noqa: BLE001 — a corrupt state must not end the run
        log.warning("paper state unreadable, restarting book: %s", exc)
        return _fresh_state()


def save_state(state: dict[str, Any]) -> None:
    _ensure_dir()
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=1)
    os.replace(tmp, STATE_PATH)   # atomic: a killed cycle cannot truncate state


def append_journal(row: dict[str, Any]) -> None:
    _ensure_dir()
    with open(JOURNAL_PATH, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def read_journal() -> list[dict[str, Any]]:
    if not os.path.exists(JOURNAL_PATH):
        return []
    rows: list[dict[str, Any]] = []
    with open(JOURNAL_PATH, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def current_signal(
    candles: Candles, strategy: str, params: dict[str, Any], *, allow_short: bool
) -> float:
    """The position the rule wants to hold going into the NEXT bar.

    Deliberately reads ``raw[-1]``, the target decided from the last CLOSED bar.
    ``exchange.fetch_candles`` has already dropped any in-progress bar, so this
    is the same one-bar-delayed decision the backtest makes — a live book that
    read a forming bar would be trading on information the backtest never had,
    and the two would stop being comparable.
    """
    raw, warmup = bt.build_positions(
        strategy, candles.closes, candles.highs, candles.lows, params,
        allow_short=allow_short,
    )
    if raw.size == 0 or raw.size <= warmup:
        return 0.0
    return float(raw[-1])


def run_cycle(
    allocations: list[Allocation],
    *,
    costs: bt.Costs,
    state: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Advance the paper book one step: re-read prices, re-target, mark to market."""
    state = state or load_state()
    state["cycle"] = int(state.get("cycle", 0)) + 1
    positions: dict[str, dict[str, Any]] = state.get("positions", {})
    per_turn = costs.per_turn

    marks: dict[str, float] = {}
    signals: dict[str, float] = {}
    trades: list[dict[str, Any]] = []
    errors: list[str] = []
    step_pnl = 0.0

    for alloc in allocations:
        try:
            candles = fetch_candles(alloc.symbol, alloc.timeframe, 1200)
        except Exception as exc:  # noqa: BLE001 — one dead feed must not stall the book
            errors.append(f"{alloc.key}: {type(exc).__name__} {str(exc)[:80]}")
            continue
        price = float(candles.closes[-1])
        marks[alloc.symbol] = price
        pos = positions.get(alloc.key) or {"notional": 0.0, "entry_price": price, "opened_at": 0}

        # 1. Mark the EXISTING position first. The move from the last mark to
        #    this price was earned by the position held over that interval — not
        #    by whatever the new signal is about to ask for. Re-targeting before
        #    marking would attribute the past move to a position that did not
        #    exist while it happened.
        prev_mark = pos.get("prev_mark")
        if prev_mark and pos.get("notional"):
            step_pnl += float(pos["notional"]) * ((price / float(prev_mark)) - 1.0)

        # 2. Now re-target on the freshly closed bar.
        sig = current_signal(
            candles, alloc.strategy, alloc.params, allow_short=alloc.variant == "long_short"
        )
        signals[alloc.key] = sig
        target_notional = sig * alloc.weight * state["start_equity"]
        delta = target_notional - float(pos["notional"])

        if abs(delta) > 1e-6:
            fee = abs(delta) * per_turn
            state["fees_paid"] = float(state.get("fees_paid", 0.0)) + fee
            state["n_trades"] = int(state.get("n_trades", 0)) + 1
            trades.append({
                "key": alloc.key, "price": price,
                "from_notional": round(float(pos["notional"]), 2),
                "to_notional": round(target_notional, 2),
                "fee": round(fee, 4),
            })
            if pos["notional"] == 0.0 and target_notional != 0.0:
                pos["opened_at"] = int(time.time())
                pos["entry_price"] = price
            elif target_notional == 0.0:
                pos["opened_at"] = 0

        pos["notional"] = target_notional
        pos["prev_mark"] = price
        pos["mark_price"] = price
        pos["symbol"] = alloc.symbol
        positions[alloc.key] = pos

    unrealised = step_pnl
    state["realised_pnl"] = float(state.get("realised_pnl", 0.0)) + unrealised
    state["equity"] = (
        float(state["start_equity"]) + float(state["realised_pnl"]) - float(state["fees_paid"])
    )
    state["positions"] = positions
    state["allocations"] = [asdict(a) for a in allocations]
    state["updated_at"] = int(time.time())

    row = {
        "cycle": state["cycle"],
        "ts": int(time.time()),
        "equity": round(state["equity"], 2),
        "start_equity": state["start_equity"],
        "return_pct": round(
            (state["equity"] / state["start_equity"] - 1.0) * 100.0, 4
        ),
        "step_pnl": round(unrealised, 4),
        "fees_paid": round(state["fees_paid"], 4),
        "n_trades": state["n_trades"],
        "marks": {k: round(v, 6) for k, v in marks.items()},
        "signals": signals,
        "trades": trades,
        "errors": errors,
        "context": context or {},
    }
    save_state(state)
    append_journal(row)
    return row


def equity_curve() -> tuple[list[int], list[float]]:
    rows = read_journal()
    return [r["ts"] for r in rows], [r["equity"] for r in rows]


def performance() -> dict[str, Any]:
    """Forward-test summary — with the sample size stated, not buried."""
    rows = read_journal()
    if len(rows) < 2:
        return {
            "ok": False,
            "reason": f"only {len(rows)} cycle(s) recorded — nothing to summarise yet",
            "n_cycles": len(rows),
        }
    eq = np.asarray([r["equity"] for r in rows], dtype=float)
    rets = eq[1:] / eq[:-1] - 1.0
    peak = np.maximum.accumulate(eq)
    dd = eq / peak - 1.0
    hours = (rows[-1]["ts"] - rows[0]["ts"]) / 3600.0

    return {
        "ok": True,
        "n_cycles": len(rows),
        "hours_elapsed": round(hours, 2),
        "start_equity": rows[0]["start_equity"],
        "equity": rows[-1]["equity"],
        "total_return_pct": round((eq[-1] / rows[0]["start_equity"] - 1.0) * 100.0, 4),
        "max_drawdown_pct": round(float(dd.min()) * 100.0, 4),
        "fees_paid": rows[-1]["fees_paid"],
        "n_trades": rows[-1]["n_trades"],
        "best_cycle_pct": round(float(rets.max()) * 100.0, 4) if rets.size else None,
        "worst_cycle_pct": round(float(rets.min()) * 100.0, 4) if rets.size else None,
        "caveat": (
            f"{len(rows)} observations over {hours:.1f} hours. This is far too short a sample "
            "to establish or refute an edge — at these sample sizes the standard error on the "
            "mean return dwarfs any plausible edge. Report it as a log, not as evidence."
        ),
    }
