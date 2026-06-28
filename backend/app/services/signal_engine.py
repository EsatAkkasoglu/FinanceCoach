"""Generalized, horizon-aware trade-signal engine across asset classes.

``build_signal(symbol, asset_class, bucket)`` returns the SAME calc envelope as
the crypto engine (``data`` = a plan with direction / entry / target / stop /
components / details), so the order tool and the frontend renderer never branch
on asset class.

Class-aware fusion (each weight set sums to 1.0):

  crypto     technicals (0.50) + perpetual derivatives (0.30) + news (0.20)
             → delegated to the battle-tested ``crypto_short_term`` engine.
  stock/etf  technicals (0.50) + fundamentals & macro-regime (0.30) + news (0.20)
             — equities have no funding rate, so the confirmation slot is
             fundamentals + a VIX regime read. StockBench (arXiv:2510.02209)
             shows news + fundamentals measurably improve an agent's calls, so
             they enter the fusion, not just the prose.
  fund       NAV technicals (0.65) + trailing-return momentum (0.35); daily NAV
             only, so funds are restricted to swing+ horizons (no intraday).

All three reuse the shared pure technical sub-score (``technical_signal``) and
the horizon ATR geometry (``app.services.horizon``). Every fetch is best-effort:
a signal still computes from price-action alone if fundamentals / news are down.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import app.services.coindesk as cd
from app.services import horizon as hz
from app.services import yfinance_service as yf
from app.tools._calc_result import err, ok
from app.tools.crypto_short_term import (
    _clamp,
    _confidence_label,
    analyze_short_term,
    technical_signal,
)

log = logging.getLogger("fincoach.signal_engine")

_DIRECTION_BAND = 0.15
# Equity / fund fusion weights.
_W_EQUITY = {"technical": 0.50, "fundamental": 0.30, "sentiment": 0.20}
_W_FUND = {"technical": 0.65, "momentum": 0.35}

# yfinance (period, interval) per horizon bucket. Intraday/swing want hourly
# bars; position/long want daily. 1h is capped at ~730d by yfinance — 3mo is
# plenty of bars for the EMA-21 / MACD / ATR-14 stack.
_YF_GRAIN: dict[str, tuple[str, str]] = {
    "intraday": ("3mo", "1h"),
    "swing": ("3mo", "1h"),
    "position": ("1y", "1d"),
    "long": ("2y", "1d"),
}


# ── asset-class inference ────────────────────────────────────────────────────


def infer_asset_class(symbol: str, asset_class: str | None = None) -> str:
    """Normalize to crypto | stock | etf | fund. Trusts an explicit class; else
    infers crypto (known base or ``-USD``) vs stock from the ticker shape."""
    if asset_class:
        a = asset_class.strip().lower()
        if a in {"crypto", "stock", "etf", "fund"}:
            return a
    t = (symbol or "").strip().upper()
    base = t.split("-")[0]
    if t.endswith("-USD") or base in cd._SYMBOL_TO_ID:
        return "crypto"
    return "stock"


def _family(asset_class: str) -> str:
    """crypto | equity | fund — the fusion path (stock and etf share equity)."""
    if asset_class == "crypto":
        return "crypto"
    if asset_class == "fund":
        return "fund"
    return "equity"


# ── shared building blocks ───────────────────────────────────────────────────


def _news_sentiment(query: str, asset_class: str) -> tuple[float, int, list[dict[str, Any]]]:
    """Mean recent news sentiment in [-1, 1], count, and up to 3 headlines."""
    try:
        from app.tools.news_tools import search_news
        articles = search_news.invoke({"query": query, "limit": 6, "asset_class": asset_class})
    except Exception as exc:  # noqa: BLE001 — news is best-effort, never block a signal
        log.info("news sentiment unavailable for %s: %s", query, exc)
        return 0.0, 0, []
    if not isinstance(articles, list):
        return 0.0, 0, []
    score_map = {"positive": 1.0, "negative": -1.0, "neutral": 0.0}
    vals = [score_map[a["sentiment"]] for a in articles if isinstance(a, dict) and a.get("sentiment") in score_map]
    mean = sum(vals) / len(vals) if vals else 0.0
    headlines = [
        {"title": a.get("title"), "source": a.get("source"), "sentiment": a.get("sentiment"), "url": a.get("url")}
        for a in articles[:3]
        if isinstance(a, dict)
    ]
    return mean, len(vals), headlines


def _vix_regime_score() -> tuple[float, dict[str, Any]]:
    """Macro regime from the VIX: calm → risk-on (+), fear → risk-off (-)."""
    try:
        from app.tools.market_tools import get_quote
        q = get_quote.invoke({"ticker": "^VIX"})
        vix = q.get("price") if isinstance(q, dict) else None
    except Exception as exc:  # noqa: BLE001
        log.info("VIX regime unavailable: %s", exc)
        return 0.0, {"vix": None}
    if vix is None:
        return 0.0, {"vix": None}
    # <15 calm (+0.5) … 20 neutral (0) … >30 fear (-1). Linear, clamped.
    score = _clamp((20.0 - float(vix)) / 10.0)
    return score, {"vix": round(float(vix), 2)}


def _fundamental_score(symbol: str, price: float) -> tuple[float, dict[str, Any]]:
    """Fundamentals sub-score ∈ [-1, 1] from yfinance overview (best-effort).

    Blends analyst-target upside, trend vs the 200-day SMA, and profitability.
    Returns 0 with an empty detail when no fundamentals are available.
    """
    try:
        ov = yf.overview(symbol)
    except Exception as exc:  # noqa: BLE001
        log.info("fundamentals unavailable for %s: %s", symbol, exc)
        return 0.0, {}
    parts: list[float] = []
    detail: dict[str, Any] = {}

    target = ov.get("analyst_target_price")
    if target and price:
        upside = target / price - 1.0
        parts.append(_clamp(upside / 0.20))  # ±20% to the analyst target = full
        detail["analyst_upside_pct"] = round(upside * 100.0, 2)

    sma200 = ov.get("sma_200d")
    if sma200 and price:
        parts.append(_clamp((price / sma200 - 1.0) / 0.10))  # ±10% vs 200d SMA
        detail["vs_sma200_pct"] = round((price / sma200 - 1.0) * 100.0, 2)

    margin = ov.get("profit_margin")
    if margin is not None:
        parts.append(_clamp(margin / 0.20))  # 20% net margin = full positive
        detail["profit_margin_pct"] = round(margin * 100.0, 2)

    fwd, ttm = ov.get("forward_pe"), ov.get("pe_ratio")
    if fwd and ttm and fwd > 0 and ttm > 0:
        # Forward P/E below trailing ⇒ earnings expected to grow ⇒ bullish.
        parts.append(_clamp((ttm - fwd) / ttm))
        detail["pe_trailing"], detail["pe_forward"] = round(ttm, 2), round(fwd, 2)

    detail["name"] = ov.get("name")
    score = sum(parts) / len(parts) if parts else 0.0
    return _clamp(score), detail


def _build_candles(bars_newest_first: list[dict[str, Any]]) -> list[dict[str, float]]:
    """yfinance / NAV rows (newest-first or arbitrary) → oldest-first OHLC."""
    rows = sorted(
        (b for b in bars_newest_first if b.get("close") is not None or b.get("price") is not None),
        key=lambda b: b.get("date") or "",
    )
    out: list[dict[str, float]] = []
    for b in rows:
        close = b.get("close")
        if close is None:  # NAV-only fund rows
            close = b.get("price")
        out.append({
            "open": float(b.get("open", close)),
            "high": float(b.get("high", close)),
            "low": float(b.get("low", close)),
            "close": float(close),
        })
    return out


def _assemble_plan(
    *,
    symbol: str,
    ticker: str,
    asset_class: str,
    bucket: str,
    components: dict[str, float],
    weights: dict[str, float],
    technical_detail: dict[str, Any],
    extra_detail: dict[str, Any],
    sentiment_n: int,
    atr_bar: float | None,
    price: float,
    grain: str,
) -> dict[str, Any]:
    """Fuse class-aware components into the common plan shape."""
    score = _clamp(sum(weights[k] * components[k] for k in weights))
    if score > _DIRECTION_BAND:
        direction = "long"
    elif score < -_DIRECTION_BAND:
        direction = "short"
    else:
        direction = "neutral"

    sign = 1.0 if score >= 0 else -1.0
    agree = sum(1 for s in components.values() if s * sign > 0)
    confidence = round(_clamp(abs(score) * (0.55 + 0.15 * agree), 0.0, 1.0), 3)

    geom = hz.atr_targets(price, atr_bar, bucket, direction)
    spec = hz.resolve(bucket)
    return {
        "ok": True,
        "symbol": symbol,
        "ticker": ticker,
        "asset_class": asset_class,
        "direction": direction,
        "score": round(score, 3),
        "confidence": confidence,
        "confidence_label": _confidence_label(confidence),
        "horizon": spec["name"],
        "horizon_hours": spec["hours"],
        "entry": round(price, 6),
        "target": geom["target"],
        "stop": geom["stop"],
        "target_pct": geom["target_pct"],
        "stop_pct": geom["stop_pct"],
        "rr": geom["rr"],
        "horizon_atr": geom["horizon_atr"],
        "horizon_atr_pct": geom["horizon_atr_pct"],
        "components": {k: round(v, 3) for k, v in components.items()},
        "weights": weights,
        "technical_detail": technical_detail,
        "fundamental_detail": extra_detail,
        "sentiment_detail": {"score": round(components.get("sentiment", 0.0), 3), "n": sentiment_n},
        "grain": grain,
        "as_of": datetime.now(UTC).isoformat(),
    }


# ── equity (stock / ETF) path ────────────────────────────────────────────────


def _equity_signal(symbol: str, asset_class: str, bucket: str, with_news: bool) -> dict[str, Any]:
    sym = symbol.strip().upper()
    period, interval = _YF_GRAIN[hz.resolve(bucket)["name"]]
    try:
        bars = yf.history(sym, period=period, interval=interval)
    except Exception as exc:  # noqa: BLE001
        return err(f"price history unavailable for {sym}: {exc}", symbol=sym)
    candles = _build_candles(bars)
    if len(candles) < 26:
        return err(f"Not enough price history to build a signal for {sym}", symbol=sym)

    closes = [c["close"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    ts = technical_signal(closes, highs, lows)
    price = ts["price"]

    fund_score, fund_detail = _fundamental_score(sym, price)
    macro_score, macro_detail = _vix_regime_score()
    # Confirmation slot = fundamentals (0.6) + macro regime (0.4).
    confirmation = _clamp(0.6 * fund_score + 0.4 * macro_score)
    fund_detail.update(macro_detail, fundamental_score=round(fund_score, 3), macro_score=round(macro_score, 3))

    sent_score, sent_n, headlines = _news_sentiment(fund_detail.get("name") or sym, asset_class) if with_news else (0.0, 0, [])

    plan = _assemble_plan(
        symbol=sym, ticker=sym, asset_class=asset_class, bucket=bucket,
        components={"technical": ts["technical"], "fundamental": confirmation, "sentiment": sent_score},
        weights=_W_EQUITY,
        technical_detail=ts["detail"], extra_detail=fund_detail,
        sentiment_n=sent_n, atr_bar=ts["atr"], price=price, grain=interval,
    )
    plan["news"] = headlines
    return _envelope(plan, source="yfinance+news")


# ── fund (TEFAS NAV) path ────────────────────────────────────────────────────


def _fund_signal(symbol: str, bucket: str) -> dict[str, Any]:
    code = symbol.strip().upper()
    try:
        from app.tools import fund_tools
        rows = fund_tools.get_fund_history.invoke({"code": code, "days": 365})
    except Exception as exc:  # noqa: BLE001
        return err(f"fund history unavailable for {code}: {exc}", symbol=code)
    candles = _build_candles(rows)
    if len(candles) < 26:
        return err(f"Not enough NAV history to build a signal for {code}", symbol=code)

    closes = [c["close"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    ts = technical_signal(closes, highs, lows)
    price = ts["price"]

    # Trailing-return momentum over a horizon-scaled window of NAV points.
    window = min(len(closes) - 1, max(5, hz.resolve(bucket)["hours"] // 24))
    base = closes[-1 - window] if closes[-1 - window] else closes[0]
    trailing_ret = (price / base - 1.0) if base else 0.0
    momentum = _clamp(trailing_ret / 0.05)  # ±5% over the window = full

    plan = _assemble_plan(
        symbol=code, ticker=code, asset_class="fund", bucket=bucket,
        components={"technical": ts["technical"], "momentum": momentum},
        weights=_W_FUND,
        technical_detail=ts["detail"],
        extra_detail={"trailing_return_pct": round(trailing_ret * 100.0, 2), "window_navs": window},
        sentiment_n=0, atr_bar=ts["atr"], price=price, grain="1d",
    )
    plan["news"] = []
    return _envelope(plan, source="tefas")


# ── envelope + public entry ──────────────────────────────────────────────────


def _envelope(plan: dict[str, Any], *, source: str) -> dict[str, Any]:
    arrow = {"long": "▲", "short": "▼", "neutral": "■"}[plan["direction"]]
    rationale = _rationale(plan)
    plan["thesis"] = rationale
    return ok(
        raw_value=plan["score"],
        formatted_value=(
            f"{arrow} {plan['direction'].upper()} · {plan['confidence_label']} "
            f"({plan['confidence']:.0%})"
            + (f" · target {plan['target_pct']:+.2f}%" if plan.get("target_pct") is not None else "")
        ),
        formula=" + ".join(f"{w:.2f}·{k}" for k, w in plan["weights"].items()) + " → ATR-based horizon target",
        explanation=rationale,
        ui_type="metric",
        data=plan,
        source=source,
        rationale=rationale,
    )


def _rationale(plan: dict[str, Any]) -> str:
    d = plan["direction"]
    comp = plan["components"]
    verb = {"long": "favours longs", "short": "favours shorts", "neutral": "is balanced — stand aside"}[d]
    bits = [
        f"{plan['ticker']} {verb} over a {plan['horizon']} horizon "
        f"(score {plan['score']:+.2f}, {plan['confidence_label']} confidence).",
        "Drivers: " + ", ".join(f"{k} {v:+.2f}" for k, v in comp.items()) + ".",
    ]
    if plan.get("target") is not None:
        bits.append(
            f"Plan: entry {plan['entry']}, target {plan['target']} ({plan['target_pct']:+.2f}%), "
            f"stop {plan['stop']} ({plan['stop_pct']:+.2f}%), R:R {plan['rr']}:1."
        )
    return " ".join(bits)


def build_signal(
    symbol: str,
    *,
    asset_class: str | None = None,
    bucket: str = "swing",
    with_news: bool = True,
) -> dict[str, Any]:
    """Horizon-sized trade signal for any asset. Returns the calc envelope.

    ``asset_class`` is crypto | stock | etf | fund (inferred from the ticker when
    omitted). ``bucket`` is an :mod:`app.services.horizon` name. Funds have no
    intraday NAV, so an intraday fund request is lifted to swing.
    """
    klass = infer_asset_class(symbol, asset_class)
    spec = hz.resolve(bucket)
    if not hz.allows(spec["name"], klass):
        # Funds can't trade intraday — lift to the shortest allowed horizon.
        spec = hz.resolve("swing")
    fam = _family(klass)
    if fam == "crypto":
        return analyze_short_term(symbol, bucket=spec["name"], with_news=with_news)
    if fam == "fund":
        return _fund_signal(symbol, spec["name"])
    return _equity_signal(symbol, klass, spec["name"], with_news)
