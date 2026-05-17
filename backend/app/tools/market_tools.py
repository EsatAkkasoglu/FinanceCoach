"""Market data tools — prices, fundamentals, technicals, 8-dim analysis.

Data sources and fallback strategy
───────────────────────────────────
  Crypto quotes   : Alpha Vantage DIGITAL_CURRENCY_DAILY → CoinGecko (fallback)
  Stock quotes    : Alpha Vantage GLOBAL_QUOTE (only source)
  Trending (US)   : Alpha Vantage TOP_GAINERS_LOSERS (only source)
  Trending (crypto): CoinGecko search/trending (primary, always available)
  Global market   : CoinGecko /global (primary, always available)
  Fundamentals    : Alpha Vantage OVERVIEW (only source for US equities)
  Technicals      : Alpha Vantage SMA / RSI (only source)

When AV fails (rate-limit / quota) and a CoinGecko equivalent exists, the
tool transparently switches and tags the result with ``source: "coingecko"``.
When CoinGecko fails and AV is the primary, the error is propagated normally.
"""
from __future__ import annotations

import logging
import statistics
from datetime import datetime
from typing import Any

from langchain_core.tools import tool

import app.services.coingecko as cg
import app.services.yfinance_service as yf_svc
from app.services import alpha_vantage as av
from app.services.alpha_vantage import AlphaVantageError, classify_ticker
from app.services.coingecko import CoinGeckoError
from app.services.yfinance_service import YFinanceError
from app.tools._cache import cache_get, cache_set

log = logging.getLogger("fincoach.tools.market")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _change_pct(price: float | None, prev: float | None) -> float:
    if price is None or prev is None or not prev:
        return 0.0
    return (price - prev) / prev * 100.0


def _is_av_rate_limited(exc: AlphaVantageError) -> bool:
    """Return True when AV is rejecting the request due to quota/rate limits.
    These messages should never be shown to the user — fall back silently.
    """
    msg = str(exc).lower()
    return "rate limit" in msg or "av info:" in msg or "25 requests per day" in msg or "information" in msg


# ---------------------------------------------------------------------------
# Internal quote builders (one per asset class)
# ---------------------------------------------------------------------------


def _quote_stock(symbol: str) -> dict[str, Any]:
    """AV GLOBAL_QUOTE → yfinance → İş Yatırım (.IS only) fallback chain."""
    # Skip AV entirely for non-US tickers (e.g. .IS suffix) — AV has no
    # coverage there and the call wastes our daily quota.
    if "." not in symbol:
        try:
            q = av.global_quote(symbol)
            return {
                "price": q["price"],
                "previous_close": q["previous_close"],
                "currency": "USD",
                "via": "global_quote",
                "volume": q.get("volume"),
                "as_of_date": q.get("latest_trading_day"),
                "source": "alpha_vantage",
            }
        except AlphaVantageError:
            pass  # Any failure → try yfinance.

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
        # Last resort for BIST tickers — İş Yatırım public endpoint.
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
    """AV TIME_SERIES_DAILY → yfinance fallback on rate limit."""
    try:
        bars = av.time_series_daily(symbol)
        if len(bars) < 1:
            raise AlphaVantageError(f"no daily bars for index {symbol}")
        latest = bars[0]
        prev = bars[1]["close"] if len(bars) > 1 else latest["close"]
        return {
            "price": latest["close"],
            "previous_close": prev,
            "currency": "USD",
            "via": "time_series_daily",
            "as_of_date": latest["date"],
            "source": "alpha_vantage",
        }
    except AlphaVantageError as exc:
        if not _is_av_rate_limited(exc):
            raise
        log.debug("AV rate-limited for index %s — falling back to yfinance", symbol)

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
    """AV TREASURY_YIELD only — yfinance uses ^TNX etc. via _quote_index."""
    bars = av.treasury_yield(maturity)
    if not bars:
        raise AlphaVantageError(f"no treasury data for {maturity}")
    latest = bars[0]
    prev = bars[1]["value"] if len(bars) > 1 else latest["value"]
    return {
        "price": latest["value"],
        "previous_close": prev,
        "currency": "PCT",
        "via": "treasury_yield",
        "as_of_date": latest["date"],
        "source": "alpha_vantage",
    }


