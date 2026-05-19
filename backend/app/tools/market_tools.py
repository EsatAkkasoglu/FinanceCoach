"""Market data tools — prices, fundamentals, technicals, 8-dim analysis.

Data sources
────────────
  Prices (stocks, ETFs, indices, forex, Treasury): yfinance
  Crypto quotes   : CoinGecko (primary) → yfinance (fallback)
  Trending (crypto): CoinGecko /trending (always available)
  Fundamentals    : yfinance
  Technicals      : yfinance (SMA/RSI computed from daily bars)
  US stock movers : unavailable (was AV-only; removed)
"""
from __future__ import annotations

import logging
import statistics
from datetime import datetime
from typing import Any

from langchain_core.tools import tool

import app.services.coingecko as cg
import app.services.yfinance_service as yf_svc
from app.services.coingecko import CoinGeckoError
from app.services.yfinance_service import YFinanceError
from app.tools._cache import cache_get, cache_set

log = logging.getLogger("fincoach.tools.market")


# ---------------------------------------------------------------------------
# Ticker classifier (previously in alpha_vantage service)
# ---------------------------------------------------------------------------

_INDEX_TICKERS = frozenset({
    "^GSPC", "^IXIC", "^DJI", "^NDX", "^RUT", "^VIX",
    "^FTSE", "^N225", "^GDAXI", "XU100.IS",
})

# yfinance treasury tickers → maturity codes
_TREASURY_MAP: dict[str, str] = {
    "^TNX": "10year",
    "^TYX": "30year",
    "^IRX": "3month",
    "^FVX": "5year",
}
# reverse: maturity code → yfinance ticker
_MATURITY_TO_YF: dict[str, str] = {v: k for k, v in _TREASURY_MAP.items()}

_FUTURES_PROXY_MAP: dict[str, str] = {
    "GC=F": "GLD",
    "SI=F": "SLV",
    "CL=F": "USO",
    "NG=F": "UNG",
    "HG=F": "CPER",
}


def classify_ticker(ticker: str) -> dict[str, Any]:
    """Classify a ticker into kind + normalized symbols for dispatch."""
    t = (ticker or "").strip().upper()
    if not t:
        return {"kind": "unknown", "input": ticker}
    if t in _TREASURY_MAP:
        return {"kind": "treasury", "maturity": _TREASURY_MAP[t], "input": t}
    if t in _FUTURES_PROXY_MAP:
        return {"kind": "futures_proxy", "symbol": _FUTURES_PROXY_MAP[t], "input": t, "proxy": True}
    if t in _INDEX_TICKERS or (t.startswith("^") and t not in _TREASURY_MAP):
        return {"kind": "index", "symbol": t, "input": t}
    if "-" in t and t.endswith("-USD"):
        return {"kind": "crypto", "base": t.split("-")[0], "quote": "USD", "input": t}
    if t.endswith("=X") and len(t) == 8:
        pair = t[:6]
        return {"kind": "forex", "from": pair[:3], "to": pair[3:], "input": t}
    if t in {"DX-Y.NYB", "DXY"}:
        return {"kind": "stock", "symbol": "UUP", "input": t, "proxy": True}
    return {"kind": "stock", "symbol": t, "input": t}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _change_pct(price: float | None, prev: float | None) -> float:
    if price is None or prev is None or not prev:
        return 0.0
    return (price - prev) / prev * 100.0


# ---------------------------------------------------------------------------
# Internal quote builders (one per asset class)
# ---------------------------------------------------------------------------


def _quote_stock(symbol: str) -> dict[str, Any]:
    """yfinance → İş Yatırım (.IS only) fallback chain."""
    try:
        q = yf_svc.quote(symbol)
        return {
            "price": q["price"],
            "previous_close": q["previous_close"],
            "currency": q.get("currency", "USD"),
            "via": "yfinance",
            "volume": q.get("volume"),
            "as_of_date": _now_iso(),
            "source": "yfinance",
        }
    except YFinanceError:
        if symbol.upper().endswith(".IS"):
            from app.services import isyatirim as iy_svc  # noqa: PLC0415
            q = iy_svc.quote(symbol)
            return {
                "price": q["price"],
                "previous_close": q["previous_close"],
                "currency": "TRY",
                "via": "isyatirim",
                "volume": q.get("volume"),
                "as_of_date": q.get("as_of"),
                "source": "isyatirim",
            }
        raise


def _quote_index(symbol: str) -> dict[str, Any]:
    """yfinance — passes ^GSPC, ^VIX etc. directly."""
    q = yf_svc.quote(symbol)
    return {
        "price": q["price"],
        "previous_close": q["previous_close"],
        "currency": "USD",
        "via": "yfinance",
        "as_of_date": _now_iso(),
        "source": "yfinance",
    }


def _quote_treasury(maturity: str) -> dict[str, Any]:
    """Treasury yield via yfinance (^TNX, ^TYX, ^IRX, ^FVX)."""
    yf_symbol = _MATURITY_TO_YF.get(maturity, "^TNX")
    q = yf_svc.quote(yf_symbol)
    return {
        "price": q["price"],
        "previous_close": q["previous_close"],
        "currency": "PCT",
        "via": "yfinance",
        "as_of_date": _now_iso(),
        "source": "yfinance",
    }


