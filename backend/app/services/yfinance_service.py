"""yfinance wrapper — unlimited free fallback for market data.

Used when Alpha Vantage hits its daily rate limit (25 req/day on free tier).
yfinance has no API key, no rate limit, and covers:
  • US stocks, ETFs, ADRs
  • Crypto  (-USD tickers: BTC-USD, ETH-USD …)
  • Forex   (EURUSD=X, USDTRY=X …)
  • Indices (^GSPC, ^IXIC, ^VIX …)
  • Treasury yields (^TNX, ^TYX …)

Not a full replacement — AV OVERVIEW fundamentals, earnings history, and
dividend history are richer. yfinance covers the gap for live prices,
basic fundamentals, and technical indicators.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Any

log = logging.getLogger("fincoach.yfinance")

_cache: dict[str, tuple[float, Any]] = {}
_cache_lock = threading.Lock()
_DEFAULT_TTL = 60  # seconds — quotes refresh every minute


class YFinanceError(RuntimeError):
    """Raised when yfinance returns no data or errors out."""


def _cache_get(key: str, ttl: int = _DEFAULT_TTL) -> Any | None:
    with _cache_lock:
        hit = _cache.get(key)
    if not hit:
        return None
    fetched_at, value = hit
    return value if time.time() - fetched_at < ttl else None


def _cache_set(key: str, value: Any) -> None:
    with _cache_lock:
        _cache[key] = (time.time(), value)


def _ticker(symbol: str):  # type: ignore[return]
    """Return a yfinance Ticker, importing lazily to avoid startup cost."""
    import yfinance as yf  # noqa: PLC0415
    return yf.Ticker(symbol)


def _now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def quote(symbol: str) -> dict[str, Any]:
    """Latest price and 1-day change for any yfinance-supported symbol.

    Returns:
        {price, previous_close, currency, volume, as_of, source}
    """
    cache_key = f"yf:quote:{symbol.upper()}"
    cached = _cache_get(cache_key, ttl=60)
    if cached:
        return cached

    try:
        tk = _ticker(symbol)
        info = tk.fast_info
        price = getattr(info, "last_price", None) or getattr(info, "regularMarketPrice", None)
        prev = getattr(info, "previous_close", None) or getattr(info, "regularMarketPreviousClose", None)
        currency = getattr(info, "currency", "USD") or "USD"
        volume = getattr(info, "three_month_average_volume", None)
    except Exception as exc:  # noqa: BLE001
        raise YFinanceError(f"yfinance quote failed for {symbol}: {exc}") from exc

    if price is None:
        raise YFinanceError(f"yfinance returned no price for {symbol}")

    result = {
        "price": round(float(price), 4),
        "previous_close": round(float(prev), 4) if prev else None,
        "currency": str(currency),
        "volume": int(volume) if volume else None,
        "as_of": _now_iso(),
        "source": "yfinance",
    }
    _cache_set(cache_key, result)
    return result


def overview(symbol: str) -> dict[str, Any]:
    """Basic fundamentals from yfinance .info.

    Covers: P/E, market cap, profit margin, beta, 52w range, dividend,
    analyst target, sector, industry. Less complete than AV OVERVIEW but
    works without a key.
    """
    cache_key = f"yf:overview:{symbol.upper()}"
    cached = _cache_get(cache_key, ttl=6 * 3600)
    if cached:
        return cached

    try:
        tk = _ticker(symbol)
        info = tk.info or {}
    except Exception as exc:  # noqa: BLE001
        raise YFinanceError(f"yfinance info failed for {symbol}: {exc}") from exc

    if not info or info.get("trailingPegRatio") is None and not info.get("longName"):
        raise YFinanceError(f"yfinance returned empty info for {symbol}")

    def _f(key: str) -> float | None:
        v = info.get(key)
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    result = {
        "ticker": symbol.upper(),
        "name": info.get("longName") or info.get("shortName"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "exchange": info.get("exchange"),
        "currency": info.get("currency"),
        "country": info.get("country"),
        "description": (info.get("longBusinessSummary") or "")[:600],
        "market_cap": info.get("marketCap"),
        "pe_ratio": _f("trailingPE"),
        "forward_pe": _f("forwardPE"),
        "peg_ratio": _f("trailingPegRatio"),
        "price_to_book": _f("priceToBook"),
        "price_to_sales": _f("priceToSalesTrailing12Months"),
        "eps": _f("trailingEps"),
        "profit_margin": _f("profitMargins"),
        "operating_margin": _f("operatingMargins"),
        "roe": _f("returnOnEquity"),
        "roa": _f("returnOnAssets"),
        "revenue_ttm": _f("totalRevenue"),
        "ebitda": _f("ebitda"),
        "beta": _f("beta"),
        "week_52_high": _f("fiftyTwoWeekHigh"),
        "week_52_low": _f("fiftyTwoWeekLow"),
        "sma_50d": _f("fiftyDayAverage"),
        "sma_200d": _f("twoHundredDayAverage"),
        "dividend_yield": _f("dividendYield"),
        "dividend_per_share": _f("dividendRate"),
        "ex_dividend_date": info.get("exDividendDate"),
        "analyst_target_price": _f("targetMeanPrice"),
        "analyst_strong_buy": info.get("strongBuy"),
        "analyst_buy": info.get("buy"),
        "analyst_hold": info.get("hold"),
        "analyst_sell": info.get("sell"),
        "analyst_strong_sell": info.get("strongSell"),
        "source": "yfinance",
    }
    _cache_set(cache_key, result)
    return result


def history(
    symbol: str,
    period: str = "1y",
    interval: str = "1d",
) -> list[dict[str, Any]]:
    """OHLCV history as a list of dicts, newest first."""
    cache_key = f"yf:hist:{symbol.upper()}:{period}:{interval}"
    cached = _cache_get(cache_key, ttl=6 * 3600)
    if cached:
        return cached

    try:
        import yfinance as yf  # noqa: PLC0415
        df = yf.download(symbol, period=period, interval=interval,
                         auto_adjust=True, progress=False)
    except Exception as exc:  # noqa: BLE001
        raise YFinanceError(f"yfinance history failed for {symbol}: {exc}") from exc

    if df is None or df.empty:
        raise YFinanceError(f"yfinance returned no history for {symbol}")

    rows: list[dict[str, Any]] = []
    for ts, row in df.iloc[::-1].iterrows():
        rows.append({
            "date": str(ts)[:10],
            "open": float(row["Open"]),
            "high": float(row["High"]),
            "low": float(row["Low"]),
            "close": float(row["Close"]),
            "volume": int(row["Volume"]) if row["Volume"] else None,
        })
    _cache_set(cache_key, rows)
    return rows


def sma(symbol: str, period: int = 50) -> list[dict[str, Any]]:
    """Simple moving average calculated from yfinance daily history."""
    bars = history(symbol, period="2y")
    if len(bars) < period:
        raise YFinanceError(f"Not enough bars to compute SMA-{period} for {symbol}")
    closes = [b["close"] for b in bars]  # newest first
    rows: list[dict[str, Any]] = []
    for i in range(len(closes) - period + 1):
        window = closes[i: i + period]
        rows.append({
            "date": bars[i]["date"],
            "sma": round(sum(window) / period, 4),
        })
    return rows


def rsi(symbol: str, period: int = 14) -> list[dict[str, Any]]:
    """RSI calculated from yfinance daily history (Wilder's smoothing)."""
    bars = history(symbol, period="1y")
    closes = [b["close"] for b in reversed(bars)]  # oldest first for calculation
    if len(closes) < period + 1:
        raise YFinanceError(f"Not enough bars to compute RSI-{period} for {symbol}")

    deltas = [closes[i + 1] - closes[i] for i in range(len(closes) - 1)]
    gains = [max(d, 0.0) for d in deltas]
    losses = [abs(min(d, 0.0)) for d in deltas]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    rsi_values: list[tuple[str, float]] = []
    dates = [b["date"] for b in reversed(bars)]  # oldest first

    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        rs = avg_gain / avg_loss if avg_loss else float("inf")
        rsi_val = 100.0 - (100.0 / (1 + rs))
        rsi_values.append((dates[i + 1], round(rsi_val, 2)))

    # Return newest first
    return [{"date": d, "rsi": v} for d, v in reversed(rsi_values)]
