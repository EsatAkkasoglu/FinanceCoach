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


# ── data quality ─────────────────────────────────────────────────────────────
#
# Learned the hard way. The first full tournament run crowned
# TRX/15m/bollinger_reversion with a +8744% out-of-sample return. It was not an
# edge: on Binance.US, 68% of TRX 15-minute bars had ZERO return, 64% had zero
# volume, and the median bar range was 0.000%. The price sat frozen for hours,
# then printed an 11% jump when somebody finally traded. A mean-reversion rule
# backtested on that "buys the low print and sells the high print" — it is
# harvesting the bid-ask bounce of a dead order book, which no one can trade.
#
# The same pair on OKX had 3% stale bars and a 0.07% median range: a real
# market. So the venue, not the coin, was the problem — and picking a source by
# history depth (which is what made Binance.US the default) selected the worst
# possible venue for exactly the pairs where it mattered most.
#
# These gates run on every fetch. A series that fails them is returned with
# ``tradeable=False`` and the tournament skips it, loudly.

#: Above this share of unchanged closes the series is a stale book, not a market.
MAX_STALE_FRACTION = 0.20
#: Above this share of zero-volume bars nothing is actually trading.
MAX_ZERO_VOLUME_FRACTION = 0.20
#: A median high-low range below this is a frozen book (BTC/ETH run ~0.16%).
MIN_MEDIAN_RANGE_PCT = 0.02
#: A single-bar move this large is a split, redenomination or data splice —
#: never a market move. TRX/1h showed +385.59% in one 30-minute bar.
DISCONTINUITY_THRESHOLD = 0.50


@dataclass
class Quality:
    """Whether a price series is fit to backtest on."""

    n_bars: int
    stale_fraction: float
    zero_volume_fraction: float
    median_range_pct: float
    max_abs_return_pct: float
    n_discontinuities: int
    tradeable: bool
    reasons: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "n_bars": self.n_bars,
            "stale_fraction": round(self.stale_fraction, 4),
            "zero_volume_fraction": round(self.zero_volume_fraction, 4),
            "median_range_pct": round(self.median_range_pct, 4),
            "max_abs_return_pct": round(self.max_abs_return_pct, 3),
            "n_discontinuities": self.n_discontinuities,
            "tradeable": self.tradeable,
            "reasons": self.reasons,
        }


def assess(
    closes: np.ndarray, highs: np.ndarray, lows: np.ndarray, volumes: np.ndarray
) -> Quality:
    """Grade a price series for tradability."""
    n = int(closes.size)
    if n < 20:
        return Quality(n, 1.0, 1.0, 0.0, 0.0, 0, False, [f"only {n} bars"])

    rets = closes[1:] / closes[:-1] - 1.0
    stale = float(np.mean(np.abs(rets) < 1e-12))
    zero_vol = float(np.mean(volumes <= 0))
    med_range = float(np.median((highs - lows) / np.maximum(closes, 1e-12))) * 100.0
    max_abs = float(np.max(np.abs(rets))) * 100.0
    n_disc = int(np.count_nonzero(np.abs(rets) > DISCONTINUITY_THRESHOLD))

    reasons: list[str] = []
    if stale > MAX_STALE_FRACTION:
        reasons.append(f"{stale:.0%} of bars never moved — stale book")
    if zero_vol > MAX_ZERO_VOLUME_FRACTION:
        reasons.append(f"{zero_vol:.0%} of bars had zero volume")
    if med_range < MIN_MEDIAN_RANGE_PCT:
        reasons.append(f"median bar range {med_range:.3f}% — frozen book")
    if n_disc:
        reasons.append(f"{n_disc} bar(s) moved >{DISCONTINUITY_THRESHOLD:.0%} — split or data splice")

    return Quality(n, stale, zero_vol, med_range, max_abs, n_disc, not reasons, reasons)


