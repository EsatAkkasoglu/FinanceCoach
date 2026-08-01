"""Paper-trading ledger tests — no network, synthetic price paths.

The ledger is the experiment's evidence, so the properties worth pinning are the
ones that would corrupt that evidence silently: trading a bar that has not
closed, losing state across a restart, or an equity figure that stops equalling
start + P&L − fees.
"""
from __future__ import annotations

import json

import numpy as np
import pytest

from app.quant import backtest as bt
from app.quant import paper
from app.quant.exchange import Candles
from app.quant.paper import Allocation

ZERO_COST = bt.Costs(fee_bps=0.0, slippage_bps=0.0)
REAL_COST = bt.Costs(fee_bps=10.0, slippage_bps=5.0)


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    """Point every ledger path at a temp dir so tests never touch real state."""
    monkeypatch.setattr(paper, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(paper, "STATE_PATH", str(tmp_path / "paper_state.json"))
    monkeypatch.setattr(paper, "JOURNAL_PATH", str(tmp_path / "cycles.jsonl"))
    return tmp_path


def _candles(closes: list[float], symbol: str = "BTC", timeframe: str = "15m") -> Candles:
    arr = np.asarray(closes, dtype=float)
    n = arr.size
    return Candles(
        symbol=symbol, timeframe=timeframe, source="test",
        ts=np.arange(n, dtype=np.int64) * 900_000,
        opens=arr, highs=arr * 1.001, lows=arr * 0.999, closes=arr,
        volumes=np.ones(n),
    )


def _rising(n: int = 400) -> list[float]:
    return [100.0 * (1.002 ** i) for i in range(n)]


@pytest.fixture
def feed(monkeypatch):
    """Install a deterministic price feed; return a setter to change it."""
    box: dict[str, list[float]] = {"closes": _rising()}
    monkeypatch.setattr(
        paper, "fetch_candles",
        lambda symbol, timeframe, want=1200: _candles(box["closes"], symbol, timeframe),
    )
    return box


# ── signal timing ────────────────────────────────────────────────────────────


def test_current_signal_reads_the_last_closed_bar():
    """The live target must come from the same bar the backtest would have used —
    otherwise the paper book and the backtest stop being comparable."""
    c = _candles(_rising(300))
    raw, _ = bt.build_positions("sma_cross", c.closes, c.highs, c.lows, {"fast": 10, "slow": 50})
    assert paper.current_signal(c, "sma_cross", {"fast": 10, "slow": 50}, allow_short=False) == (
        pytest.approx(float(raw[-1]))
    )


def test_current_signal_is_flat_before_the_indicator_warms_up():
    c = _candles(_rising(20))
    assert paper.current_signal(c, "sma_cross", {"fast": 10, "slow": 50}, allow_short=False) == 0.0


def test_short_variant_can_return_a_negative_target():
    falling = [100.0 * (0.998 ** i) for i in range(400)]
    c = _candles(falling)
    assert paper.current_signal(c, "sma_cross", {}, allow_short=True) == -1.0


# ── cycle mechanics ──────────────────────────────────────────────────────────


def test_first_cycle_opens_a_position_and_journals_it(ledger, feed):
    allocs = [Allocation("BTC", "15m", "sma_cross", "long_flat", {"fast": 10, "slow": 50}, 1.0)]
    row = paper.run_cycle(allocs, costs=ZERO_COST)

    assert row["cycle"] == 1
    assert row["signals"]["BTC/15m/sma_cross/long_flat"] == 1.0
    assert len(row["trades"]) == 1
    assert len(paper.read_journal()) == 1


def test_equity_identity_holds_after_every_cycle(ledger, feed):
    allocs = [Allocation("BTC", "15m", "sma_cross", "long_flat", {"fast": 10, "slow": 50}, 1.0)]
    for step in range(4):
        feed["closes"] = _rising(400 + step * 10)
        paper.run_cycle(allocs, costs=REAL_COST)
    state = paper.load_state()
    assert state["equity"] == pytest.approx(
        state["start_equity"] + state["realised_pnl"] - state["fees_paid"]
    )


def test_a_held_position_earns_the_price_move(ledger, feed):
    allocs = [Allocation("BTC", "15m", "sma_cross", "long_flat", {"fast": 10, "slow": 50}, 1.0)]
    paper.run_cycle(allocs, costs=ZERO_COST)          # opens, sets the first mark
    before = paper.load_state()["equity"]

    feed["closes"] = _rising(400) + [_rising(400)[-1] * 1.10]   # +10% next bar
    paper.run_cycle(allocs, costs=ZERO_COST)
    after = paper.load_state()["equity"]
    assert after > before


def test_no_trade_is_booked_when_the_target_is_unchanged(ledger, feed):
    allocs = [Allocation("BTC", "15m", "sma_cross", "long_flat", {"fast": 10, "slow": 50}, 1.0)]
    paper.run_cycle(allocs, costs=REAL_COST)
    fees_after_open = paper.load_state()["fees_paid"]
    paper.run_cycle(allocs, costs=REAL_COST)          # same signal → no churn
    assert paper.load_state()["fees_paid"] == pytest.approx(fees_after_open)


def test_fees_are_charged_on_the_traded_notional(ledger, feed):
    allocs = [Allocation("BTC", "15m", "sma_cross", "long_flat", {"fast": 10, "slow": 50}, 1.0)]
    row = paper.run_cycle(allocs, costs=REAL_COST)
    expected = abs(row["trades"][0]["to_notional"]) * REAL_COST.per_turn
    assert paper.load_state()["fees_paid"] == pytest.approx(expected, rel=1e-9)


def test_a_dead_feed_is_recorded_and_does_not_stop_the_cycle(ledger, monkeypatch):
    def boom(symbol, timeframe, want=1200):
        raise RuntimeError("venue down")

    monkeypatch.setattr(paper, "fetch_candles", boom)
    row = paper.run_cycle(
        [Allocation("BTC", "15m", "sma_cross", "long_flat", {}, 1.0)], costs=REAL_COST
    )
    assert row["errors"] and "venue down" in row["errors"][0]
    assert row["cycle"] == 1                 # the book still advanced


def test_weights_split_the_book_across_allocations(ledger, feed):
    allocs = [
        Allocation("BTC", "15m", "sma_cross", "long_flat", {"fast": 10, "slow": 50}, 0.5),
        Allocation("ETH", "15m", "sma_cross", "long_flat", {"fast": 10, "slow": 50}, 0.5),
    ]
    row = paper.run_cycle(allocs, costs=ZERO_COST)
    notionals = [t["to_notional"] for t in row["trades"]]
    assert len(notionals) == 2
    assert sum(notionals) == pytest.approx(paper.START_EQUITY)


# ── persistence ──────────────────────────────────────────────────────────────


def test_state_survives_a_restart(ledger, feed):
    allocs = [Allocation("BTC", "15m", "sma_cross", "long_flat", {"fast": 10, "slow": 50}, 1.0)]
    paper.run_cycle(allocs, costs=REAL_COST)
    paper.run_cycle(allocs, costs=REAL_COST)
    reloaded = paper.load_state()             # simulates a fresh process
    assert reloaded["cycle"] == 2
    assert reloaded["positions"]


def test_a_corrupt_state_file_restarts_the_book_instead_of_crashing(ledger):
    (ledger / "paper_state.json").write_text("{broken", encoding="utf-8")
    state = paper.load_state()
    assert state["cycle"] == 0
    assert state["equity"] == paper.START_EQUITY


def test_journal_rows_are_valid_json_lines(ledger, feed):
    allocs = [Allocation("BTC", "15m", "sma_cross", "long_flat", {"fast": 10, "slow": 50}, 1.0)]
    for _ in range(3):
        paper.run_cycle(allocs, costs=REAL_COST)
    for line in (ledger / "cycles.jsonl").read_text(encoding="utf-8").splitlines():
        json.loads(line)
    assert len(paper.read_journal()) == 3


# ── reporting ────────────────────────────────────────────────────────────────


def test_performance_refuses_to_summarise_a_single_cycle(ledger, feed):
    paper.run_cycle(
        [Allocation("BTC", "15m", "sma_cross", "long_flat", {}, 1.0)], costs=REAL_COST
    )
    out = paper.performance()
    assert out["ok"] is False
    assert out["n_cycles"] == 1


def test_performance_reports_the_sample_size_caveat(ledger, feed):
    allocs = [Allocation("BTC", "15m", "sma_cross", "long_flat", {"fast": 10, "slow": 50}, 1.0)]
    for step in range(5):
        feed["closes"] = _rising(400 + step)
        paper.run_cycle(allocs, costs=REAL_COST)
    out = paper.performance()
    assert out["ok"] is True
    assert out["n_cycles"] == 5
    assert "too short a sample" in out["caveat"]
    assert out["max_drawdown_pct"] <= 0.0


# ── duplicate-bar cycles are not observations ────────────────────────────────


def test_performance_does_not_count_a_repeated_bar_as_new_evidence(ledger, feed):
    """A tournament cycle runs ~17 minutes; the loop can then fire again against
    the SAME closed bar. Counting that twice overstates how much forward
    evidence exists, which is the one number this summary exists to be honest
    about."""
    allocs = [Allocation("BTC", "15m", "sma_cross", "long_flat", {"fast": 10, "slow": 50}, 1.0)]
    paper.run_cycle(allocs, costs=REAL_COST)          # opens
    paper.run_cycle(allocs, costs=REAL_COST)          # same bar → duplicate
    paper.run_cycle(allocs, costs=REAL_COST)          # same bar → duplicate

    out = paper.performance()
    assert out["ok"] is False                          # 1 distinct observation
    assert out["n_cycles"] == 1
    assert out["n_raw_cycles"] == 3
    assert "unchanged bar" in out["reason"]


def test_performance_counts_cycles_where_the_bar_moved(ledger, feed):
    allocs = [Allocation("BTC", "15m", "sma_cross", "long_flat", {"fast": 10, "slow": 50}, 1.0)]
    for step in range(4):
        feed["closes"] = _rising(400 + step)          # a genuinely new bar each time
        paper.run_cycle(allocs, costs=REAL_COST)
    paper.run_cycle(allocs, costs=REAL_COST)          # one repeat at the end

    out = paper.performance()
    assert out["ok"] is True
    assert out["n_cycles"] == 4
    assert out["n_duplicate_bar_cycles"] == 1


def test_a_dropped_allocation_is_closed_and_charged(ledger, feed):
    """A cell that falls off the leaderboard must be flattened, not orphaned.

    Left in place it stops being marked (P&L silently freezes) and never pays
    its exit cost, so the book diverges from any real one that had to actually
    close the trade.
    """
    btc = Allocation("BTC", "15m", "sma_cross", "long_flat", {"fast": 10, "slow": 50}, 1.0)
    paper.run_cycle([btc], costs=REAL_COST)
    fees_after_open = paper.load_state()["fees_paid"]
    assert paper.load_state()["positions"]

    eth = Allocation("ETH", "15m", "sma_cross", "long_flat", {"fast": 10, "slow": 50}, 1.0)
    row = paper.run_cycle([eth], costs=REAL_COST)          # BTC dropped

    closed = [t for t in row["trades"] if t.get("reason") == "dropped from allocation"]
    assert len(closed) == 1
    assert closed[0]["key"].startswith("BTC/")
    assert closed[0]["to_notional"] == 0.0

    state = paper.load_state()
    assert not any(k.startswith("BTC/") for k in state["positions"])
    assert state["fees_paid"] > fees_after_open           # the exit was paid for
    assert state["equity"] == pytest.approx(
        state["start_equity"] + state["realised_pnl"] - state["fees_paid"]
    )
