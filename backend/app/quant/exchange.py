"""Intraday OHLCV from public exchange APIs — the data layer for the crypto experiment.

``quant/data.py`` serves the app's existing daily surfaces (yfinance / TEFAS). It
cannot serve this experiment: yfinance's curl backend does not survive the agent
proxy, and neither yfinance nor TEFAS offers 15-minute crypto bars. So this module
talks to exchange candle endpoints directly.

Sources, in fallback order (all keyless, all verified reachable):

    OKX          — primary. Deepest coverage of mid-cap alts, 15m/30m/1H/4H,
                   history endpoint paginates back years.
    Binance.US   — fallback. 1000 bars per request, simple time-range paging.
    Coinbase     — last resort. Only 60/300/900/3600/21600/86400 granularities.

Two correctness rules the rest of the experiment depends on:

1. **The in-progress bar is dropped.** OKX flags it (``confirm == "0"``); Binance
   and Coinbase do not, so the newest bar is dropped whenever its close time has
   not yet passed. Backtesting on a partially-formed bar is look-ahead of the
   worst kind — the bar's close is the future, and it leaks into every indicator.
2. **Bars are returned oldest-first and strictly de-duplicated by timestamp.**
   Paginated fetches overlap at the seams; a duplicated bar silently doubles a
   return and inflates every metric downstream.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any

import numpy as np
import requests

log = logging.getLogger("fincoach.quant.exchange")

#: Crypto trades 24/7/365 — no exchange calendar, no weekend gap.
BARS_PER_YEAR: dict[str, float] = {
    "15m": 365.25 * 24 * 4,
    "30m": 365.25 * 24 * 2,
    "1h": 365.25 * 24,
    "4h": 365.25 * 6,
    "1d": 365.25,
}

_TIMEFRAME_MS: dict[str, int] = {
    "15m": 15 * 60_000,
    "30m": 30 * 60_000,
    "1h": 60 * 60_000,
    "4h": 4 * 60 * 60_000,
    "1d": 24 * 60 * 60_000,
}

_OKX_BAR = {"15m": "15m", "30m": "30m", "1h": "1H", "4h": "4H", "1d": "1D"}
_BINANCE_BAR = {"15m": "15m", "30m": "30m", "1h": "1h", "4h": "4h", "1d": "1d"}
_COINBASE_GRAN = {"15m": 900, "1h": 3600, "1d": 86400}

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; FinCoachQuant/1.0)"}
_TIMEOUT = 25

CACHE_DIR = os.environ.get(
    "FINCOACH_CANDLE_CACHE",
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "candles"),
)


class ExchangeError(RuntimeError):
    """No source could supply usable candles."""


@dataclass
class Candles:
    """Oldest-first OHLCV for one (symbol, timeframe)."""

    symbol: str
    timeframe: str
    source: str
    ts: np.ndarray        # epoch ms, open time of each bar
    opens: np.ndarray
    highs: np.ndarray
    lows: np.ndarray
    closes: np.ndarray
    volumes: np.ndarray

    def __len__(self) -> int:
        return int(self.closes.size)

    @property
    def bars_per_year(self) -> float:
        return BARS_PER_YEAR.get(self.timeframe, 365.25)

    @property
    def dates(self) -> list[str]:
        return [
            time.strftime("%Y-%m-%d %H:%M", time.gmtime(int(t) / 1000)) for t in self.ts
        ]

    def tail(self, n: int) -> Candles:
        return Candles(
            self.symbol, self.timeframe, self.source,
            self.ts[-n:], self.opens[-n:], self.highs[-n:],
            self.lows[-n:], self.closes[-n:], self.volumes[-n:],
        )


# ── raw rows: [ts_ms, o, h, l, c, v] oldest-first, closed bars only ──────────


def _now_ms() -> int:
    return int(time.time() * 1000)


def _get(url: str, params: dict[str, Any]) -> Any:
    r = requests.get(url, params=params, timeout=_TIMEOUT, headers=_HEADERS)
    r.raise_for_status()
    return r.json()


def _okx_rows(symbol: str, timeframe: str, want: int) -> list[list[float]]:
    """OKX paginates backwards via ``after`` (return bars older than this ts)."""
    bar = _OKX_BAR[timeframe]
    inst = f"{symbol.upper()}-USDT"
    rows: list[list[float]] = []
    cursor: int | None = None

    # First page comes from /candles (limit 300); older pages from
    # /history-candles (limit 100). Both return newest-first.
    for page in range(140):
        if page == 0:
            payload = _get(
                "https://www.okx.com/api/v5/market/candles",
                {"instId": inst, "bar": bar, "limit": 300},
            )
        else:
            payload = _get(
                "https://www.okx.com/api/v5/market/history-candles",
                {"instId": inst, "bar": bar, "limit": 100, "after": str(cursor)},
            )
        if str(payload.get("code")) != "0":
            raise ExchangeError(f"OKX error for {inst}: {payload.get('msg')}")
        data = payload.get("data") or []
        if not data:
            break
        for row in data:
            # row[8] == "1" once the candle is closed. Anything else is live.
            if len(row) > 8 and str(row[8]) != "1":
                continue
            rows.append([
                float(row[0]), float(row[1]), float(row[2]),
                float(row[3]), float(row[4]), float(row[5]),
            ])
        cursor = int(data[-1][0])
        if len(rows) >= want:
            break
        time.sleep(0.12)  # OKX public rate limit is generous but not unlimited
    return rows


def _binance_rows(symbol: str, timeframe: str, want: int) -> list[list[float]]:
    """Binance.US paginates backwards via ``endTime``; returns oldest-first."""
    interval = _BINANCE_BAR[timeframe]
    pair = f"{symbol.upper()}USDT"
    step = _TIMEFRAME_MS[timeframe]
    rows: list[list[float]] = []
    end = _now_ms()

    for _ in range(30):
        payload = _get(
            "https://api.binance.us/api/v3/klines",
            {"symbol": pair, "interval": interval, "limit": 1000, "endTime": end},
        )
        if not isinstance(payload, list) or not payload:
            break
        for row in payload:
            open_ms = int(row[0])
            # Binance does not flag the live bar — drop any bar whose close
            # time is still in the future.
            if open_ms + step > _now_ms():
                continue
            rows.append([
                float(open_ms), float(row[1]), float(row[2]),
                float(row[3]), float(row[4]), float(row[5]),
            ])
        end = int(payload[0][0]) - 1
        if len(rows) >= want:
            break
        time.sleep(0.12)
    return rows


def _coinbase_rows(symbol: str, timeframe: str, want: int) -> list[list[float]]:
    """Coinbase caps at 300 bars per call and offers few granularities."""
    gran = _COINBASE_GRAN.get(timeframe)
    if gran is None:
        return []
    product = f"{symbol.upper()}-USD"
    step = _TIMEFRAME_MS[timeframe]
    rows: list[list[float]] = []
    end = int(time.time())

    for _ in range(20):
        start = end - gran * 300
        payload = _get(
            f"https://api.exchange.coinbase.com/products/{product}/candles",
            {"granularity": gran, "start": start, "end": end},
        )
        if not isinstance(payload, list) or not payload:
            break
        for row in payload:  # [time, low, high, open, close, volume], newest-first
            open_ms = int(row[0]) * 1000
            if open_ms + step > _now_ms():
                continue
            rows.append([
                float(open_ms), float(row[3]), float(row[2]),
                float(row[1]), float(row[4]), float(row[5]),
            ])
        end = start
        if len(rows) >= want:
            break
        time.sleep(0.2)
    return rows


#: Binance.US leads because it returns 1000 bars per request against OKX's 100 —
#: an order of magnitude fewer round trips when pulling deep intraday history.
#: OKX follows because it lists mid-cap alts Binance.US does not. Coinbase is a
#: last resort: only three usable granularities and 300 bars per call.
_SOURCES = (("binance.us", _binance_rows), ("okx", _okx_rows), ("coinbase", _coinbase_rows))

#: A venue that returns far less than asked is not really a hit — keep looking
#: and take the deepest series any venue can supply.
_SUFFICIENT = 0.7


def _normalise(rows: list[list[float]], symbol: str, timeframe: str, source: str) -> Candles:
    """De-duplicate by timestamp, sort oldest-first, drop non-finite bars."""
    by_ts: dict[int, list[float]] = {}
    for row in rows:
        if not all(np.isfinite(row)):
            continue
        if row[4] <= 0 or row[2] < row[3]:  # bad close, or high below low
            continue
        by_ts[int(row[0])] = row
    ordered = [by_ts[t] for t in sorted(by_ts)]
    arr = np.asarray(ordered, dtype=float) if ordered else np.empty((0, 6))
    return Candles(
        symbol=symbol.upper(), timeframe=timeframe, source=source,
        ts=arr[:, 0].astype(np.int64) if arr.size else np.empty(0, dtype=np.int64),
        opens=arr[:, 1] if arr.size else np.empty(0),
        highs=arr[:, 2] if arr.size else np.empty(0),
        lows=arr[:, 3] if arr.size else np.empty(0),
        closes=arr[:, 4] if arr.size else np.empty(0),
        volumes=arr[:, 5] if arr.size else np.empty(0),
    )


# ── disk cache (survives between scheduled experiment cycles) ────────────────


def _cache_path(symbol: str, timeframe: str) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, f"{symbol.upper()}_{timeframe}.json")


def _load_cache(symbol: str, timeframe: str) -> tuple[list[list[float]], str] | None:
    path = _cache_path(symbol, timeframe)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            blob = json.load(fh)
        return blob.get("rows", []), blob.get("source", "cache")
    except Exception as exc:  # noqa: BLE001 — a corrupt cache must not stop a run
        log.info("candle cache unreadable for %s %s: %s", symbol, timeframe, exc)
        return None


def _save_cache(symbol: str, timeframe: str, rows: list[list[float]], source: str) -> None:
    try:
        with open(_cache_path(symbol, timeframe), "w", encoding="utf-8") as fh:
            json.dump({"source": source, "saved_at": _now_ms(), "rows": rows}, fh)
    except Exception as exc:  # noqa: BLE001
        log.info("candle cache unwritable for %s %s: %s", symbol, timeframe, exc)


def fetch_candles(
    symbol: str, timeframe: str, want: int = 3000, *, use_cache: bool = True
) -> Candles:
    """Oldest-first closed candles for ``symbol`` at ``timeframe``.

    Merges any cached history with a fresh fetch, so a scheduled cycle extends
    the series instead of re-downloading it. Raises :class:`ExchangeError` only
    when every source fails AND there is no cache.
    """
    if timeframe not in _TIMEFRAME_MS:
        raise ExchangeError(f"unsupported timeframe: {timeframe}")

    cached_rows: list[list[float]] = []
    source = "cache"
    if use_cache:
        hit = _load_cache(symbol, timeframe)
        if hit:
            cached_rows, source = hit

    fresh: list[list[float]] = []
    errors: list[str] = []
    for name, fn in _SOURCES:
        try:
            rows = fn(symbol, timeframe, want)
        except Exception as exc:  # noqa: BLE001 — try the next venue
            errors.append(f"{name}: {type(exc).__name__} {str(exc)[:90]}")
            continue
        if len(rows) > len(fresh):
            fresh, source = rows, name
        if len(fresh) >= want * _SUFFICIENT:
            break

    merged = cached_rows + fresh
    if not merged:
        raise ExchangeError(
            f"no candles for {symbol} {timeframe} — " + "; ".join(errors or ["all sources empty"])
        )

    candles = _normalise(merged, symbol, timeframe, source)
    if use_cache and fresh:
        # Cap the stored history so the cache cannot grow without bound.
        keep = candles.tail(max(want, 6000))
        _save_cache(
            symbol, timeframe,
            [
                [float(t), float(o), float(h), float(low), float(c), float(v)]
                for t, o, h, low, c, v in zip(
                    keep.ts, keep.opens, keep.highs, keep.lows, keep.closes, keep.volumes,
                    strict=True,
                )
            ],
            source,
        )
    return candles


def probe_sources() -> dict[str, Any]:
    """Which venues are reachable right now — used by the experiment preflight."""
    out: dict[str, Any] = {}
    for name, fn in _SOURCES:
        started = time.time()
        try:
            rows = fn("BTC", "1h", 10)
            out[name] = {"ok": bool(rows), "bars": len(rows), "ms": int((time.time() - started) * 1000)}
        except Exception as exc:  # noqa: BLE001
            out[name] = {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:120]}"}
    return out