def _quote_forex(from_ccy: str, to_ccy: str) -> dict[str, Any]:
    """AV CURRENCY_EXCHANGE_RATE → yfinance fallback on rate limit."""
    try:
        spot = av.currency_exchange_rate(from_ccy, to_ccy)
        price = spot["rate"]
        try:
            bars = av.fx_daily(from_ccy, to_ccy)
            prev = bars[1]["close"] if len(bars) > 1 else price
        except AlphaVantageError:
            prev = price
        return {
            "price": price,
            "previous_close": prev,
            "currency": to_ccy,
            "via": "currency_exchange_rate",
            "as_of": spot.get("last_refreshed"),
            "source": "alpha_vantage",
        }
    except AlphaVantageError as exc:
        if not _is_av_rate_limited(exc):
            raise
        log.debug("AV rate-limited for forex %s/%s — falling back to yfinance", from_ccy, to_ccy)

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
    """Crypto quote: AV DIGITAL_CURRENCY_DAILY, falling back to CoinGecko."""
    # --- Alpha Vantage (primary) ---
    try:
        bars = av.digital_currency_daily(base, quote)
        if bars:
            latest = bars[0]
            prev = bars[1]["close"] if len(bars) > 1 else latest["close"]
            return {
                "price": latest["close"],
                "previous_close": prev,
                "currency": quote,
                "via": "digital_currency_daily",
                "as_of_date": latest["date"],
                "source": "alpha_vantage",
            }
    except AlphaVantageError as exc:
        log.info("AV crypto failed for %s/%s, trying CoinGecko: %s", base, quote, exc)

    # AV spot-rate fallback (cheaper endpoint, no history)
    try:
        spot = av.currency_exchange_rate(base, quote)
        return {
            "price": spot["rate"],
            "previous_close": spot["rate"],
            "currency": quote,
            "via": "currency_exchange_rate",
            "as_of": spot.get("last_refreshed"),
            "source": "alpha_vantage",
        }
    except AlphaVantageError as exc:
        log.info("AV spot rate also failed for %s/%s, falling back to CoinGecko: %s", base, quote, exc)

    # --- CoinGecko (fallback) ---
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
        raise AlphaVantageError(
            f"Both AV and CoinGecko failed for {base}/{quote}: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Public tools
# ---------------------------------------------------------------------------


@tool
def get_quote(ticker: str) -> dict[str, Any]:
    """Get the latest price and 1-day change for ANY supported ticker.

    Supported:
        AAPL, NVDA           — US stocks (AV GLOBAL_QUOTE)
        BTC-USD, ETH-USD     — crypto (AV DIGITAL_CURRENCY_DAILY → CoinGecko fallback)
        SPY, QQQ, VTI, GLD   — ETFs (AV GLOBAL_QUOTE)
        ^GSPC, ^IXIC, ^VIX   — indices (AV TIME_SERIES_DAILY)
        EURUSD=X, USDTRY=X   — forex (AV CURRENCY_EXCHANGE_RATE + FX_DAILY)
        ^TNX, ^TYX           — Treasury yields (AV TREASURY_YIELD)
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
            "source": result.get("source", "alpha_vantage"),
            "via": result.get("via"),
        }
        if cls.get("proxy"):
            quote_result["proxy_for"] = cls["input"]
        cache_set(cache_key, quote_result)
        return quote_result
    except AlphaVantageError as exc:
        log.warning("get_quote failure for %s: %s", upper, exc)
        return {"ticker": upper, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        log.warning("get_quote unexpected error for %s: %s", upper, exc)
        return {"ticker": upper, "error": str(exc)}


@tool
def get_company_overview(ticker: str) -> dict[str, Any]:
    """Fundamentals + analyst block for a US-listed equity (or ETF).
    Backed by Alpha Vantage OVERVIEW. Returns valuation, profitability,
    growth, dividend and analyst-rating fields in one call.

    Use whenever the user asks "what does company X do", "is X a good buy",
    "P/E of X", "is X overvalued", or for any fundamental comparison.

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
        raw = av.overview(upper)
    except AlphaVantageError as exc:
        if _is_av_rate_limited(exc):
            log.debug("AV rate-limited for overview %s — falling back to yfinance", upper)
            try:
                return yf_svc.overview(upper)
            except YFinanceError as yf_exc:
                log.warning("yfinance overview also failed for %s: %s", upper, yf_exc)
                return {"ticker": upper, "error": "Market data temporarily unavailable. Try again shortly."}
        return {"ticker": upper, "error": f"alpha vantage: {exc}"}

    def _f(key: str) -> float | None:
        v = raw.get(key)
        try:
            return float(v) if v not in (None, "", "None", "-") else None
        except (TypeError, ValueError):
            return None

    def _i(key: str) -> int | None:
        v = _f(key)
        return int(v) if v is not None else None

    result = {
        "ticker": upper,
        "name": raw.get("Name"),
        "sector": raw.get("Sector"),
        "industry": raw.get("Industry"),
        "exchange": raw.get("Exchange"),
        "currency": raw.get("Currency"),
        "country": raw.get("Country"),
        "description": (raw.get("Description") or "")[:600],
        "market_cap": _i("MarketCapitalization"),
        "pe_ratio": _f("PERatio"),
        "forward_pe": _f("ForwardPE"),
        "peg_ratio": _f("PEGRatio"),
        "price_to_book": _f("PriceToBookRatio"),
        "price_to_sales": _f("PriceToSalesRatioTTM"),
        "eps": _f("EPS"),
        "profit_margin": _f("ProfitMargin"),
        "operating_margin": _f("OperatingMarginTTM"),
        "roe": _f("ReturnOnEquityTTM"),
        "roa": _f("ReturnOnAssetsTTM"),
        "revenue_ttm": _f("RevenueTTM"),
        "ebitda": _f("EBITDA"),
        "beta": _f("Beta"),
        "week_52_high": _f("52WeekHigh"),
        "week_52_low": _f("52WeekLow"),
        "sma_50d": _f("50DayMovingAverage"),
        "sma_200d": _f("200DayMovingAverage"),
        "dividend_yield": _f("DividendYield"),
        "dividend_per_share": _f("DividendPerShare"),
        "ex_dividend_date": raw.get("ExDividendDate"),
        "next_dividend_date": raw.get("DividendDate"),
        "analyst_target_price": _f("AnalystTargetPrice"),
        "analyst_strong_buy": _i("AnalystRatingStrongBuy"),
        "analyst_buy": _i("AnalystRatingBuy"),
        "analyst_hold": _i("AnalystRatingHold"),
        "analyst_sell": _i("AnalystRatingSell"),
        "analyst_strong_sell": _i("AnalystRatingStrongSell"),
        "source": "alpha_vantage",
    }
    cache_set(cache_key, result)
    return result


@tool
def get_technical_indicators(
    ticker: str,
    sma_period: int = 50,
    rsi_period: int = 14,
) -> dict[str, Any]:
    """Latest SMA and RSI for a US ticker (Alpha Vantage SMA + RSI endpoints).

    Use when the agent needs momentum / trend context: "is X overbought?",
    "is X above its 50-day SMA?", "is the momentum positive?". Reports the
    current SMA value, RSI value, an interpretation (overbought / oversold /
    neutral) and the SMA-cross signal vs the current quote.

    Args:
        ticker: e.g. "AAPL", "NVDA". US equities/ETFs only.
        sma_period: lookback window for the simple moving average (default 50).
        rsi_period: lookback window for the Relative Strength Index (default 14).
    """
    upper = (ticker or "").strip().upper()
    try:
        sma_rows = av.sma(upper, time_period=sma_period)
        rsi_rows = av.rsi(upper, time_period=rsi_period)
    except AlphaVantageError as exc:
        if not _is_av_rate_limited(exc):
            return {"ticker": upper, "error": f"alpha vantage: {exc}"}
        log.debug("AV rate-limited for technicals %s — falling back to yfinance", upper)
        try:
            sma_rows = yf_svc.sma(upper, period=sma_period)
            rsi_rows = yf_svc.rsi(upper, period=rsi_period)
        except YFinanceError as yf_exc:
            log.warning("yfinance technicals failed for %s: %s", upper, yf_exc)
            return {"ticker": upper, "error": "Technical indicators temporarily unavailable."}

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
        "source": "alpha_vantage",
    }