def _truncate_at_discontinuity(rows: list[list[float]]) -> list[list[float]]:
    """Keep only the segment after the last split/splice jump.

    A redenomination is not a return. Leaving it in hands any long-biased rule a
    free 385% and makes the whole series meaningless; the honest response is to
    treat everything before the break as a different instrument.
    """
    if len(rows) < 3:
        return rows
    closes = np.asarray([r[4] for r in rows], dtype=float)
    rets = closes[1:] / np.maximum(closes[:-1], 1e-12) - 1.0
    breaks = np.flatnonzero(np.abs(rets) > DISCONTINUITY_THRESHOLD)
    if breaks.size == 0:
        return rows
    cut = int(breaks[-1]) + 1
    log.info("truncating %d bars before a price discontinuity at index %d", cut, cut)
    return rows[cut:]


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
    quality: Quality | None = None

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

    @property
    def tradeable(self) -> bool:
        return bool(self.quality is None or self.quality.tradeable)

    def tail(self, n: int) -> Candles:
        return Candles(
            self.symbol, self.timeframe, self.source,
            self.ts[-n:], self.opens[-n:], self.highs[-n:],
            self.lows[-n:], self.closes[-n:], self.volumes[-n:],
            self.quality,
        )

    def window(self, start_ms: int, end_ms: int) -> Candles:
        """The bars whose OPEN time falls in ``[start_ms, end_ms]``.

        Exists so several timeframes can be pinned to one calendar span. Without
        it each timeframe simply takes "the last N bars", which is a different
        number of DAYS per timeframe — 8000 bars is 84 days at 15m and 938 days
        at 4h. Comparing those two and calling the difference a *timeframe*
        effect confounds it with a *regime* effect, and nothing in the result can
        separate the two afterwards.

        Bounds are inclusive and no interpolation happens: a timeframe with no
        bar exactly at ``start_ms`` simply begins at its first bar inside the
        span, which is at most one bar of slack.
        """
        if self.ts.size == 0:
            return self
        mask = (self.ts >= int(start_ms)) & (self.ts <= int(end_ms))
        return Candles(
            self.symbol, self.timeframe, self.source,
            self.ts[mask], self.opens[mask], self.highs[mask],
            self.lows[mask], self.closes[mask], self.volumes[mask],
            self.quality,
        )

    @property
    def span_days(self) -> float:
        """Calendar days actually covered — the number the bar count hides."""
        if self.ts.size < 2:
            return 0.0
        return float(self.ts[-1] - self.ts[0]) / 86_400_000.0


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
    ordered = _truncate_at_discontinuity(ordered)
    arr = np.asarray(ordered, dtype=float) if ordered else np.empty((0, 6))
    quality = (
        assess(arr[:, 4], arr[:, 2], arr[:, 3], arr[:, 5]) if arr.size else None
    )
    return Candles(
        symbol=symbol.upper(), timeframe=timeframe, source=source,
        ts=arr[:, 0].astype(np.int64) if arr.size else np.empty(0, dtype=np.int64),
        opens=arr[:, 1] if arr.size else np.empty(0),
        highs=arr[:, 2] if arr.size else np.empty(0),
        lows=arr[:, 3] if arr.size else np.empty(0),
        closes=arr[:, 4] if arr.size else np.empty(0),
        volumes=arr[:, 5] if arr.size else np.empty(0),
        quality=quality,
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

    When ``FINCOACH_FROZEN_DATA`` names a snapshot directory, that snapshot is
    the ONLY source: no network, no live cache, no writes. This exists because
    an audit caught the live path serving *different venues to the two arms of
    the same A/B* — the cache refreshed between arms and the venue-quality race
    picked differently. A comparison is only controlled if the data cannot
    move; frozen mode makes that a property of the layer instead of a hope.
    """
    if timeframe not in _TIMEFRAME_MS:
        raise ExchangeError(f"unsupported timeframe: {timeframe}")

    frozen = os.environ.get("FINCOACH_FROZEN_DATA")
    if frozen:
        path = os.path.join(frozen, f"{symbol.upper()}_{timeframe}.json")
        if not os.path.exists(path):
            raise ExchangeError(
                f"frozen data layer {frozen} has no {symbol.upper()}/{timeframe} "
                "— frozen mode never falls back to the network"
            )
        with open(path, encoding="utf-8") as fh:
            blob = json.load(fh)
        return _normalise(
            blob.get("rows", []), symbol, timeframe,
            f"frozen:{blob.get('source', 'unknown')}",
        )

    cached_rows: list[list[float]] = []
    source = "cache"
    if use_cache:
        hit = _load_cache(symbol, timeframe)
        if hit:
            cached_rows, source = hit

    # Try every venue and keep the best TRADEABLE series — depth alone is the
    # wrong criterion. Binance.US paginates fastest and so used to win by
    # default, which is precisely how a dead TRX book became the data behind a
    # +8744% "edge". A liquid short series beats a frozen long one.
    fresh: list[list[float]] = []
    errors: list[str] = []
    best_quality: Quality | None = None
    for name, fn in _SOURCES:
        try:
            rows = fn(symbol, timeframe, want)
        except Exception as exc:  # noqa: BLE001 — try the next venue
            errors.append(f"{name}: {type(exc).__name__} {str(exc)[:90]}")
            continue
        if not rows:
            continue
        candidate = _normalise(rows, symbol, timeframe, name)
        q = candidate.quality
        better = (
            fresh == []
            or (q and q.tradeable and not (best_quality and best_quality.tradeable))
            or (
                bool(q and q.tradeable) == bool(best_quality and best_quality.tradeable)
                and len(rows) > len(fresh)
            )
        )
        if better:
            fresh, source, best_quality = rows, name, q
        if best_quality and best_quality.tradeable and len(fresh) >= want * _SUFFICIENT:
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
