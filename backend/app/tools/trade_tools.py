"""Chat-facing order tools — PROPOSE a horizon-aware trade the user approves.

Per the product's "always confirm" decision, the agent NEVER auto-places. It
PROPOSES a risk-defined target (status PENDING); the user approves it via
``POST /crypto/targets/{id}/confirm`` (panel / chat card), which flips it
PENDING → ACTIVE and starts live scoring. Multi-asset via
``app.services.signal_engine.build_signal`` (crypto / stock / ETF / fund) and
horizon-aware via ``app.services.horizon`` buckets.
"""
from __future__ import annotations

import logging
from typing import Any

from langchain_core.tools import tool

from app.auth import get_current_user_id_or_none
from app.db.models import TradeStatus
from app.db.session import SessionLocal
from app.services import horizon as hz
from app.services.signal_engine import build_signal
from app.services.trade_targets import upsert_target_from_plan
from app.settings import settings
from app.tools.crypto_short_term import _plan_summary

log = logging.getLogger("fincoach.tools.trade")


def _propose_one(user_id: int, symbol: str, *, asset_class: str | None, bucket: str) -> dict[str, Any]:
    """Analyse one symbol and, if directional, persist a PENDING proposal."""
    result = build_signal(symbol, asset_class=asset_class or None, bucket=bucket)
    if not result.get("ok"):
        return {"ok": False, "error": result.get("error", "signal failed"), "symbol": symbol}
    plan = result.get("data") or {}
    if plan.get("direction") == "neutral" or plan.get("target") is None:
        return {
            "ok": True,
            "proposed": False,
            "direction": "neutral",
            "message": (
                f"{plan.get('ticker', symbol)} has no clear {plan.get('horizon', bucket)} edge "
                "right now (neutral) — nothing proposed. Standing aside is the correct call."
            ),
            "plan": _plan_summary(plan),
        }
    with SessionLocal() as db:
        tgt = upsert_target_from_plan(db, user_id, result, status=TradeStatus.PENDING.value)
        db.commit()
        tid = tgt.id if tgt is not None else None
    return {
        "ok": True,
        "proposed": True,
        "target_id": tid,
        "status": "pending",
        "message": (
            f"Proposed a {plan['direction'].upper()} on {plan['ticker']} ({plan['horizon']} horizon): "
            f"entry {plan['entry']}, target {plan['target']} ({plan['target_pct']:+.2f}%), "
            f"stop {plan['stop']} ({plan['stop_pct']:+.2f}%), R:R {plan['rr']}:1. "
            "Awaiting your approval — confirm it and it goes live on the Signals panel."
        ),
        "plan": _plan_summary(plan),
    }


@tool
def propose_trade(symbol: str, horizon: str = "swing", asset_class: str = "") -> dict[str, Any]:
    """Analyse a NAMED asset over a horizon and PROPOSE a risk-defined trade to OPEN.

    Use whenever the user wants to ACT on a specific asset — "open / take a
    position", "al", "pozisyon aç", "işlem aç", "bunu izlemeye al" — on a crypto
    (BTC, ETH, SOL), a US stock/ETF (AAPL, NVDA, SPY) or a Turkish fund code
    (AFA, TI2). It does NOT auto-place: it proposes an entry / target / stop the
    user then approves (the order appears on the Signals panel once approved). If
    the signal is neutral, nothing is proposed and the tool says so. For analysis
    WITHOUT proposing an order, use get_trade_signal / get_crypto_short_term_plan.

    Args:
        symbol: ticker or fund code, e.g. "SOL", "AAPL", "AFA".
        horizon: holding horizon — "intraday" (~4h), "swing" (~1 day, default),
            "position" (~1 week) or "long" (~1 month). Infer from the user's words.
        asset_class: optional override — "crypto", "stock", "etf" or "fund".
            Leave empty to auto-detect.
    """
    user_id = get_current_user_id_or_none()
    if user_id is None:
        return {"ok": False, "error": "no user in context"}
    bucket = hz.resolve(horizon)["name"]
    return _propose_one(user_id, symbol, asset_class=asset_class, bucket=bucket)