# ---------------------------------------------------------------------------
# 8-dimension analysis (AV-backed, US equities only)
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
        payload = av.earnings(symbol)
        quarters = (payload.get("quarterlyEarnings") or [])[:4]
        surprises: list[float] = []
        for q in quarters:
            try:
                surprises.append(float(q.get("surprisePercentage")))
            except (TypeError, ValueError):
                continue
        return _surprises_to_score(surprises, source="alpha_vantage")
    except AlphaVantageError:
        pass
    try:
        rows = yf_svc.earnings_surprises(symbol, limit=4)
        surprises = [r["surprise_pct"] for r in rows]
        return _surprises_to_score(surprises, source="yfinance")
    except YFinanceError as exc:
        return 0.5, {"error": f"yfinance fallback failed: {exc}", "unavailable": True}


def _fundamentals_from_overview(ov: dict[str, Any], *, source: str) -> tuple[float, dict[str, Any]]:
    """Shared scoring logic for AV-shape and yfinance-shape overview dicts."""
    if source == "alpha_vantage":
        pe_key, pm_key, roe_key, sector_key = "PERatio", "ProfitMargin", "ReturnOnEquityTTM", "Sector"
    else:
        pe_key, pm_key, roe_key, sector_key = "pe_ratio", "profit_margin", "roe", "sector"

    def f(k: str) -> float | None:
        v = ov.get(k)
        try:
            return float(v) if v not in (None, "", "None", "-") else None
        except (TypeError, ValueError):
            return None

    pe, profit_margin, roe = f(pe_key), f(pm_key), f(roe_key)
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
    detail["sector"] = ov.get(sector_key)
    detail["source"] = source
    return score, detail