def _quote_forex(from_ccy: str, to_ccy: str) -> dict[str, Any]:
    """Forex via yfinance (EURUSD=X style)."""
    yf_symbol = f"{from_ccy}{to_ccy}=X"
    q = yf_svc.quote(yf_symbol)
    return {
        "price": q["price"],
        "previous_close": q["previous_close"],
        "currency": to_ccy,
        "via": "yfinance",
        "as_of": _now_iso(),
        "source": "yfinance",
    }


def _quote_crypto(base: str, quote: str = "USD") -> dict[str, Any]:
    """Crypto quote: CoinGecko primary, yfinance fallback."""
    try:
        row = cg.coin_price(base, currency=quote.lower())
        return {
            "price": row["price"],
            "previous_close": row["previous_close"],
            "currency": quote,
            "via": "coingecko_markets",
            "as_of": row.get("last_updated"),
            "source": "coingecko",
        }
    except CoinGeckoError as exc:
        log.info("CoinGecko failed for %s/%s, trying yfinance: %s", base, quote, exc)

    yf_symbol = f"{base}-{quote}"
    q = yf_svc.quote(yf_symbol)
    return {
        "price": q["price"],
        "previous_close": q["previous_close"],
        "currency": quote,
        "via": "yfinance",
        "as_of": _now_iso(),
        "source": "yfinance",
    }


# ---------------------------------------------------------------------------
# Public tools
# ---------------------------------------------------------------------------


@tool
def get_quote(ticker: str) -> dict[str, Any]:
    """Get the latest price and 1-day change for ANY supported ticker.

    Supported:
        AAPL, NVDA           — US stocks (yfinance)
        BTC-USD, ETH-USD     — crypto (CoinGecko → yfinance fallback)
        SPY, QQQ, VTI, GLD   — ETFs (yfinance)
        ^GSPC, ^IXIC, ^VIX   — indices (yfinance)
        EURUSD=X, USDTRY=X   — forex (yfinance)
        ^TNX, ^TYX           — Treasury yields (yfinance)
        GC=F, CL=F           — commodity futures (proxied via ETF: GLD/USO)

    For asset NAMES (e.g. "gold", "S&P 500"), call ``resolve_symbol`` first.

    Returns:
        {ticker, price, change_pct, currency, as_of, source, via}
    """
    cache_key = f"get_quote:{(ticker or '').strip().upper()}"
    cached = cache_get(cache_key)
    if isinstance(cached, dict):
        return cached

    cls = classify_ticker(ticker)
    kind = cls.get("kind")
    upper = (ticker or "").strip().upper()
    try:
        if kind in {"stock", "futures_proxy"}:
            result = _quote_stock(cls["symbol"])
        elif kind == "index":
            result = _quote_index(cls["symbol"])
        elif kind == "treasury":
            result = _quote_treasury(cls["maturity"])
        elif kind == "forex":
            result = _quote_forex(cls["from"], cls["to"])
        elif kind == "crypto":
            result = _quote_crypto(cls["base"], cls["quote"])
        else:
            return {"ticker": upper, "error": f"unsupported ticker shape: {ticker}"}

        price = result.get("price")
        prev = result.get("previous_close")
        if price is None:
            return {"ticker": upper, "error": "no price data"}

        quote_result = {
            "ticker": upper,
            "price": round(float(price), 4),
            "change_pct": round(_change_pct(price, prev), 2),
            "currency": result.get("currency", "USD"),
            "as_of": result.get("as_of") or result.get("as_of_date") or _now_iso(),
            "source": result.get("source", "yfinance"),
            "via": result.get("via"),
        }
        if cls.get("proxy"):
            quote_result["proxy_for"] = cls["input"]
        cache_set(cache_key, quote_result)
        return quote_result
    except Exception as exc:  # noqa: BLE001
        log.warning("get_quote failure for %s: %s", upper, exc)
        return {"ticker": upper, "error": str(exc)}


@tool
def get_company_overview(ticker: str) -> dict[str, Any]:
    """Fundamentals + analyst block for any listed equity or ETF.

    Returns valuation, profitability, growth, dividend, and analyst-rating
    fields. Backed by yfinance (no API key required).

    Returns: {
        ticker, name, sector, industry, exchange, currency, description,
        market_cap, pe_ratio, forward_pe, peg_ratio, price_to_book,
        eps, profit_margin, operating_margin, roe, roa,
        revenue_ttm, ebitda, beta,
        week_52_high, week_52_low, sma_50d, sma_200d,
        dividend_yield, dividend_per_share, ex_dividend_date,
        analyst_target_price, analyst_strong_buy, analyst_buy,
        analyst_hold, analyst_sell, analyst_strong_sell,
        source
    }
    """
    cache_key = f"overview:{(ticker or '').strip().upper()}"
    cached = cache_get(cache_key)
    if isinstance(cached, dict):
        return cached
    upper = (ticker or "").strip().upper()
    try:
        result = yf_svc.overview(upper)
        cache_set(cache_key, result)
        return result
    except YFinanceError as exc:
        log.warning("overview failed for %s: %s", upper, exc)
        return {"ticker": upper, "error": str(exc)}


