"""Short-horizon (intraday / 4-hour) crypto trade-signal engine.

The existing crypto stack (``analyze_ticker_8dim``, ``get_technical_indicators``)
is **daily**-grained — SMA-50, 365-day history — which is the right lens for a
position investor but far too coarse for a 4-hour trade. This module adds the
missing short-horizon layer: it fuses three independent reads into one concrete,
risk-defined plan (entry / target / stop) sized to a 4-hour window.

    technicals (50%)   intraday EMA-9/21 trend, RSI-14, MACD, 4-bar momentum
    derivatives (30%)  perpetual funding (crowded-leverage / contrarian) + OI trend
    sentiment   (20%)  recent crypto-news sentiment

All indicator math is pure Python (no pandas) so it is unit-testable without a
network round-trip — :func:`compute_short_term_signal` takes plain numbers and
returns the full plan. :func:`analyze_short_term` is the thin orchestrator that
fetches live candles + derivatives + news and calls it.

Targets are **ATR-based**, never guessed: the 4-hour ATR (≈ hourly ATR × √4) sets
a 1.5× target and 1.0× stop, giving a fixed 1.5 : 1 reward : risk. Scaling
volatility by the square-root of time is the standard diffusion approximation.

Direction is a sign vote, not a price prediction. The number that matters for a
juror is the realised move between entry and target inside the horizon.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from langchain_core.tools import tool

import app.services.coindesk as cd
from app.auth import get_current_user_id_or_none
from app.db.session import SessionLocal
from app.services import horizon as hz
from app.services.coindesk import CoinDeskError
from app.services.trade_targets import upsert_target_from_plan
from app.settings import settings
from app.tools._cache import cache_get, cache_set
from app.tools._calc_result import err, ok

log = logging.getLogger("fincoach.tools.crypto_short_term")

HORIZON_HOURS = 4  # canonical intraday horizon (the original engine); see app.services.horizon
# Bands on the blended directional score (∈ [-1, 1]) → long / short / neutral.
_DIRECTION_BAND = 0.15
# Component blend weights. Technicals lead; derivatives temper crowded leverage;
# news nudges. Must sum to 1.0.
_W_TECH = 0.50
_W_DERIV = 0.30
_W_SENTIMENT = 0.20


# ---------------------------------------------------------------------------
# Pure indicator math (oldest-first input series)
# ---------------------------------------------------------------------------


def _clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def ema_series(values: list[float], period: int) -> list[float]:
    """Exponential moving average over an oldest-first series.

    Seeded with the simple average of the first ``period`` points (standard
    Wilder/most-charting convention). Returns one EMA value per input point
    (the first ``period-1`` are the running seed average).
    """
    if not values or period < 1:
        return []
    k = 2.0 / (period + 1.0)
    out: list[float] = []
    ema: float | None = None
    seed_sum = 0.0
    for i, v in enumerate(values):
        if i < period:
            seed_sum += v
            ema = seed_sum / (i + 1)
        else:
            ema = v * k + ema * (1 - k)  # type: ignore[operator]
        out.append(ema)
    return out


def ema_last(values: list[float], period: int) -> float | None:
    s = ema_series(values, period)
    return s[-1] if s else None


def rsi(values: list[float], period: int = 14) -> float | None:
    """Wilder's RSI of an oldest-first close series. None if too short."""
    if len(values) <= period:
        return None
    gains, losses = 0.0, 0.0
    for i in range(1, period + 1):
        delta = values[i] - values[i - 1]
        if delta >= 0:
            gains += delta
        else:
            losses -= delta
    avg_gain = gains / period
    avg_loss = losses / period
    for i in range(period + 1, len(values)):
        delta = values[i] - values[i - 1]
        gain = delta if delta > 0 else 0.0
        loss = -delta if delta < 0 else 0.0
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> float | None:
    """Wilder's Average True Range over oldest-first OHLC. None if too short."""
    n = len(closes)
    if n <= period or len(highs) != n or len(lows) != n:
        return None
    trs: list[float] = []
    for i in range(1, n):
        prev_close = closes[i - 1]
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - prev_close),
            abs(lows[i] - prev_close),
        )
        trs.append(tr)
    if len(trs) < period:
        return None
    atr_val = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr_val = (atr_val * (period - 1) + tr) / period
    return atr_val