def _score_fundamentals(symbol: str) -> tuple[float, dict[str, Any]]:
    try:
        return _fundamentals_from_overview(av.overview(symbol), source="alpha_vantage")
    except AlphaVantageError:
        pass  # Any AV failure (rate-limit, invalid symbol, non-US) → try yfinance.
    try:
        return _fundamentals_from_overview(yf_svc.overview(symbol), source="yfinance")
    except YFinanceError as exc:
        return 0.5, {"error": f"yfinance fallback failed: {exc}", "unavailable": True}


def _analyst_from_overview(ov: dict[str, Any], *, source: str) -> tuple[float, dict[str, Any]]:
    if source == "alpha_vantage":
        keys = ("AnalystRatingStrongBuy", "AnalystRatingBuy", "AnalystRatingHold",
                "AnalystRatingSell", "AnalystRatingStrongSell")
        target = ov.get("AnalystTargetPrice")
    else:
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
        return 0.5, {"coverage": "none", "source": source}
    weighted = sb * 1.0 + b * 0.75 + h * 0.5 + s * 0.25 + ss * 0.0
    return weighted / total, {
        "strong_buy": sb, "buy": b, "hold": h, "sell": s, "strong_sell": ss,
        "total_analysts": total, "target_price": target, "source": source,
    }