@tool
def get_technical_indicators(
    ticker: str,
    sma_period: int = 50,
    rsi_period: int = 14,
) -> dict[str, Any]:
    """Latest SMA and RSI for a ticker (computed from yfinance daily bars).

    Use when the agent needs momentum / trend context: "is X overbought?",
    "is X above its 50-day SMA?", "is the momentum positive?". Reports the
    current SMA value, RSI value, an interpretation (overbought / oversold /
    neutral) and the SMA-cross signal vs the current quote.

    Args:
        ticker: e.g. "AAPL", "NVDA", "BTC-USD".
        sma_period: lookback window for the simple moving average (default 50).
        rsi_period: lookback window for the Relative Strength Index (default 14).
    """
    upper = (ticker or "").strip().upper()
    try:
        sma_rows = yf_svc.sma(upper, period=sma_period)
        rsi_rows = yf_svc.rsi(upper, period=rsi_period)
    except YFinanceError as exc:
        return {"ticker": upper, "error": str(exc)}

    sma_latest = sma_rows[0]["sma"] if sma_rows else None
    rsi_latest = rsi_rows[0]["rsi"] if rsi_rows else None

    if rsi_latest is None:
        rsi_signal = "n/a"
    elif rsi_latest >= 70:
        rsi_signal = "overbought"
    elif rsi_latest <= 30:
        rsi_signal = "oversold"
    else:
        rsi_signal = "neutral"

    sma_signal: str = "n/a"
    quote = get_quote.invoke({"ticker": upper})
    spot_price = quote.get("price") if isinstance(quote, dict) else None
    if isinstance(spot_price, int | float) and sma_latest:
        sma_signal = "above_sma" if spot_price > sma_latest else "below_sma"

    return {
        "ticker": upper,
        "sma": {
            "period": sma_period,
            "value": round(sma_latest, 4) if sma_latest is not None else None,
            "as_of": sma_rows[0]["date"] if sma_rows else None,
            "signal": sma_signal,
        },
        "rsi": {
            "period": rsi_period,
            "value": round(rsi_latest, 2) if rsi_latest is not None else None,
            "as_of": rsi_rows[0]["date"] if rsi_rows else None,
            "signal": rsi_signal,
        },
        "current_price": spot_price,
        "source": "yfinance",
    }


# ---------------------------------------------------------------------------
# 8-dimension analysis (yfinance-backed)
# ---------------------------------------------------------------------------


_RISK_WEIGHTS = {
    "earnings_surprise": 0.12,
    "fundamentals": 0.18,
    "analyst_sentiment": 0.15,
    "historical": 0.10,
    "market_context": 0.10,
    "sector": 0.05,
    "momentum": 0.15,
    "sentiment": 0.15,
}


def _surprises_to_score(surprises: list[float], *, source: str) -> tuple[float, dict[str, Any]]:
    if not surprises:
        return 0.5, {"surprises": [], "source": source}
    avg = sum(surprises) / len(surprises)
    score = max(0.0, min(1.0, 0.5 + (avg / 40.0)))
    return score, {
        "recent_surprise_pct": round(surprises[0], 2),
        "avg_4q_surprise_pct": round(avg, 2),
        "source": source,
    }


def _score_earnings_surprise(symbol: str) -> tuple[float, dict[str, Any]]:
    try:
        rows = yf_svc.earnings_surprises(symbol, limit=4)
        surprises = [r["surprise_pct"] for r in rows]
        return _surprises_to_score(surprises, source="yfinance")
    except YFinanceError as exc:
        return 0.5, {"error": str(exc), "unavailable": True}