@tool
def open_best_trade(
    symbols: list[str] | None = None, horizon: str = "swing", asset_class: str = ""
) -> dict[str, Any]:
    """Scan several assets, pick the HIGHEST-CONVICTION setup over a horizon, and PROPOSE it.

    Use when the user asks YOU to choose — "pick the best crypto to trade now",
    "en iyi kriptoyu seç ve işlem aç", "find me the best swing setup". Ranks each
    candidate's signal by confidence and proposes (PENDING, awaiting approval) the
    strongest DIRECTIONAL one. If every candidate is neutral, nothing is proposed.

    Args:
        symbols: optional candidates, e.g. ["BTC","ETH","SOL"] or ["AAPL","MSFT"].
            Defaults to the curated crypto basket.
        horizon: "intraday" / "swing" (default) / "position" / "long".
        asset_class: optional override applied to every candidate.
    """
    user_id = get_current_user_id_or_none()
    if user_id is None:
        return {"ok": False, "error": "no user in context"}
    bucket = hz.resolve(horizon)["name"]
    syms = [s.strip().upper() for s in (symbols or settings.crypto_basket) if s and s.strip()]

    ranking: list[dict[str, Any]] = []
    best: tuple[dict[str, Any], dict[str, Any]] | None = None  # (plan, full result)
    for s in syms:
        res = build_signal(s, asset_class=asset_class or None, bucket=bucket)
        if not res.get("ok"):
            ranking.append({"symbol": s, "ok": False, "error": res.get("error")})
            continue
        p = res.get("data") or {}
        ranking.append({
            "symbol": s,
            "direction": p.get("direction"),
            "score": p.get("score"),
            "confidence": p.get("confidence"),
            "target_pct": p.get("target_pct"),
        })
        tradeable = p.get("direction") != "neutral" and p.get("target") is not None
        if tradeable and (best is None or (p.get("confidence") or 0) > (best[0].get("confidence") or 0)):
            best = (p, res)
    ranking.sort(key=lambda r: (r.get("confidence") if r.get("confidence") is not None else -1), reverse=True)

    if best is None:
        return {
            "ok": True,
            "proposed": False,
            "message": (
                f"No clear {bucket} trade across the scanned assets right now — the market is "
                "balanced, so standing aside is the right move."
            ),
            "ranking": ranking,
        }
    plan, result = best
    with SessionLocal() as db:
        tgt = upsert_target_from_plan(db, user_id, result, status=TradeStatus.PENDING.value)
        db.commit()
        tid = tgt.id if tgt is not None else None
    return {
        "ok": True,
        "proposed": True,
        "chosen": plan["ticker"],
        "target_id": tid,
        "status": "pending",
        "message": (
            f"Best {plan['horizon']} setup: {plan['direction'].upper()} on {plan['ticker']} "
            f"(confidence {plan['confidence']:.0%}). Entry {plan['entry']}, target {plan['target']} "
            f"({plan['target_pct']:+.2f}%), stop {plan['stop']}, R:R {plan['rr']}:1. "
            "Proposed — approve it to go live on the Signals panel."
        ),
        "plan": _plan_summary(plan),
        "ranking": ranking,
    }


@tool
def get_trade_signal(symbol: str, horizon: str = "swing", asset_class: str = "") -> dict[str, Any]:
    """Build a risk-defined trade signal for ANY asset over a horizon — READ ONLY.

    Fuses price-action technicals with the class-appropriate confirmation layer
    (crypto: funding/OI; stock/ETF: fundamentals + macro regime; fund: NAV
    momentum) and news into one directional call (long/short/neutral) with an
    ATR-based entry, profit target and stop sized to the horizon. Use for
    "should I…? / ne dersin?" analysis. To actually OPEN/propose a trade, use
    propose_trade instead.

    Args:
        symbol: ticker or fund code (crypto BTC/ETH, stock AAPL/NVDA, fund AFA).
        horizon: "intraday" (~4h) / "swing" (~1d, default) / "position" (~1wk) /
            "long" (~1mo).
        asset_class: optional override — "crypto"/"stock"/"etf"/"fund".
    """
    bucket = hz.resolve(horizon)["name"]
    return build_signal(symbol, asset_class=asset_class or None, bucket=bucket)