def _score_analyst_sentiment(symbol: str) -> tuple[float, dict[str, Any]]:
    try:
        return _analyst_from_overview(av.overview(symbol), source="alpha_vantage")
    except AlphaVantageError:
        pass
    try:
        return _analyst_from_overview(yf_svc.overview(symbol), source="yfinance")
    except YFinanceError as exc:
        return 0.5, {"error": f"yfinance fallback failed: {exc}", "unavailable": True}


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
        score, detail = _historical_from_bars(av.time_series_daily(symbol, outputsize="full"))
        detail["source"] = "alpha_vantage"
        return score, detail
    except AlphaVantageError:
        pass
    try:
        bars = yf_svc.history(symbol, period="1y")
        score, detail = _historical_from_bars(bars)
        detail["source"] = "yfinance"
        return score, detail
    except YFinanceError as exc:
        return 0.5, {"error": f"yfinance fallback failed: {exc}", "unavailable": True}


def _score_market_context() -> tuple[float, dict[str, Any]]:
    vix: float | None = None
    source = "alpha_vantage"
    try:
        bars = av.time_series_daily("VIX")
        vix = bars[0]["close"] if bars else None
    except AlphaVantageError as exc:
        if not _is_av_rate_limited(exc):
            return 0.5, {"error": str(exc), "unavailable": True}
        try:
            q = yf_svc.quote("^VIX")
            vix = q.get("price")
            source = "yfinance"
        except YFinanceError as yf_exc:
            return 0.5, {"vix": None, "error": str(yf_exc), "unavailable": True}
    if vix is None:
        return 0.5, {"vix": None, "unavailable": True}
    score = max(0.0, min(1.0, (35 - vix) / 23.0))
    regime = "calm" if vix < 20 else "elevated" if vix < 30 else "stressed"
    return score, {"vix": round(vix, 2), "regime": regime, "source": source}


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
    change: float | None = None
    source = "alpha_vantage"
    try:
        q = av.global_quote(etf)
        change = q.get("change_percent")
    except AlphaVantageError:
        try:
            yq = yf_svc.quote(etf)
            price, prev = yq.get("price"), yq.get("previous_close")
            if price is not None and prev:
                change = (price - prev) / prev * 100.0
                source = "yfinance"
        except YFinanceError as yf_exc:
            return 0.5, {"sector": sector, "etf": etf, "error": str(yf_exc), "unavailable": True}
    if change is None:
        return 0.5, {"sector": sector, "etf": etf, "unavailable": True}
    score = max(0.0, min(1.0, 0.5 + change / 6.0))
    return score, {"sector": sector, "etf": etf, "day_change_pct": round(change, 2), "source": source}


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
        rsi_rows = av.rsi(symbol, time_period=14)
        sma_rows = av.sma(symbol, time_period=50)
        rsi_v = rsi_rows[0]["rsi"] if rsi_rows else None
        sma_v = sma_rows[0]["sma"] if sma_rows else None
        try:
            price = av.global_quote(symbol).get("price")
        except AlphaVantageError:
            price = None
        return _momentum_from_values(rsi_v, sma_v, price, source="alpha_vantage")
    except AlphaVantageError:
        pass
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
        return 0.5, {"error": f"yfinance fallback failed: {exc}", "unavailable": True}


def _score_sentiment(symbol: str) -> tuple[float, dict[str, Any]]:
    """AV-only — no yfinance equivalent. Skip on rate-limit."""
    try:
        payload = av.news_sentiment(tickers=symbol, limit=20, sort="LATEST")
    except AlphaVantageError as exc:
        if _is_av_rate_limited(exc):
            return 0.5, {"error": "unavailable (AV rate-limited; no fallback)", "unavailable": True}
        return 0.5, {"error": str(exc), "unavailable": True}
    feed = payload.get("feed") or []
    if not feed:
        return 0.5, {"articles": 0}
    scores: list[float] = []
    for item in feed:
        for ts in item.get("ticker_sentiment") or []:
            if (ts.get("ticker") or "").upper() == symbol.upper():
                try:
                    scores.append(float(ts.get("ticker_sentiment_score")))
                except (TypeError, ValueError):
                    pass
                break
    if not scores:
        return 0.5, {"articles": len(feed)}
    avg = sum(scores) / len(scores)
    score = max(0.0, min(1.0, 0.5 + avg))
    label = "bullish" if avg > 0.15 else "bearish" if avg < -0.15 else "neutral"
    return score, {
        "articles": len(feed),
        "scored_articles": len(scores),
        "avg_sentiment": round(avg, 3),
        "label": label,
    }