def _fundamentals_from_overview(ov: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    """Score PE, profit margin, ROE from a yfinance overview dict."""
    def f(k: str) -> float | None:
        v = ov.get(k)
        try:
            return float(v) if v not in (None, "", "None", "-") else None
        except (TypeError, ValueError):
            return None

    pe = f("pe_ratio")
    profit_margin = f("profit_margin")
    roe = f("roe")
    sub_scores: list[float] = []
    detail: dict[str, Any] = {}
    if pe is not None and pe > 0:
        detail["pe_ratio"] = pe
        sub_scores.append(max(0.0, min(1.0, 1.0 - (pe - 10) / 30.0)))
    if profit_margin is not None:
        detail["profit_margin"] = profit_margin
        sub_scores.append(max(0.0, min(1.0, profit_margin / 0.25)))
    if roe is not None:
        detail["roe"] = roe
        sub_scores.append(max(0.0, min(1.0, roe / 0.25)))
    score = statistics.mean(sub_scores) if sub_scores else 0.5
    detail["sector"] = ov.get("sector")
    detail["source"] = "yfinance"
    return score, detail


def _score_fundamentals(symbol: str) -> tuple[float, dict[str, Any]]:
    try:
        return _fundamentals_from_overview(yf_svc.overview(symbol))
    except YFinanceError as exc:
        return 0.5, {"error": str(exc), "unavailable": True}


def _analyst_from_overview(ov: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    keys = ("analyst_strong_buy", "analyst_buy", "analyst_hold",
            "analyst_sell", "analyst_strong_sell")
    target = ov.get("analyst_target_price")

    def i(k: str) -> int:
        try:
            return int(float(ov.get(k) or 0))
        except (TypeError, ValueError):
            return 0

    sb, b, h, s, ss = (i(k) for k in keys)
    total = sb + b + h + s + ss
    if total == 0:
        return 0.5, {"coverage": "none", "source": "yfinance"}
    weighted = sb * 1.0 + b * 0.75 + h * 0.5 + s * 0.25 + ss * 0.0
    return weighted / total, {
        "strong_buy": sb, "buy": b, "hold": h, "sell": s, "strong_sell": ss,
        "total_analysts": total, "target_price": target, "source": "yfinance",
    }


def _score_analyst_sentiment(symbol: str) -> tuple[float, dict[str, Any]]:
    try:
        return _analyst_from_overview(yf_svc.overview(symbol))
    except YFinanceError as exc:
        return 0.5, {"error": str(exc), "unavailable": True}


def _historical_from_bars(bars: list[dict[str, Any]]) -> tuple[float, dict[str, Any]]:
    if len(bars) < 50:
        return 0.5, {"bars": len(bars), "unavailable": True}
    window = bars[:252] if len(bars) >= 252 else bars
    closes = [b["close"] for b in window if b["close"] is not None]
    if not closes:
        return 0.5, {"unavailable": True}
    latest, hi, lo = closes[0], max(closes), min(closes)
    rng = hi - lo
    score = (latest - lo) / rng if rng else 0.5
    return max(0.0, min(1.0, score)), {
        "year_high": round(hi, 2),
        "year_low": round(lo, 2),
        "year_return_pct": round((latest / closes[-1] - 1) * 100.0, 2) if closes[-1] else None,
    }


def _score_historical(symbol: str) -> tuple[float, dict[str, Any]]:
    try:
        bars = yf_svc.history(symbol, period="1y")
        score, detail = _historical_from_bars(bars)
        detail["source"] = "yfinance"
        return score, detail
    except YFinanceError as exc:
        return 0.5, {"error": str(exc), "unavailable": True}


def _score_market_context() -> tuple[float, dict[str, Any]]:
    try:
        q = yf_svc.quote("^VIX")
        vix = q.get("price")
    except YFinanceError as exc:
        return 0.5, {"vix": None, "error": str(exc), "unavailable": True}
    if vix is None:
        return 0.5, {"vix": None, "unavailable": True}
    score = max(0.0, min(1.0, (35 - vix) / 23.0))
    regime = "calm" if vix < 20 else "elevated" if vix < 30 else "stressed"
    return score, {"vix": round(vix, 2), "regime": regime, "source": "yfinance"}


_SECTOR_ETFS = {
    "Technology": "XLK",
    "Information Technology": "XLK",
    "Financials": "XLF",
    "Financial Services": "XLF",
    "Energy": "XLE",
    "Health Care": "XLV",
    "Healthcare": "XLV",
    "Consumer Discretionary": "XLY",
    "Consumer Cyclical": "XLY",
    "Consumer Staples": "XLP",
    "Consumer Defensive": "XLP",
    "Industrials": "XLI",
    "Materials": "XLB",
    "Utilities": "XLU",
    "Real Estate": "XLRE",
    "Communication Services": "XLC",
}


def _score_sector(sector: str | None) -> tuple[float, dict[str, Any]]:
    if not sector:
        return 0.5, {"sector": None, "unavailable": True}
    etf = _SECTOR_ETFS.get(sector)
    if not etf:
        return 0.5, {"sector": sector, "etf": None, "unavailable": True}
    try:
        yq = yf_svc.quote(etf)
        price, prev = yq.get("price"), yq.get("previous_close")
        if price is not None and prev:
            change = (price - prev) / prev * 100.0
            score = max(0.0, min(1.0, 0.5 + change / 6.0))
            return score, {"sector": sector, "etf": etf, "day_change_pct": round(change, 2), "source": "yfinance"}
    except YFinanceError as exc:
        return 0.5, {"sector": sector, "etf": etf, "error": str(exc), "unavailable": True}
    return 0.5, {"sector": sector, "etf": etf, "unavailable": True}


def _momentum_from_values(
    rsi_v: float | None, sma_v: float | None, price: float | None, source: str,
) -> tuple[float, dict[str, Any]]:
    detail: dict[str, Any] = {"rsi": rsi_v, "sma_50d": sma_v, "source": source}
    sub: list[float] = []
    if rsi_v is not None:
        if rsi_v >= 75:
            sub.append(0.4)
        elif rsi_v >= 60:
            sub.append(0.8)
        elif rsi_v >= 45:
            sub.append(0.6)
        elif rsi_v >= 30:
            sub.append(0.4)
        else:
            sub.append(0.2)
    if price is not None and sma_v:
        gap = (price - sma_v) / sma_v
        detail["price_vs_sma_pct"] = round(gap * 100.0, 2)
        sub.append(max(0.0, min(1.0, 0.5 + gap * 5)))
    if not sub:
        detail["unavailable"] = True
        return 0.5, detail
    return statistics.mean(sub), detail


def _score_momentum(symbol: str) -> tuple[float, dict[str, Any]]:
    try:
        rsi_rows = yf_svc.rsi(symbol, period=14)
        sma_rows = yf_svc.sma(symbol, period=50)
        rsi_v = rsi_rows[0]["rsi"] if rsi_rows else None
        sma_v = sma_rows[0]["sma"] if sma_rows else None
        try:
            price = yf_svc.quote(symbol).get("price")
        except YFinanceError:
            price = None
        return _momentum_from_values(rsi_v, sma_v, price, source="yfinance")
    except YFinanceError as exc:
        return 0.5, {"error": str(exc), "unavailable": True}


def _score_sentiment(_symbol: str) -> tuple[float, dict[str, Any]]:
    """News sentiment dimension — not available without AV; returns neutral."""
    return 0.5, {"unavailable": True, "note": "news sentiment not available"}


def _recommendation(final_score: float) -> str:
    if final_score >= 0.70:
        return "BUY"
    if final_score <= 0.40:
        return "SELL"
    return "HOLD"


@tool
def analyze_ticker_8dim(ticker: str, fast: bool = False) -> dict[str, Any]:
    """Run the 8-dimension analysis on a US stock or ETF.

    Dimensions: earnings_surprise, fundamentals, analyst_sentiment, historical,
    market_context, sector, momentum, sentiment. Each scored 0–1, then a
    weighted score (0–1) yields a BUY (>=0.70) / HOLD / SELL (<=0.40)
    recommendation. Backed by yfinance (no rate limits).

    Args:
        ticker: e.g. "NVDA", "AAPL". US equities/ETFs recommended.
        fast: skip the news-sentiment dimension (no effect — sentiment is
            always neutral without a news API).
    """
    cache_key = f"8dim:{(ticker or '').strip().upper()}:{int(bool(fast))}"
    cached = cache_get(cache_key)
    if isinstance(cached, dict):
        return cached

    upper = (ticker or "").strip().upper()
    cls = classify_ticker(upper)
    if cls.get("kind") not in {"stock", "futures_proxy"}:
        return {
            "ticker": upper,
            "error": (
                "8-dim analysis is only available for equities/ETFs "
                "(crypto/indices/forex lack the required fundamentals data)."
            ),
        }
    symbol = cls["symbol"]

    dims: dict[str, dict[str, Any]] = {}

    s, d = _score_fundamentals(symbol)
    dims["fundamentals"] = {"score": s, **d}
    sector_name = d.get("sector")

    s, d = _score_earnings_surprise(symbol)
    dims["earnings_surprise"] = {"score": s, **d}

    s, d = _score_analyst_sentiment(symbol)
    dims["analyst_sentiment"] = {"score": s, **d}

    s, d = _score_historical(symbol)
    dims["historical"] = {"score": s, **d}

    s, d = _score_market_context()
    dims["market_context"] = {"score": s, **d}

    s, d = _score_sector(sector_name)
    dims["sector"] = {"score": s, **d}

    s, d = _score_momentum(symbol)
    dims["momentum"] = {"score": s, **d}

    s, d = _score_sentiment(symbol)
    dims["sentiment"] = {"score": s, **d}

    unavailable = [k for k, v in dims.items() if v.get("unavailable")]
    usable_keys = [k for k in _RISK_WEIGHTS if k not in unavailable]
    total_weight = sum(_RISK_WEIGHTS[k] for k in usable_keys)
    if total_weight > 0:
        final = sum(_RISK_WEIGHTS[k] * dims[k]["score"] for k in usable_keys) / total_weight
    else:
        final = 0.5

    degraded = len(unavailable) >= 4
    result: dict[str, Any] = {
        "ticker": upper,
        "final_score": round(final, 3) if not degraded else None,
        "recommendation": _recommendation(final) if not degraded else None,
        "dimensions": {k: {**v, "score": round(v["score"], 3)} for k, v in dims.items()},
        "weights": _RISK_WEIGHTS,
        "unavailable_dimensions": unavailable,
        "source": "yfinance",
        "as_of": _now_iso(),
    }
    if degraded:
        result["degraded"] = True
        result["error"] = (
            f"Analysis degraded: {len(unavailable)}/8 dimensions unavailable "
            f"({', '.join(unavailable)}). Final score and recommendation withheld."
        )
    cache_set(cache_key, result)
    return result


# ---------------------------------------------------------------------------
# Dividend metrics
# ---------------------------------------------------------------------------


def _dividend_result_from_yf(upper: str, ov: dict[str, Any]) -> dict[str, Any]:
    def _f(v: Any) -> float | None:
        try:
            return float(v) if v not in (None, "", "None", "-") else None
        except (TypeError, ValueError):
            return None

    yield_ = _f(ov.get("dividend_yield"))
    dps = _f(ov.get("dividend_per_share"))
    eps = _f(ov.get("eps"))
    payout_ratio = (dps / eps) if (dps is not None and eps and eps > 0) else None

    by_year: dict[int, float] = {}
    try:
        import yfinance as yf  # noqa: PLC0415
        tk = yf.Ticker(upper, session=yf_svc._session())
        divs = tk.dividends
        if divs is not None and not divs.empty:
            for ts, amt in divs.items():
                try:
                    year = ts.year
                    by_year[year] = by_year.get(year, 0.0) + float(amt)
                except Exception:  # noqa: BLE001
                    pass
    except Exception:  # noqa: BLE001
        pass

    years_sorted = sorted(by_year)
    growth_5y_cagr: float | None = None
    if len(years_sorted) >= 6:
        recent = by_year[years_sorted[-1]]
        five_back = by_year[years_sorted[-6]]
        if five_back > 0:
            growth_5y_cagr = (recent / five_back) ** (1 / 5) - 1

    streak = 0
    for i in range(len(years_sorted) - 1, 0, -1):
        if by_year[years_sorted[i]] > by_year[years_sorted[i - 1]]:
            streak += 1
        else:
            break

    safety = 50.0
    if payout_ratio is not None:
        safety += max(-25.0, min(25.0, (0.6 - payout_ratio) * 50.0))
    if streak >= 10:
        safety += 15.0
    elif streak >= 5:
        safety += 8.0
    if yield_ is not None and yield_ > 0.08:
        safety -= 10.0
    safety = max(0.0, min(100.0, safety))

    if safety >= 80 and (yield_ or 0) >= 0.03:
        rating = "excellent"
    elif safety >= 65:
        rating = "good"
    elif safety >= 45:
        rating = "moderate"
    else:
        rating = "poor"

    return {
        "ticker": upper,
        "yield": yield_,
        "dividend_per_share": dps,
        "payout_ratio": round(payout_ratio, 3) if payout_ratio is not None else None,
        "growth_5y_cagr": round(growth_5y_cagr, 4) if growth_5y_cagr is not None else None,
        "consecutive_increase_years": streak,
        "ex_dividend_date": ov.get("ex_dividend_date"),
        "next_dividend_date": None,
        "safety_score": round(safety, 1),
        "income_rating": rating,
        "source": "yfinance",
    }


@tool
def get_dividend_metrics(ticker: str) -> dict[str, Any] | None:
    """Yield, payout ratio, growth (5Y CAGR), consecutive years of increases,
    safety score (0-100), income rating (excellent/good/moderate/poor).

    Backed by yfinance — covers US equities, ETFs, and international tickers.
    """
    cache_key = f"div:{(ticker or '').strip().upper()}"
    cached = cache_get(cache_key)
    if isinstance(cached, dict):
        return cached

    upper = (ticker or "").strip().upper()
    try:
        ov = yf_svc.overview(upper)
        result = _dividend_result_from_yf(upper, ov)
        cache_set(cache_key, result)
        return result
    except YFinanceError as exc:
        return {"ticker": upper, "error": str(exc)}


# ---------------------------------------------------------------------------
# BIST dividend screener — yfinance only
# ---------------------------------------------------------------------------

_BIST_UNIVERSE = [
    "THYAO.IS", "ASELS.IS", "EREGL.IS", "KCHOL.IS", "SAHOL.IS",
    "SISE.IS", "GARAN.IS", "AKBNK.IS", "ISCTR.IS", "BIMAS.IS",
    "ARCLK.IS", "TCELL.IS", "MGROS.IS", "TOASO.IS", "YKBNK.IS",
    "DOHOL.IS", "KOZAL.IS", "ENKAI.IS", "FROTO.IS", "TUPRS.IS",
    "PETKM.IS", "KRDMD.IS", "TTKOM.IS", "SODA.IS", "OTKAR.IS",
    "HALKB.IS", "VAKBN.IS", "SMRTG.IS", "TAVHL.IS", "PGSUS.IS",
    # extended BIST100 coverage
    "EKGYO.IS", "LOGO.IS", "NETAS.IS", "GUBRF.IS", "CIMSA.IS",
    "AKCNS.IS", "BRSAN.IS", "ULKER.IS", "CCOLA.IS",
    "AGHOL.IS", "ALARK.IS", "ALKIM.IS", "ANACM.IS", "AYEN.IS",
    "BAGFS.IS", "CEMTS.IS", "CEMAS.IS", "CLEBI.IS", "DOAS.IS",
    "DYOBY.IS", "EGEEN.IS", "EGPRO.IS", "EMKEL.IS", "FMIZP.IS",
    "GESAN.IS", "GOLTS.IS", "HEKTS.IS", "IPEKE.IS", "ISBTR.IS",
    "KARSN.IS", "KATMR.IS", "KCAER.IS", "KENT.IS", "KLNMA.IS",
    "KNFRT.IS", "KORDS.IS", "KRDMA.IS", "MAVI.IS", "MPARK.IS",
    "NTHOL.IS", "NTTUR.IS", "OYAKC.IS", "QUAGR.IS", "RYSAS.IS",
    "SELEC.IS", "SILVR.IS", "SKBNK.IS", "TSKB.IS", "TURSG.IS",
]


@tool
def get_bist_dividend_leaders(top_n: int = 5) -> dict[str, Any]:
    """Find the highest-dividend-yield stocks on Borsa Istanbul (BIST).

    Queries yfinance for a curated universe of BIST blue chips and returns
    the top N ranked by trailing 12-month dividend yield.

    Args:
        top_n: How many top stocks to return (default 5, max 10).
    """
    top_n = min(int(top_n), 10)
    cache_key = f"bist_div:{top_n}"
    cached = cache_get(cache_key)
    if isinstance(cached, dict):
        return cached

    results: list[dict[str, Any]] = []
    errors: list[str] = []

    for sym in _BIST_UNIVERSE:
        try:
            ov = yf_svc.overview(sym)
            y = ov.get("dividend_yield")
            if y is None:
                continue
            try:
                y_float = float(y)
            except (TypeError, ValueError):
                continue
            if y_float <= 0:
                continue
            results.append({
                "ticker": sym,
                "name": ov.get("name"),
                "dividend_yield": round(y_float, 4),
                "dividend_per_share": ov.get("dividend_per_share"),
                "pe_ratio": ov.get("pe_ratio"),
                "market_cap": ov.get("market_cap"),
                "sector": ov.get("sector"),
                "currency": ov.get("currency", "TRY"),
                "source": "yfinance",
            })
        except YFinanceError as exc:
            errors.append(f"{sym}: {exc}")
            log.debug("BIST dividend screen failed for %s: %s", sym, exc)

    results.sort(key=lambda x: x["dividend_yield"], reverse=True)
    top = results[:top_n]

    out: dict[str, Any] = {
        "top_dividend_stocks": top,
        "universe_size": len(_BIST_UNIVERSE),
        "found_with_yield": len(results),
        "as_of": _now_iso(),
        "source": "yfinance",
        "note": (
            "Dividend yields are trailing 12-month figures from yfinance. "
            "Turkish companies often pay large one-time dividends — verify "
            "sustainability before investing."
        ),
    }
    if errors:
        out["fetch_errors"] = errors[:5]
    cache_set(cache_key, out)
    return out


# ---------------------------------------------------------------------------
# BIST movers — top gainers / losers today
# ---------------------------------------------------------------------------


@tool
def get_bist_movers(top_n: int = 10) -> dict[str, Any]:
    """Find today's top gainers and losers on Borsa Istanbul (BIST).

    Fetches daily price data for a broad BIST100 universe via yfinance and
    ranks stocks by their intraday % change. Use this when the user asks
    about "en çok yükselenler", "en çok düşenler", or top movers on BIST.

    Args:
        top_n: How many gainers and losers to return (default 10, max 20).
    """
    import concurrent.futures  # noqa: PLC0415

    top_n = min(int(top_n), 20)
    cache_key = f"bist_movers:{top_n}"
    cached = cache_get(cache_key)
    if isinstance(cached, dict):
        return cached

    results: list[dict[str, Any]] = []
    errors: list[str] = []

    def _fetch_one(sym: str) -> dict[str, Any] | None:
        try:
            q = yf_svc.quote(sym)
            price = q.get("price")
            prev = q.get("previous_close")
            if price is None or not prev:
                return None
            chg = (price - prev) / prev * 100.0
            return {
                "ticker": sym,
                "price": round(float(price), 2),
                "previous_close": round(float(prev), 2),
                "change_pct": round(chg, 2),
                "currency": q.get("currency", "TRY"),
                "source": "yfinance",
            }
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{sym}: {exc}")
            return None

    # Deduplicated universe (expansion may have duplicates)
    universe = list(dict.fromkeys(_BIST_UNIVERSE))

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(_fetch_one, sym): sym for sym in universe}
        for fut in concurrent.futures.as_completed(futures):
            row = fut.result()
            if row:
                results.append(row)

    results.sort(key=lambda x: x["change_pct"], reverse=True)
    gainers = results[:top_n]
    losers = list(reversed(results))[:top_n]

    out: dict[str, Any] = {
        "gainers": gainers,
        "losers": losers,
        "universe_size": len(universe),
        "fetched": len(results),
        "as_of": _now_iso(),
        "source": "yfinance",
        "note": (
            "Based on yfinance closing prices for a BIST100 universe. "
            "During market hours prices may lag 15 min."
        ),
    }
    if errors:
        out["fetch_errors"] = errors[:5]
    cache_set(cache_key, out)
    return out


# ---------------------------------------------------------------------------
# US large-cap movers — yfinance scan of a curated S&P leaders universe
# ---------------------------------------------------------------------------


_US_LARGECAP_UNIVERSE = [
    # Mega-cap tech
    "AAPL", "MSFT", "NVDA", "GOOGL", "GOOG", "AMZN", "META", "TSLA", "AVGO", "ORCL",
    "ADBE", "CRM", "AMD", "INTC", "QCOM", "TXN", "CSCO", "IBM", "NOW", "INTU",
    # Communication & media
    "NFLX", "DIS", "CMCSA", "T", "VZ", "TMUS",
    # Financials
    "JPM", "BAC", "WFC", "GS", "MS", "C", "BLK", "AXP", "V", "MA", "PYPL",
    # Healthcare
    "UNH", "JNJ", "LLY", "PFE", "MRK", "ABBV", "TMO", "ABT", "DHR", "BMY", "AMGN",
    # Consumer discretionary / staples
    "WMT", "COST", "HD", "LOW", "MCD", "SBUX", "NKE", "TGT", "PG", "KO", "PEP", "PM",
    # Energy
    "XOM", "CVX", "COP", "SLB", "OXY",
    # Industrials & defense
    "BA", "CAT", "GE", "HON", "LMT", "RTX", "DE", "UNP", "UPS", "FDX",
    # Semis & growth darlings
    "ASML", "TSM", "ARM", "MU", "PLTR", "SMCI", "COIN", "UBER", "ABNB", "SHOP",
    # ETFs (broad market + sector leaders) — useful as a movers reference too
    "SPY", "QQQ", "DIA", "IWM", "VOO", "VTI",
]


@tool
def get_us_movers(top_n: int = 10) -> dict[str, Any]:
    """Find today's top gainers and losers among US large-cap stocks.

    Scans a curated ~100-name universe of S&P leaders + popular tickers via
    yfinance and ranks by intraday % change. Use THIS tool when the user
    asks about US/American "top gainers", "top losers", "biggest movers",
    "what's up today on the US market", etc. Do NOT use scan_hot_trends
    for stock movers — that tool only returns crypto trending.

    Args:
        top_n: How many gainers and losers to return (default 10, max 20).
    """
    import concurrent.futures  # noqa: PLC0415

    top_n = min(int(top_n), 20)
    cache_key = f"us_movers:{top_n}"
    cached = cache_get(cache_key)
    if isinstance(cached, dict):
        return cached

    results: list[dict[str, Any]] = []
    errors: list[str] = []

    def _fetch_one(sym: str) -> dict[str, Any] | None:
        try:
            q = yf_svc.quote(sym)
            price = q.get("price")
            prev = q.get("previous_close")
            if price is None or not prev:
                return None
            chg = (price - prev) / prev * 100.0
            return {
                "ticker": sym,
                "price": round(float(price), 2),
                "previous_close": round(float(prev), 2),
                "change_pct": round(chg, 2),
                "currency": q.get("currency", "USD"),
                "source": "yfinance",
            }
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{sym}: {exc}")
            return None

    universe = list(dict.fromkeys(_US_LARGECAP_UNIVERSE))

    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        futures = {pool.submit(_fetch_one, sym): sym for sym in universe}
        for fut in concurrent.futures.as_completed(futures):
            row = fut.result()
            if row:
                results.append(row)

    results.sort(key=lambda x: x["change_pct"], reverse=True)
    gainers = results[:top_n]
    losers = list(reversed(results))[:top_n]

    out: dict[str, Any] = {
        "gainers": gainers,
        "losers": losers,
        "universe_size": len(universe),
        "fetched": len(results),
        "as_of": _now_iso(),
        "source": "yfinance",
        "note": (
            "Ranked from a curated US large-cap universe (S&P leaders + "
            "popular ETFs), not the full market. yfinance prices may lag "
            "~15 min during market hours."
        ),
    }
    if errors:
        out["fetch_errors"] = errors[:5]
    cache_set(cache_key, out)
    return out


# ---------------------------------------------------------------------------
# Hot trends — CoinGecko (CRYPTO ONLY)
# ---------------------------------------------------------------------------


@tool
def scan_hot_trends(no_social: bool = False) -> dict[str, Any]:
    """CRYPTO ONLY — trending coins and global crypto stats from CoinGecko.

    Returns:
      • crypto_trending  — top trending coins from CoinGecko
      • crypto_global    — total market cap, BTC dominance, 24h change

    DO NOT call this for US or Turkish stock movers — it returns ONLY
    cryptocurrencies. For US stock gainers/losers use ``get_us_movers``;
    for BIST stock movers use ``get_bist_movers``.

    ``no_social`` is retained for backward compatibility but ignored.
    """
    cache_key = "hot"
    cached = cache_get(cache_key)
    if isinstance(cached, dict):
        return cached

    out: dict[str, Any] = {"as_of": _now_iso(), "source": "coingecko"}

    try:
        out["crypto_trending"] = cg.trending_coins()
    except CoinGeckoError as exc:
        log.warning("scan_hot_trends: CoinGecko trending failed: %s", exc)
        out["crypto_trending"] = []
        out["cg_trending_error"] = str(exc)

    try:
        out["crypto_global"] = cg.global_market()
    except CoinGeckoError as exc:
        log.info("scan_hot_trends: CoinGecko global market failed: %s", exc)

    cache_set(cache_key, out)
    return out


# ---------------------------------------------------------------------------
# Rumors / M&A chatter — not available (was AV NEWS_SENTIMENT only)
# ---------------------------------------------------------------------------


@tool
def scan_rumors() -> dict[str, Any]:
    """Recent M&A chatter and analyst-actionable headlines.

    Note: this feature was previously backed by Alpha Vantage NEWS_SENTIMENT
    which has been removed due to rate limits. Use the news_sentiment agent
    for current news analysis instead.
    """
    return {
        "rumors": [],
        "as_of": _now_iso(),
        "note": (
            "M&A rumor scanning is unavailable. "
            "Ask the news/sentiment agent for current headlines instead."
        ),
    }


# ---------------------------------------------------------------------------
# Coercers shared by other modules
# ---------------------------------------------------------------------------


def _safe_float(v: Any) -> float | None:
    try:
        return float(v) if v not in (None, "", "None") else None
    except (TypeError, ValueError):
        return None


def _safe_int(v: Any) -> int | None:
    f = _safe_float(v)
    return int(f) if f is not None else None


def _safe_change(v: Any) -> float | None:
    if v is None:
        return None
    s = str(v).strip().rstrip("%")
    try:
        return float(s)
    except ValueError:
        return None