def macd(values: list[float], fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[float, float, float] | None:
    """MACD line, signal line, histogram for an oldest-first close series."""
    if len(values) < slow + signal:
        return None
    ema_fast = ema_series(values, fast)
    ema_slow = ema_series(values, slow)
    macd_line = [f - s for f, s in zip(ema_fast, ema_slow, strict=False)]
    signal_line = ema_series(macd_line, signal)
    m = macd_line[-1]
    sig = signal_line[-1]
    return m, sig, m - sig


# ---------------------------------------------------------------------------
# Signal fusion (pure — the heart of the engine, fully unit-testable)
# ---------------------------------------------------------------------------


def _confidence_label(c: float) -> str:
    if c >= 0.6:
        return "high"
    if c >= 0.35:
        return "medium"
    return "low"


def compute_short_term_signal(
    candles: list[dict[str, float]],
    *,
    bucket: str = "intraday",
    funding_bps_8h: float | None = None,
    oi_change_24h_pct: float | None = None,
    sentiment_score: float | None = None,
    sentiment_n: int = 0,
) -> dict[str, Any]:
    """Fuse technicals + derivatives + sentiment into a horizon-sized plan.

    ``candles`` is oldest-first ``[{open,high,low,close}, ...]`` at the bucket's
    bar granularity (1h for intraday/swing, 1d for position/long — the caller
    fetches the right grain). ``bucket`` is a :mod:`app.services.horizon` name
    (default ``intraday`` = the original 4-hour engine, byte-for-byte).
    ``funding_bps_8h`` is the perpetual funding rate in basis points / 8h.
    ``oi_change_24h_pct`` is open-interest 24h % change. ``sentiment_score`` is
    the mean news sentiment in [-1, 1] over ``sentiment_n`` articles.

    Returns a JSON-safe dict: direction, score, confidence, the per-component
    sub-scores, and ATR-derived entry/target/stop scaled to the horizon. Raises
    nothing.
    """
    closes = [float(c["close"]) for c in candles if c.get("close") is not None]
    highs = [float(c.get("high", c["close"])) for c in candles if c.get("close") is not None]
    lows = [float(c.get("low", c["close"])) for c in candles if c.get("close") is not None]
    if len(closes) < 26:
        return {"ok": False, "error": "insufficient candles", "n": len(closes)}

    price = closes[-1]

    # ── Technical sub-scores, each ∈ [-1, 1] ──────────────────────────────
    ema_fast = ema_last(closes, 9) or price
    ema_slow = ema_last(closes, 21) or price
    # EMA-9/21 separation as a fraction of price; 0.6% gap = full conviction.
    trend_score = _clamp((ema_fast - ema_slow) / price / 0.006)

    rsi_val = rsi(closes, 14)
    # RSI 50 → 0, 70 → +1, 30 → -1 (momentum read; capped at the extremes).
    rsi_score = _clamp((rsi_val - 50.0) / 20.0) if rsi_val is not None else 0.0

    macd_out = macd(closes)
    macd_score = _clamp(macd_out[2] / price / 0.003) if macd_out else 0.0

    # 4-bar price momentum.
    ret_4 = (price / closes[-5] - 1.0) if len(closes) >= 5 and closes[-5] else 0.0
    mom_score = _clamp(ret_4 / 0.02)

    technical = _clamp(0.40 * trend_score + 0.25 * rsi_score + 0.20 * macd_score + 0.15 * mom_score)

    # ── Derivatives sub-score ─────────────────────────────────────────────
    # Funding: a moderately positive rate confirms bullish demand, but an
    # extreme one (over-leveraged longs paying a steep premium) is a CONTRARIAN
    # warning. Model as bullish up to ~1.5 bps, fading and flipping negative as
    # it gets crowded. Mirror for deeply negative (crowded shorts → bullish).
    funding_score = 0.0
    squeeze_flag = "neutral"
    if funding_bps_8h is not None:
        b = funding_bps_8h
        if b >= 0:
            funding_score = _clamp((1.5 - b) / 3.0)  # +0.5 at 0bps, 0 at 1.5, -1 at 4.5
        else:
            funding_score = _clamp((-1.5 - b) / -3.0)  # mirror: crowded shorts → bullish
        if b > 4.0:
            squeeze_flag = "crowded_longs"
        elif b < -4.0:
            squeeze_flag = "crowded_shorts"

    # OI trend confirms whichever way technicals lean: rising OI + uptrend =
    # real capital entering; rising OI + downtrend = shorts pressing.
    oi_score = 0.0
    if oi_change_24h_pct is not None:
        confirm = _clamp(oi_change_24h_pct / 10.0)  # +10% OI = full confirmation
        oi_score = confirm * (1.0 if technical >= 0 else -1.0)

    derivatives = _clamp(0.6 * funding_score + 0.4 * oi_score)

    # ── Sentiment sub-score ───────────────────────────────────────────────
    sentiment = _clamp(sentiment_score) if (sentiment_score is not None and sentiment_n > 0) else 0.0

    # ── Blend ─────────────────────────────────────────────────────────────
    score = _clamp(_W_TECH * technical + _W_DERIV * derivatives + _W_SENTIMENT * sentiment)

    if score > _DIRECTION_BAND:
        direction = "long"
    elif score < -_DIRECTION_BAND:
        direction = "short"
    else:
        direction = "neutral"

    # Confidence: magnitude of the score, boosted when components agree in sign.
    sign = 1.0 if score >= 0 else -1.0
    agree = sum(1 for s in (technical, derivatives, sentiment) if s * sign > 0)
    confidence = round(_clamp(abs(score) * (0.55 + 0.15 * agree), 0.0, 1.0), 3)

    # ── ATR-based, horizon-scaled targets ─────────────────────────────────
    # ``atr_bar`` is the per-bar ATR at the bucket's grain (1h candles for
    # intraday/swing). ``horizon.atr_targets`` scales it to the horizon (√bars)
    # and applies the per-bucket multiplier (fat-tail premium grows with hold).
    atr_bar = atr(highs, lows, closes, 14)
    geom = hz.atr_targets(price, atr_bar, bucket, direction)
    spec = hz.resolve(bucket)
    h_atr = geom["horizon_atr"]

    entry = round(price, 6)
    return {
        "ok": True,
        "direction": direction,
        "score": round(score, 3),
        "confidence": confidence,
        "confidence_label": _confidence_label(confidence),
        "horizon": spec["name"],
        "horizon_hours": spec["hours"],
        "entry": entry,
        "target": geom["target"],
        "stop": geom["stop"],
        "target_pct": geom["target_pct"],
        "stop_pct": geom["stop_pct"],
        "rr": geom["rr"],
        "horizon_atr": h_atr,
        "horizon_atr_pct": geom["horizon_atr_pct"],
        # Back-compat aliases for the existing 4-Hour Signals frontend.
        "atr_4h": h_atr,
        "atr_4h_pct": geom["horizon_atr_pct"],
        "components": {
            "technical": round(technical, 3),
            "derivatives": round(derivatives, 3),
            "sentiment": round(sentiment, 3),
        },
        "technical_detail": {
            "ema_fast": round(ema_fast, 6),
            "ema_slow": round(ema_slow, 6),
            "trend": round(trend_score, 3),
            "rsi": round(rsi_val, 2) if rsi_val is not None else None,
            "rsi_score": round(rsi_score, 3),
            "macd_hist": round(macd_out[2], 6) if macd_out else None,
            "macd_score": round(macd_score, 3),
            "momentum_4bar_pct": round(ret_4 * 100.0, 2),
        },
        "derivatives_detail": {
            "funding_bps_8h": funding_bps_8h,
            "funding_score": round(funding_score, 3),
            "oi_change_24h_pct": oi_change_24h_pct,
            "oi_score": round(oi_score, 3),
            "squeeze_flag": squeeze_flag,
        },
        "sentiment_detail": {"score": sentiment, "n": sentiment_n},
    }


# ---------------------------------------------------------------------------
# Live orchestration (fetch → compute)
# ---------------------------------------------------------------------------


def _fetch_candles(symbol: str, bucket: str = "intraday") -> tuple[list[dict[str, float]], str]:
    """Oldest-first OHLC candles at the bucket's grain. Returns (rows, grain).

    Intraday/swing want hourly bars (daily fallback); position/long want daily
    bars natively, so the per-bar ATR matches the horizon's bar length.
    """
    spec = hz.resolve(bucket)
    if spec["bars"] == "1h":
        try:
            rows = cd.coin_history_hourly(symbol, hours=200)
            if len(rows) >= 30:
                return list(reversed(rows)), "1h"
        except CoinDeskError as exc:
            log.info("hourly candles unavailable for %s, falling back to daily: %s", symbol, exc)
    # Daily — native for position/long, and the hourly fallback. ~180d gives the
    # EMA-21 / MACD(26,9) / ATR-14 stack ample history.
    daily = cd.ohlcv(symbol, days=180)
    return list(reversed(daily)), "1d"


def _fetch_derivatives(symbol: str) -> tuple[float | None, float | None]:
    """(funding_bps_8h, oi_change_24h_pct), each best-effort / None on failure."""
    funding_bps: float | None = None
    oi_change: float | None = None
    try:
        fr = cd.funding_rate(symbol)
        funding_bps = fr.get("rate_8h_bps")
    except CoinDeskError as exc:
        log.info("funding rate unavailable for %s: %s", symbol, exc)
    try:
        hist = cd.open_interest_history(symbol, days=3)
        closes = [r["close"] for r in hist]  # newest-first
        if len(closes) > 1 and closes[1]:
            oi_change = (closes[0] / closes[1] - 1.0) * 100.0
    except CoinDeskError as exc:
        log.info("open interest unavailable for %s: %s", symbol, exc)
    return funding_bps, oi_change


def _fetch_sentiment(symbol: str) -> tuple[float, int, list[dict[str, Any]]]:
    """Mean recent crypto-news sentiment in [-1,1], count, and the headlines."""
    try:
        from app.tools.news_tools import search_news
        articles = search_news.invoke({"query": symbol, "limit": 6, "asset_class": "crypto"})
    except Exception as exc:  # noqa: BLE001 — news is best-effort, never block a signal
        log.info("news sentiment unavailable for %s: %s", symbol, exc)
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


def _rationale(symbol: str, plan: dict[str, Any]) -> str:
    """One-paragraph human read of the plan, English (UI localises labels)."""
    d = plan["direction"]
    comp = plan["components"]
    td = plan["technical_detail"]
    verb = {"long": "favours longs", "short": "favours shorts", "neutral": "is balanced — stand aside"}[d]
    bits = [f"{symbol} {verb} over the next {plan['horizon_hours']}h (score {plan['score']:+.2f}, "
            f"{plan['confidence_label']} confidence)."]
    bits.append(
        f"Technicals {comp['technical']:+.2f} (EMA-9 {'>' if td['ema_fast'] >= td['ema_slow'] else '<'} EMA-21, "
        f"RSI {td['rsi'] if td['rsi'] is not None else 'n/a'}); "
        f"derivatives {comp['derivatives']:+.2f}; news {comp['sentiment']:+.2f}."
    )
    if plan.get("target") is not None:
        bits.append(
            f"Plan: entry {plan['entry']}, target {plan['target']} ({plan['target_pct']:+.2f}%), "
            f"stop {plan['stop']} ({plan['stop_pct']:+.2f}%), R:R {plan['rr']}:1."
        )
    return " ".join(bits)


def analyze_short_term(
    symbol: str, *, bucket: str = "intraday", with_news: bool = True
) -> dict[str, Any]:
    """Full live, horizon-sized plan for a crypto symbol. Returns the calc envelope.

    ``bucket`` is an :mod:`app.services.horizon` name (default ``intraday`` = 4h).
    Degrades gracefully: derivatives and news are best-effort, so a signal is
    still produced from technicals alone if the futures/news feeds are down.
    """
    base = cd._symbol(symbol)
    spec = hz.resolve(bucket)
    cache_key = f"short_term:{base}:{spec['name']}:{int(with_news)}"
    cached = cache_get(cache_key)
    if isinstance(cached, dict):
        return cached

    try:
        candles, grain = _fetch_candles(base, spec["name"])
    except CoinDeskError as exc:
        return err(str(exc), symbol=symbol)
    if len(candles) < 26:
        return err(f"Not enough price history to build a {spec['hours']}h signal for {base}", symbol=symbol)

    funding_bps, oi_change = _fetch_derivatives(base)
    sent_score, sent_n, headlines = _fetch_sentiment(base) if with_news else (0.0, 0, [])

    plan = compute_short_term_signal(
        candles,
        bucket=spec["name"],
        funding_bps_8h=funding_bps,
        oi_change_24h_pct=oi_change,
        sentiment_score=sent_score,
        sentiment_n=sent_n,
    )
    if not plan.get("ok"):
        return err(plan.get("error", "signal computation failed"), symbol=symbol)

    plan["symbol"] = base
    plan["ticker"] = f"{base}-USD"
    plan["asset_class"] = "crypto"
    plan["grain"] = grain
    plan["news"] = headlines
    plan["as_of"] = datetime.now(UTC).isoformat()
    rationale = _rationale(base, plan)

    arrow = {"long": "▲", "short": "▼", "neutral": "■"}[plan["direction"]]
    result = ok(
        raw_value=plan["score"],
        formatted_value=(
            f"{arrow} {plan['direction'].upper()} · {plan['confidence_label']} "
            f"({plan['confidence']:.0%})"
            + (f" · target {plan['target_pct']:+.2f}%" if plan.get("target_pct") is not None else "")
        ),
        formula="0.50·technical + 0.30·derivatives + 0.20·sentiment → ATR-based horizon target",
        explanation=rationale,
        ui_type="metric",
        data=plan,
        source="coindesk+news",
        rationale=rationale,
    )
    cache_set(cache_key, result)
    return result


@tool
def get_crypto_short_term_plan(symbol: str) -> dict[str, Any]:
    """Build a risk-defined 4-hour trade plan for a crypto asset.

    Fuses intraday technicals (EMA-9/21 trend, RSI-14, MACD, momentum), the
    perpetual derivatives layer (funding rate as a crowded-leverage/contrarian
    read + open-interest trend) and recent news sentiment into a single
    directional call with an ATR-based entry, profit target and stop-loss sized
    to a 4-hour horizon. Use this for short-term ("next few hours") crypto
    trade questions — NOT for long-term allocation (use analyze_ticker_8dim).

    Args:
        symbol: e.g. "BTC", "ETH", "SOL" (or "BTC-USD" — the base is used).
    """
    return analyze_short_term(symbol)


def _plan_summary(p: dict[str, Any]) -> dict[str, Any]:
    """Compact, JSON-safe view of a plan for tool returns."""
    return {
        "ticker": p.get("ticker"),
        "direction": p.get("direction"),
        "entry": p.get("entry"),
        "target": p.get("target"),
        "target_pct": p.get("target_pct"),
        "stop": p.get("stop"),
        "stop_pct": p.get("stop_pct"),
        "rr": p.get("rr"),
        "confidence": p.get("confidence"),
        "score": p.get("score"),
        "horizon_hours": p.get("horizon_hours"),
        "components": p.get("components"),
    }


@tool
def set_crypto_trade_target(symbol: str) -> dict[str, Any]:
    """Analyze a crypto's 4-hour outlook AND OPEN a trade target (order) for the user.

    The target is persisted and appears LIVE on the Markets "4-Hour Signals"
    panel (entry, profit target, stop, countdown, live P&L). Use this whenever
    the user wants to ACT on a named coin short-term — "open a trade / take a
    position / al / pozisyon aç / bunu izlemeye al / 4 saatlik işlem aç" on BTC,
    ETH, SOL, or any coin. For analysis WITHOUT placing an order, use
    get_crypto_short_term_plan instead.

    If the signal is neutral (no clear 4-hour edge), NO order is placed and the
    tool says so — never force a trade.

    Args:
        symbol: e.g. "BTC", "ETH", "SOL" (or "BTC-USD" — the base is used).
    """
    user_id = get_current_user_id_or_none()
    if user_id is None:
        return {"ok": False, "error": "no user in context"}
    result = analyze_short_term(symbol)
    if not result.get("ok"):
        return {"ok": False, "error": result.get("error", "signal failed"), "symbol": symbol}
    plan = result.get("data") or {}
    if plan.get("direction") == "neutral" or plan.get("target") is None:
        return {
            "ok": True,
            "placed": False,
            "direction": "neutral",
            "message": (
                f"{plan.get('symbol', symbol)} has no clear 4-hour edge right now "
                "(neutral) — no order placed. Standing aside is the correct call."
            ),
            "plan": _plan_summary(plan),
        }
    with SessionLocal() as db:
        tgt = upsert_target_from_plan(db, user_id, result)
        db.commit()
        tid = tgt.id if tgt is not None else None
    return {
        "ok": True,
        "placed": True,
        "target_id": tid,
        "message": (
            f"Opened a {plan['direction'].upper()} on {plan['ticker']}: "
            f"entry {plan['entry']}, target {plan['target']} ({plan['target_pct']:+.2f}%), "
            f"stop {plan['stop']} ({plan['stop_pct']:+.2f}%), R:R {plan['rr']}:1, "
            f"{plan['horizon_hours']}h horizon. It's now live on the 4-Hour Signals panel."
        ),
        "plan": _plan_summary(plan),
    }


@tool
def open_best_crypto_trade(symbols: list[str] | None = None) -> dict[str, Any]:
    """Scan several cryptos, pick the single HIGHEST-CONVICTION 4-hour setup, and OPEN it.

    Use when the user asks you to choose — "pick the best crypto to trade right
    now", "find me the best short-term setup", "en iyi kriptoyu seç ve işlem aç".
    Ranks each candidate's 4-hour signal by confidence, opens a trade target for
    the strongest DIRECTIONAL one (long or short), and it appears live on the
    Markets "4-Hour Signals" panel. If every candidate is neutral, no order is
    placed and the tool says the market is balanced.

    Args:
        symbols: optional list like ["BTC","ETH","SOL","DOGE"]. Defaults to the
            curated basket (BTC/ETH/SOL — deep news + derivatives coverage).
    """
    user_id = get_current_user_id_or_none()
    if user_id is None:
        return {"ok": False, "error": "no user in context"}
    syms = [s.strip().upper() for s in (symbols or settings.crypto_basket) if s and s.strip()]
    ranking: list[dict[str, Any]] = []
    best: tuple[dict[str, Any], dict[str, Any]] | None = None  # (plan, full result)
    for s in syms:
        res = analyze_short_term(s)
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
            "placed": False,
            "message": (
                "No clear 4-hour trade across the scanned coins right now — the "
                "market is balanced, so standing aside is the right move."
            ),
            "ranking": ranking,
        }
    plan, result = best
    with SessionLocal() as db:
        tgt = upsert_target_from_plan(db, user_id, result)
        db.commit()
        tid = tgt.id if tgt is not None else None
    return {
        "ok": True,
        "placed": True,
        "chosen": plan["ticker"],
        "target_id": tid,
        "message": (
            f"Best 4-hour setup: {plan['direction'].upper()} on {plan['ticker']} "
            f"(confidence {plan['confidence']:.0%}). Entry {plan['entry']}, target "
            f"{plan['target']} ({plan['target_pct']:+.2f}%), stop {plan['stop']}, "
            f"R:R {plan['rr']}:1. Opened and live on the 4-Hour Signals panel."
        ),
        "plan": _plan_summary(plan),
        "ranking": ranking,
    }