def _recommendation(final_score: float) -> str:
    if final_score >= 0.70:
        return "BUY"
    if final_score <= 0.40:
        return "SELL"
    return "HOLD"


@tool
def analyze_ticker_8dim(ticker: str, fast: bool = False) -> dict[str, Any]:
    """Run the 8-dimension analysis on a US stock or ETF using Alpha Vantage.

    Dimensions: earnings_surprise, fundamentals, analyst_sentiment, historical,
    market_context, sector, momentum, sentiment. Each scored 0–1, then a
    weighted score (0–1) yields a BUY (>=0.70) / HOLD / SELL (<=0.40)
    recommendation.

    Args:
        ticker: e.g. "NVDA", "AAPL". US equities/ETFs only — crypto and
            indices return an explanatory error since AV fundamentals don't
            cover them.
        fast: skip the news-sentiment dimension (saves 1 API call, ~3-5s).
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
                "8-dim analysis is only available for US equities/ETFs "
                "(Alpha Vantage fundamentals don't cover crypto/indices/forex)."
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

    if fast:
        dims["sentiment"] = {"score": 0.5, "skipped": True}
    else:
        s, d = _score_sentiment(symbol)
        dims["sentiment"] = {"score": s, **d}

    # Renormalize weights to only include dimensions that actually returned
    # data. Skipped (fast=True) dims are NOT treated as unavailable — they
    # contribute their neutral 0.5 by design.
    unavailable = [k for k, v in dims.items() if v.get("unavailable")]
    usable_keys = [k for k in _RISK_WEIGHTS if k not in unavailable]
    total_weight = sum(_RISK_WEIGHTS[k] for k in usable_keys)
    if total_weight > 0:
        final = sum(_RISK_WEIGHTS[k] * dims[k]["score"] for k in usable_keys) / total_weight
    else:
        final = 0.5

    # If most dimensions are unavailable, the recommendation is not
    # meaningful — surface that honestly instead of returning a fake 0.5/HOLD.
    degraded = len(unavailable) >= 4
    result: dict[str, Any] = {
        "ticker": upper,
        "final_score": round(final, 3) if not degraded else None,
        "recommendation": _recommendation(final) if not degraded else None,
        "dimensions": {k: {**v, "score": round(v["score"], 3)} for k, v in dims.items()},
        "weights": _RISK_WEIGHTS,
        "unavailable_dimensions": unavailable,
        "source": "alpha_vantage+yfinance",
        "as_of": _now_iso(),
    }
    if degraded:
        result["degraded"] = True
        result["error"] = (
            f"Analysis degraded: {len(unavailable)}/8 dimensions unavailable "
            f"({', '.join(unavailable)}) — Alpha Vantage daily quota likely "
            "exhausted and no fallback exists for these dimensions. Final "
            "score and recommendation withheld to avoid a misleading result."
        )
    cache_set(cache_key, result)
    return result


# ---------------------------------------------------------------------------
# Dividend metrics
# ---------------------------------------------------------------------------


@tool
def get_dividend_metrics(ticker: str) -> dict[str, Any] | None:
    """Yield, payout ratio, growth (5Y CAGR), consecutive years of increases,
    safety score (0-100), income rating (excellent/good/moderate/poor).

    Backed by Alpha Vantage OVERVIEW + DIVIDENDS endpoints. US equities/ETFs.
    """
    cache_key = f"div:{(ticker or '').strip().upper()}"
    cached = cache_get(cache_key)
    if isinstance(cached, dict):
        return cached

    upper = (ticker or "").strip().upper()
    try:
        ov = av.overview(upper)
        history = av.dividends(upper)
    except AlphaVantageError as exc:
        return {"ticker": upper, "error": f"alpha vantage: {exc}"}

    def _f(v: Any) -> float | None:
        try:
            return float(v) if v not in (None, "", "None", "-") else None
        except (TypeError, ValueError):
            return None

    yield_ = _f(ov.get("DividendYield"))
    dps = _f(ov.get("DividendPerShare"))
    eps = _f(ov.get("EPS"))
    payout_ratio = (dps / eps) if (dps is not None and eps and eps > 0) else None

    by_year: dict[int, float] = {}
    for d in history:
        date = d.get("ex_dividend_date") or d.get("payment_date")
        amt = d.get("amount")
        if not date or amt is None:
            continue
        try:
            year = int(date[:4])
        except (TypeError, ValueError):
            continue
        by_year[year] = by_year.get(year, 0.0) + float(amt)

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

    result = {
        "ticker": upper,
        "yield": yield_,
        "dividend_per_share": dps,
        "payout_ratio": round(payout_ratio, 3) if payout_ratio is not None else None,
        "growth_5y_cagr": round(growth_5y_cagr, 4) if growth_5y_cagr is not None else None,
        "consecutive_increase_years": streak,
        "ex_dividend_date": ov.get("ExDividendDate"),
        "next_dividend_date": ov.get("DividendDate"),
        "safety_score": round(safety, 1),
        "income_rating": rating,
        "source": "alpha_vantage",
    }
    cache_set(cache_key, result)
    return result


# ---------------------------------------------------------------------------
# Hot trends  — AV (US stocks) + CoinGecko (crypto), mutual fallback
# ---------------------------------------------------------------------------


@tool
def scan_hot_trends(no_social: bool = False) -> dict[str, Any]:
    """Find trending tickers across markets.

    Returns:
      • top_gainers / top_losers / most_active  — US stocks from AV
        (falls back gracefully if AV rate-limits; error recorded in av_error)
      • crypto_trending  — top-7 trending coins from CoinGecko (always
        attempted; falls back to empty list with cg_error on failure)
      • crypto_global    — total market cap, BTC dominance, 24h change
        from CoinGecko (best-effort)

    ``no_social`` is retained for backward compatibility but ignored —
    CoinGecko trending is always included as market data, not social media.
    """
    cache_key = "hot"
    cached = cache_get(cache_key)
    if isinstance(cached, dict):
        return cached

    out: dict[str, Any] = {"as_of": _now_iso(), "source": "alpha_vantage+coingecko"}

    # --- Alpha Vantage: US stock movers ---
    try:
        payload = av.top_gainers_losers()
        out["top_gainers"] = [
            {
                "ticker": x.get("ticker"),
                "price": _safe_float(x.get("price")),
                "change_pct": _safe_change(x.get("change_percentage")),
                "volume": _safe_int(x.get("volume")),
            }
            for x in (payload.get("top_gainers") or [])[:10]
        ]
        out["top_losers"] = [
            {
                "ticker": x.get("ticker"),
                "price": _safe_float(x.get("price")),
                "change_pct": _safe_change(x.get("change_percentage")),
                "volume": _safe_int(x.get("volume")),
            }
            for x in (payload.get("top_losers") or [])[:10]
        ]
        out["most_active"] = [
            {
                "ticker": x.get("ticker"),
                "price": _safe_float(x.get("price")),
                "change_pct": _safe_change(x.get("change_percentage")),
                "volume": _safe_int(x.get("volume")),
            }
            for x in (payload.get("most_actively_traded") or [])[:10]
        ]
    except AlphaVantageError as exc:
        log.warning("scan_hot_trends: AV TOP_GAINERS_LOSERS failed: %s", exc)
        out["av_error"] = str(exc)

    # --- CoinGecko: crypto trending (primary for crypto, no AV equivalent) ---
    try:
        out["crypto_trending"] = cg.trending_coins()
    except CoinGeckoError as exc:
        log.warning("scan_hot_trends: CoinGecko trending failed: %s", exc)
        out["crypto_trending"] = []
        out["cg_trending_error"] = str(exc)

    # --- CoinGecko: global crypto market snapshot ---
    try:
        out["crypto_global"] = cg.global_market()
    except CoinGeckoError as exc:
        log.info("scan_hot_trends: CoinGecko global market failed: %s", exc)

    cache_set(cache_key, out)
    return out


# ---------------------------------------------------------------------------
# Rumors / M&A / analyst chatter  — AV NEWS_SENTIMENT
# ---------------------------------------------------------------------------


@tool
def scan_rumors() -> dict[str, Any]:
    """Recent M&A chatter, analyst-actionable news and breaking headlines
    scored by potential market impact. Backed by Alpha Vantage
    NEWS_SENTIMENT (``topics=mergers_and_acquisitions`` and
    ``topics=financial_markets``).

    Returns up to ~10 rumors. Each item: {title, ticker, source,
    sentiment, sentiment_label, relevance, impact_score (1-10), url,
    published_at}.

    NOTE: Alpha Vantage does NOT provide insider-transaction data. If the
    user explicitly asks for "insider trades", say it's not available in
    this prototype.
    """
    cache_key = "rumors"
    cached = cache_get(cache_key)
    if isinstance(cached, dict):
        return cached

    rumors: list[dict[str, Any]] = []
    try:
        ma = av.news_sentiment(topics="mergers_and_acquisitions", limit=20, sort="LATEST")
        rumors.extend(_format_rumors(ma.get("feed") or [], category="m&a"))
    except AlphaVantageError as exc:
        log.warning("M&A news fetch failed: %s", exc)

    try:
        fm = av.news_sentiment(topics="financial_markets", limit=10, sort="LATEST")
        rumors.extend(_format_rumors(fm.get("feed") or [], category="market"))
    except AlphaVantageError as exc:
        log.warning("financial_markets news fetch failed: %s", exc)

    seen: set[str] = set()
    ranked: list[dict[str, Any]] = []
    for r in sorted(rumors, key=lambda x: x.get("impact_score", 0), reverse=True):
        url = r.get("url") or r.get("title") or ""
        if url in seen:
            continue
        seen.add(url)
        ranked.append(r)
        if len(ranked) >= 10:
            break

    result = {
        "rumors": ranked,
        "as_of": _now_iso(),
        "source": "alpha_vantage_news_sentiment",
    }
    cache_set(cache_key, result)
    return result


def _format_rumors(feed: list[dict[str, Any]], category: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in feed:
        try:
            sentiment = float(item.get("overall_sentiment_score") or 0.0)
        except (TypeError, ValueError):
            sentiment = 0.0
        top_rel = 0.0
        top_ticker = None
        for ts in item.get("ticker_sentiment") or []:
            try:
                rel = float(ts.get("relevance_score") or 0)
            except (TypeError, ValueError):
                rel = 0.0
            if rel > top_rel:
                top_rel = rel
                top_ticker = ts.get("ticker")
        impact = round(max(1.0, min(10.0, abs(sentiment) * 8 + top_rel * 4)), 1)
        out.append({
            "title": item.get("title"),
            "ticker": top_ticker,
            "source": item.get("source"),
            "category": category,
            "sentiment": round(sentiment, 3),
            "sentiment_label": item.get("overall_sentiment_label"),
            "relevance": round(top_rel, 3),
            "impact_score": impact,
            "url": item.get("url"),
            "published_at": item.get("time_published"),
        })
    return out


# ---------------------------------------------------------------------------
# Coercers shared by scan_hot_trends / scan_rumors
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
