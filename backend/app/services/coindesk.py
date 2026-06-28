"""CoinDesk Data API client — the single source of truth for crypto data.

Formerly CryptoCompare; rebranded to the CoinDesk Data API. Covers spot &
index prices, OHLCV history, top-by-market-cap lists, asset search AND the
derivatives layer (perpetual funding rate, open interest, futures OHLC) that
powers FinCoach's crypto health / squeeze-risk analytics.

Design notes
────────────
* Auth: ``Authorization: Apikey {KEY}`` header (the API also accepts an
  ``api_key`` query param; we use the header).
* Base URL + every endpoint PATH and the response-shape parsing are isolated
  in THIS module. CoinDesk returns ``{"Data": ...}`` envelopes with UPPER_CASE
  field names; all of that normalisation lives here so the tool/agent layers
  stay clean. If a path or field name needs adjusting after a live call, this
  is the only file to touch.
* Public function names mirror the old ``coingecko`` service (coin_price,
  coin_market_data, top_coins, coin_history, trending_coins, global_market,
  search_coins) so callers migrate with a one-line import swap, plus the new
  derivatives functions (funding_rate, funding_rate_history, open_interest).

Pricing source: we use the CADLI index (``/index/cc``) as the canonical,
exchange-independent reference price for a coin. Market-cap/volume/rank come
from the asset top-list. Derivatives come from a configurable futures venue
(default ``binance``) via ``settings.coindesk_futures_market``.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import UTC, datetime
from typing import Any

import requests

from app.settings import settings

log = logging.getLogger("fincoach.coindesk")

_BASE_URL = "https://data-api.coindesk.com"
_DEFAULT_TIMEOUT = 10

# ── Endpoint paths (single source of truth) ────────────────────────────────
# Spot trades on real exchanges. Index = CoinDesk aggregate reference rates.
_EP_INDEX_TICK = "/index/cc/v1/latest/tick"
_EP_INDEX_HISTORY_DAYS = "/index/cc/v1/historical/days"
_EP_INDEX_HISTORY_HOURS = "/index/cc/v1/historical/hours"
_EP_SPOT_TICK = "/spot/v1/latest/tick"
_EP_SPOT_HISTORY_DAYS = "/spot/v1/historical/days"
_EP_SPOT_HISTORY_HOURS = "/spot/v1/historical/hours"
_EP_ASSET_TOP_LIST = "/asset/v1/top/list"
_EP_ASSET_SEARCH = "/asset/v1/search"
# Derivatives (futures). Latest tick bundles funding rate + open interest.
_EP_FUT_TICK = "/futures/v1/latest/tick"           # price tick (no funding here)
_EP_FUT_FUNDING_TICK = "/futures/v1/latest/funding-rate/tick"   # confirmed path
_EP_FUT_OI_TICK = "/futures/v1/latest/open-interest/tick"       # confirmed path
_EP_FUT_FUNDING_HISTORY = "/futures/v1/historical/funding-rate/days"
_EP_FUT_OI_HISTORY = "/futures/v1/historical/open-interest/days"
_EP_FUT_HISTORY_DAYS = "/futures/v1/historical/days"

# Canonical index family. CADLI is CoinDesk's flagship aggregate index.
_INDEX_MARKET = "cadli"
# Spot exchange used when an index value is unavailable.
_SPOT_MARKET = "coinbase"

# Per-path TTL seconds (matched against the path prefix).
_TTL: dict[str, int] = {
    _EP_INDEX_TICK: 60,
    _EP_SPOT_TICK: 60,
    _EP_ASSET_TOP_LIST: 5 * 60,
    _EP_ASSET_SEARCH: 24 * 3600,
    _EP_INDEX_HISTORY_DAYS: 10 * 60,
    _EP_SPOT_HISTORY_DAYS: 10 * 60,
    # Intraday bars refresh fast — keep them short so a 4h-horizon signal sees
    # the latest closed hourly candle rather than a stale cache.
    _EP_INDEX_HISTORY_HOURS: 3 * 60,
    _EP_SPOT_HISTORY_HOURS: 3 * 60,
    _EP_FUT_TICK: 60,
    _EP_FUT_FUNDING_TICK: 60,
    _EP_FUT_OI_TICK: 60,
    _EP_FUT_FUNDING_HISTORY: 10 * 60,
    _EP_FUT_OI_HISTORY: 10 * 60,
    _EP_FUT_HISTORY_DAYS: 10 * 60,
}
_DEFAULT_TTL = 2 * 60

_cache: dict[str, tuple[float, Any]] = {}
_cache_lock = threading.Lock()

# Stablecoins to exclude from trending / top-N results.
_STABLECOINS: frozenset[str] = frozenset(
    {"USDT", "USDC", "DAI", "FDUSD", "USDE", "TUSD", "BUSD", "USDP", "GUSD", "FRAX", "LUSD"}
)

# Known symbol → display name. Used so crypto detection / name resolution does
# not require a network round-trip for the common coins. CoinDesk addresses
# assets by their SYMBOL directly (no opaque id), so this doubles as the
# "is this a crypto ticker?" allow-list.
_SYMBOL_TO_ID: dict[str, str] = {
    "BTC": "Bitcoin", "ETH": "Ethereum", "BNB": "BNB", "SOL": "Solana",
    "XRP": "XRP", "ADA": "Cardano", "DOGE": "Dogecoin", "TON": "Toncoin",
    "TRX": "TRON", "AVAX": "Avalanche", "SHIB": "Shiba Inu", "DOT": "Polkadot",
    "LINK": "Chainlink", "MATIC": "Polygon", "POL": "Polygon", "LTC": "Litecoin",
    "BCH": "Bitcoin Cash", "UNI": "Uniswap", "NEAR": "NEAR Protocol",
    "APT": "Aptos", "ICP": "Internet Computer", "FIL": "Filecoin",
    "ATOM": "Cosmos", "ARB": "Arbitrum", "OP": "Optimism", "VET": "VeChain",
    "ALGO": "Algorand", "HBAR": "Hedera", "GRT": "The Graph", "SAND": "The Sandbox",
    "MANA": "Decentraland", "AXS": "Axie Infinity", "XLM": "Stellar", "EOS": "EOS",
    "AAVE": "Aave", "MKR": "Maker", "CRV": "Curve DAO", "LDO": "Lido DAO",
    "RUNE": "THORChain", "INJ": "Injective", "SUI": "Sui", "SEI": "Sei",
    "PEPE": "Pepe", "WIF": "dogwifhat", "BONK": "Bonk", "FLOKI": "FLOKI",
    "IMX": "Immutable", "XMR": "Monero", "ETC": "Ethereum Classic",
    "FET": "Artificial Superintelligence Alliance", "RENDER": "Render",
    "TAO": "Bittensor", "JUP": "Jupiter", "WLD": "Worldcoin", "STRK": "Starknet",
    "PYTH": "Pyth Network", "TIA": "Celestia", "KAS": "Kaspa",
}


# ---------------------------------------------------------------------------
# Errors + transport
# ---------------------------------------------------------------------------


class CoinDeskError(RuntimeError):
    """Raised on transport / auth / rate-limit / not-found / bad-shape errors."""


def _ttl_for(path: str) -> int:
    return _TTL.get(path, _DEFAULT_TTL)


def _cache_get(key: str, ttl: int) -> Any | None:
    with _cache_lock:
        hit = _cache.get(key)
    if hit is None:
        return None
    fetched_at, value = hit
    if time.time() - fetched_at > ttl:
        return None
    return value


def _cache_set(key: str, value: Any) -> None:
    with _cache_lock:
        _cache[key] = (time.time(), value)


def _request(path: str, params: dict[str, Any] | None = None) -> Any:
    """GET {_BASE_URL}{path} with header auth, TTL caching, error normalisation."""
    params = params or {}
    cache_key = path + ":" + ":".join(f"{k}={v}" for k, v in sorted(params.items()))
    ttl = _ttl_for(path)

    cached = _cache_get(cache_key, ttl)
    if cached is not None:
        return cached

    key = settings.coindesk_api_key
    if not key:
        raise CoinDeskError(
            "COINDESK_API_KEY is not set — add it to backend/.env "
            "(get one at https://developers.coindesk.com/settings/api-keys)."
        )

    url = f"{_BASE_URL}{path}"
    headers = {"Authorization": f"Apikey {key}"}
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=_DEFAULT_TIMEOUT)
        if resp.status_code == 429:
            raise CoinDeskError("CoinDesk rate limit (429) — try again in a moment")
        if resp.status_code in (401, 403):
            raise CoinDeskError("CoinDesk auth failed (check COINDESK_API_KEY)")
        if resp.status_code == 404:
            raise CoinDeskError(f"CoinDesk: resource not found — {path}")
        resp.raise_for_status()
        payload = resp.json()
    except requests.RequestException as exc:
        raise CoinDeskError(f"CoinDesk transport error ({path}): {exc}") from exc
    except ValueError as exc:
        raise CoinDeskError(f"CoinDesk bad JSON ({path}): {exc}") from exc

    # CoinDesk wraps errors inside a 200 body too: {"Err": {"message": ...}}.
    if isinstance(payload, dict):
        err = payload.get("Err") or payload.get("Error")
        if err:
            msg = err.get("message") if isinstance(err, dict) else str(err)
            if msg:
                raise CoinDeskError(f"CoinDesk API error ({path}): {msg}")

    _cache_set(cache_key, payload)
    return payload


# ---------------------------------------------------------------------------
# Small coercers
# ---------------------------------------------------------------------------


def _to_float(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _fmt_money(value: Any) -> str:
    """Format a large dollar number as '$1.2B' / '$500M' / '$1,234.56'."""
    try:
        n = float(value)
    except (TypeError, ValueError):
        return "n/a"
    if n >= 1_000_000_000:
        return f"${n / 1_000_000_000:.1f}B"
    if n >= 1_000_000:
        return f"${n / 1_000_000:.1f}M"
    return f"${n:,.2f}"


def _first_data_row(payload: Any, instrument: str) -> dict[str, Any]:
    """Extract the per-instrument dict from a CoinDesk latest-tick envelope.

    Tick responses look like ``{"Data": {"BTC-USD": {...}}}`` — but some
    families return ``{"Data": [{...}]}``. Handle both defensively.
    """
    if not isinstance(payload, dict):
        raise CoinDeskError("CoinDesk tick: unexpected payload type")
    data = payload.get("Data")
    if isinstance(data, dict):
        if instrument in data and isinstance(data[instrument], dict):
            return data[instrument]
        # single-key dict
        for v in data.values():
            if isinstance(v, dict):
                return v
        raise CoinDeskError("CoinDesk tick: empty Data map")
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data[0]
    raise CoinDeskError("CoinDesk tick: no Data rows")


def _symbol(symbol: str) -> str:
    return symbol.strip().upper().split("-")[0]


def _instrument(symbol: str, quote: str = "USD") -> str:
    """Spot/index instrument id, e.g. 'BTC-USD'."""
    return f"{_symbol(symbol)}-{quote.upper()}"


def _perp_instrument(symbol: str) -> str:
    """Perpetual futures instrument id for the configured venue.

    Most venues on CoinDesk use ``{BASE}-USDT-VANILLA-PERPETUAL``.
    """
    return f"{_symbol(symbol)}-USDT-VANILLA-PERPETUAL"


# ---------------------------------------------------------------------------
# Spot / index prices
# ---------------------------------------------------------------------------


def _index_tick(symbol: str, quote: str = "USD") -> dict[str, Any]:
    instrument = _instrument(symbol, quote)
    payload = _request(
        _EP_INDEX_TICK,
        {"market": _INDEX_MARKET, "instruments": instrument},
    )
    return _first_data_row(payload, instrument)


def _spot_tick(symbol: str, quote: str = "USD") -> dict[str, Any]:
    instrument = _instrument(symbol, quote)
    payload = _request(
        _EP_SPOT_TICK,
        {"market": _SPOT_MARKET, "instruments": instrument},
    )
    return _first_data_row(payload, instrument)


def _row_to_quote(row: dict[str, Any], symbol: str, currency: str) -> dict[str, Any]:
    """Normalise a CoinDesk tick row into FinCoach's quote shape."""
    price = _to_float(row.get("VALUE") or row.get("PRICE") or row.get("CURRENT_DAY_OPEN"))
    # Day-change percent field name varies across families.
    change = _to_float(
        row.get("CURRENT_DAY_CHANGE_PERCENTAGE")
        or row.get("MOVING_24_HOUR_CHANGE_PERCENTAGE")
        or row.get("CHANGE_PERCENTAGE_24_HOUR")
    )
    prev = None
    if price is not None and change is not None:
        prev = price / (1.0 + change / 100.0)
    last_update = row.get("VALUE_LAST_UPDATE_TS") or row.get("LAST_UPDATE_TS")
    as_of = None
    if last_update:
        try:
            as_of = datetime.fromtimestamp(int(last_update), tz=UTC).isoformat()
        except (TypeError, ValueError, OSError):
            as_of = None
    return {
        "id": _symbol(symbol),
        "symbol": _symbol(symbol),
        "name": _SYMBOL_TO_ID.get(_symbol(symbol), _symbol(symbol)),
        "price": price,
        "previous_close": prev,
        "change_pct_24h": round(change, 4) if change is not None else None,
        "market_cap": _to_float(row.get("CIRCULATING_MKT_CAP_USD") or row.get("MOSCOW_TIME")),
        "volume_24h": _to_float(row.get("MOVING_24_HOUR_QUOTE_VOLUME") or row.get("CURRENT_DAY_QUOTE_VOLUME")),
        "rank": None,
        "currency": currency.upper(),
        "last_updated": as_of,
        "source": "coindesk",
    }


def coin_price(symbol: str, currency: str = "usd") -> dict[str, Any]:
    """Single-coin reference price. Tries the CADLI index, falls back to spot."""
    try:
        row = _index_tick(symbol, currency.upper())
    except CoinDeskError as exc:
        log.info("CoinDesk index tick failed for %s, trying spot: %s", symbol, exc)
        row = _spot_tick(symbol, currency.upper())
    quote = _row_to_quote(row, symbol, currency)
    if quote.get("price") is None:
        raise CoinDeskError(f"No price data for '{symbol}' from CoinDesk")
    return quote


def coin_market_data(symbols: list[str], currency: str = "usd") -> list[dict[str, Any]]:
    """Price + market data for a list of symbols (one tick call per symbol)."""
    out: list[dict[str, Any]] = []
    for sym in symbols:
        try:
            out.append(coin_price(sym, currency=currency))
        except CoinDeskError as exc:
            log.info("CoinDesk market data skip %s: %s", sym, exc)
    return out


def top_coins(
    limit: int = 10,
    currency: str = "usd",
    *,
    exclude_stablecoins: bool = True,
) -> list[dict[str, Any]]:
    """Top N coins by circulating market cap (CoinDesk asset top-list).

    The API requires ``limit`` ≥ 10; we fetch 50 and filter stablecoins
    to guarantee the caller gets the requested number of real assets.
    """
    fetch_limit = max(50, limit * 3)  # fetch plenty so stablecoin filtering leaves enough
    payload = _request(
        _EP_ASSET_TOP_LIST,
        {"limit": fetch_limit},
    )
    rows_raw = _top_list_rows(payload)
    rows: list[dict[str, Any]] = []
    for rank_idx, item in enumerate(rows_raw, start=1):
        sym = (item.get("SYMBOL") or item.get("symbol") or "").upper()
        if not sym:
            continue
        if exclude_stablecoins and sym in _STABLECOINS:
            continue
        row = _top_row_to_market(item, currency)
        # Assign rank from list position if not embedded in the row.
        if row["rank"] is None:
            row["rank"] = rank_idx
        rows.append(row)
        if len(rows) >= limit:
            break
    return rows


def _top_list_rows(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("Data")
    if isinstance(data, dict):
        lst = data.get("LIST") or data.get("list")
        if isinstance(lst, list):
            return [r for r in lst if isinstance(r, dict)]
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    return []


def _top_row_to_market(item: dict[str, Any], currency: str) -> dict[str, Any]:
    sym = (item.get("SYMBOL") or "").upper()
    # PRICE_USD is the confirmed field name from the live /asset/v1/top/list response.
    price = _to_float(item.get("PRICE_USD") or item.get("PRICE_CONVERSION_VALUE"))
    change = _to_float(
        item.get("SPOT_MOVING_24_HOUR_CHANGE_PERCENTAGE_USD")
        or item.get("SPOT_MOVING_24_HOUR_CHANGE_PERCENTAGE_CONVERSION")
    )
    prev = price / (1.0 + change / 100.0) if (price is not None and change is not None and change != -100.0) else price
    return {
        "id": sym,
        "symbol": sym,
        "name": item.get("NAME") or _SYMBOL_TO_ID.get(sym, sym),
        "price": price,
        "previous_close": prev,
        "change_pct_24h": round(change, 4) if change is not None else None,
        "market_cap": _to_float(item.get("CIRCULATING_MKT_CAP_USD") or item.get("TOTAL_MKT_CAP_USD")),
        "volume_24h": _to_float(item.get("SPOT_MOVING_24_HOUR_QUOTE_VOLUME_USD")),
        "rank": None,  # assigned by top_coins() from list position
        "currency": currency.upper(),
        "last_updated": None,
        "source": "coindesk",
    }


def trending_coins() -> list[dict[str, Any]]:
    """Proxy for 'trending': top movers among the top-50 by market cap.

    CoinDesk has no search-volume trending endpoint, so we surface the most
    active large caps (ranked by absolute 24h move) as a stand-in.
    """
    try:
        rows = top_coins(limit=50, exclude_stablecoins=True)
    except CoinDeskError as exc:
        raise CoinDeskError(f"trending unavailable: {exc}") from exc
    movers = [r for r in rows if r.get("change_pct_24h") is not None]
    movers.sort(key=lambda r: abs(r["change_pct_24h"]), reverse=True)
    out: list[dict[str, Any]] = []
    for i, r in enumerate(movers[:7]):
        out.append({
            "id": r["id"],
            "name": r["name"],
            "symbol": r["symbol"],
            "rank": r.get("rank"),
            "price_usd": r.get("price"),
            "market_cap": r.get("market_cap"),
            "change_pct_24h": r.get("change_pct_24h"),
            "score": i,  # 0 = biggest mover
        })
    return out


def global_market() -> dict[str, Any]:
    """Aggregate crypto market stats derived from the top-list.

    CoinDesk exposes per-asset data; we aggregate the top-50 to approximate
    total market cap, 24h volume and BTC/ETH dominance.
    """
    rows = top_coins(limit=50, exclude_stablecoins=False)
    total_cap = sum(r["market_cap"] for r in rows if r.get("market_cap"))
    total_vol = sum(r["volume_24h"] for r in rows if r.get("volume_24h"))
    by_sym = {r["symbol"]: r for r in rows}
    btc_cap = (by_sym.get("BTC") or {}).get("market_cap") or 0.0
    eth_cap = (by_sym.get("ETH") or {}).get("market_cap") or 0.0
    # Cap-weighted 24h change across the sample.
    weighted = 0.0
    for r in rows:
        cap, chg = r.get("market_cap"), r.get("change_pct_24h")
        if cap and chg is not None and total_cap:
            weighted += chg * (cap / total_cap)
    return {
        "total_market_cap_usd": total_cap or None,
        "total_volume_24h_usd": total_vol or None,
        "btc_dominance_pct": round(btc_cap / total_cap * 100, 2) if total_cap else None,
        "eth_dominance_pct": round(eth_cap / total_cap * 100, 2) if total_cap else None,
        "market_cap_change_pct_24h": round(weighted, 2) if total_cap else None,
        "active_cryptocurrencies": len(rows),
        "markets": None,
        "note": "Aggregated from CoinDesk top-50 by market cap (approximation).",
    }


# ---------------------------------------------------------------------------
# Historical OHLCV
# ---------------------------------------------------------------------------


def _history_rows(payload: Any) -> list[dict[str, Any]]:
    """Extract a list of OHLC rows from a CoinDesk historical response.

    Handles three response shapes observed across endpoints:
      • ``{"Data": [...]}``          — direct list (funding-rate, OI history)
      • ``{"Data": {"Data": [...]}}``— nested dict (index/spot history)
      • ``{"Data": {"entries": [...]}}`` — older shape
    """
    if not isinstance(payload, dict):
        return []
    data = payload.get("Data")
    # Direct list shape (confirmed for futures history endpoints).
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    # Nested dict shape (index/spot history).
    if isinstance(data, dict):
        inner = data.get("Data") or data.get("entries") or data.get("list") or []
        if isinstance(inner, list):
            return [r for r in inner if isinstance(r, dict)]
    return []


def coin_history(symbol: str, days: int = 365, vs_currency: str = "usd") -> list[dict[str, Any]]:
    """Daily close history. Returns newest-first ``{date, close}`` rows."""
    instrument = _instrument(symbol, vs_currency.upper())
    limit = max(1, min(int(days), 2000))
    try:
        payload = _request(
            _EP_INDEX_HISTORY_DAYS,
            {"market": _INDEX_MARKET, "instrument": instrument, "limit": limit},
        )
    except CoinDeskError:
        payload = _request(
            _EP_SPOT_HISTORY_DAYS,
            {"market": _SPOT_MARKET, "instrument": instrument, "limit": limit},
        )
    rows: list[dict[str, Any]] = []
    for item in _history_rows(payload):
        ts = item.get("TIMESTAMP") or item.get("timestamp")
        close = _to_float(item.get("CLOSE") or item.get("close"))
        if ts is None or close is None:
            continue
        try:
            dt = datetime.fromtimestamp(int(ts), tz=UTC)
        except (TypeError, ValueError, OSError):
            continue
        rows.append({"date": dt.strftime("%Y-%m-%d"), "close": close})
    rows.sort(key=lambda r: r["date"], reverse=True)
    return rows


def ohlcv(symbol: str, vs_currency: str = "usd", days: int = 7) -> list[dict[str, Any]]:
    """OHLCV candlesticks (daily). Newest-first."""
    instrument = _instrument(symbol, vs_currency.upper())
    limit = max(1, min(int(days), 2000))
    try:
        payload = _request(
            _EP_INDEX_HISTORY_DAYS,
            {"market": _INDEX_MARKET, "instrument": instrument, "limit": limit},
        )
    except CoinDeskError:
        payload = _request(
            _EP_SPOT_HISTORY_DAYS,
            {"market": _SPOT_MARKET, "instrument": instrument, "limit": limit},
        )
    rows: list[dict[str, Any]] = []
    for item in _history_rows(payload):
        ts = item.get("TIMESTAMP")
        if ts is None:
            continue
        rows.append({
            "timestamp": int(ts) * 1000,
            "open": _to_float(item.get("OPEN")),
            "high": _to_float(item.get("HIGH")),
            "low": _to_float(item.get("LOW")),
            "close": _to_float(item.get("CLOSE")),
        })
    rows.sort(key=lambda r: r["timestamp"], reverse=True)
    return rows


def coin_history_hourly(
    symbol: str, hours: int = 120, vs_currency: str = "usd"
) -> list[dict[str, Any]]:
    """Hourly OHLC candles for intraday analysis. Newest-first rows.

    Powers short-horizon (e.g. 4-hour) technicals — EMA crossovers, intraday
    RSI, ATR-based targets — that the daily ``coin_history``/``ohlcv`` series
    are too coarse to support. Tries the CADLI index hours endpoint, falls back
    to the spot exchange. Each row: ``{ts, date, open, high, low, close}`` where
    ``ts`` is an epoch-second integer and ``date`` is a UTC ``YYYY-MM-DD HH:00``
    label.
    """
    instrument = _instrument(symbol, vs_currency.upper())
    limit = max(2, min(int(hours), 2000))
    try:
        payload = _request(
            _EP_INDEX_HISTORY_HOURS,
            {"market": _INDEX_MARKET, "instrument": instrument, "limit": limit},
        )
    except CoinDeskError:
        payload = _request(
            _EP_SPOT_HISTORY_HOURS,
            {"market": _SPOT_MARKET, "instrument": instrument, "limit": limit},
        )
    rows: list[dict[str, Any]] = []
    for item in _history_rows(payload):
        ts = item.get("TIMESTAMP") or item.get("timestamp")
        close = _to_float(item.get("CLOSE") or item.get("close"))
        if ts is None or close is None:
            continue
        try:
            dt = datetime.fromtimestamp(int(ts), tz=UTC)
        except (TypeError, ValueError, OSError):
            continue
        rows.append({
            "ts": int(ts),
            "date": dt.strftime("%Y-%m-%d %H:00"),
            "open": _to_float(item.get("OPEN")),
            "high": _to_float(item.get("HIGH")),
            "low": _to_float(item.get("LOW")),
            "close": close,
        })
    rows.sort(key=lambda r: r["ts"], reverse=True)
    return rows


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


def search_coins(query: str) -> list[dict[str, Any]]:
    """Search assets by name/symbol. Local map first, then the API."""
    q = (query or "").strip()
    qu = q.upper()
    # Fast local hit on the known-symbol map.
    local: list[dict[str, Any]] = []
    for sym, name in _SYMBOL_TO_ID.items():
        if qu == sym or q.lower() in name.lower():
            local.append({"id": sym, "symbol": sym, "name": name, "rank": None})
    if local:
        return local[:10]
    try:
        payload = _request(_EP_ASSET_SEARCH, {"search_string": q, "limit": 10})
    except CoinDeskError as exc:
        log.info("CoinDesk asset search failed for %r: %s", q, exc)
        return []
    rows = _top_list_rows(payload)
    out: list[dict[str, Any]] = []
    for r in rows[:10]:
        sym = (r.get("SYMBOL") or "").upper()
        if not sym:
            continue
        out.append({
            "id": sym,
            "symbol": sym,
            "name": r.get("NAME") or sym,
            "rank": r.get("RANK") or r.get("CIRCULATING_MKT_CAP_USD_RANK"),
        })
    return out


# ---------------------------------------------------------------------------
# Derivatives — funding rate, open interest, futures history
# ---------------------------------------------------------------------------


def _futures_market() -> str:
    return (settings.coindesk_futures_market or "binance").strip().lower()


def funding_rate(symbol: str) -> dict[str, Any]:
    """Latest perpetual funding rate + open interest for a coin.

    Returns the raw rate, its reporting interval (hours), the rate normalised
    to an 8-hour equivalent, the annualised APY, and current open interest.

    Normalisation (per the crypto-derivatives literature):
        r_8h      = r_h * (8 / h)
        r_8h_bps  = r_8h * 10_000
        APY (%)   = r_8h_bps * 3 * 365 / 100

    Confirmed CoinDesk fields (live-tested):
        VALUE         — latest funding rate (fractional, e.g. 7.4e-5 = 0.0074%)
        INTERVAL_MS   — funding interval in milliseconds (28800000 = 8 h)
    Open interest comes from the separate /open-interest/tick endpoint:
        VALUE_QUOTE   — OI in quote currency (USDT)
    """
    market = _futures_market()
    instrument = _perp_instrument(symbol)

    # Funding rate tick
    payload = _request(
        _EP_FUT_FUNDING_TICK,
        {"market": market, "instruments": instrument},
    )
    row = _first_data_row(payload, instrument)

    # VALUE is the current (latest 8-hour period) funding rate fraction.
    raw = _to_float(row.get("VALUE"))
    if raw is None:
        # Fallback to CURRENT_HOUR_OPEN which holds the latest sampled rate.
        raw = _to_float(row.get("CURRENT_HOUR_OPEN"))

    # INTERVAL_MS: convert ms → hours (28800000 ms = 8 h).
    interval_ms = _to_float(row.get("INTERVAL_MS"))
    interval_h = (interval_ms / 3_600_000.0) if interval_ms else 8.0

    # Open interest from dedicated endpoint (best-effort, don't fail if missing).
    open_interest: float | None = None
    try:
        oi_payload = _request(
            _EP_FUT_OI_TICK,
            {"market": market, "instruments": instrument},
        )
        oi_row = _first_data_row(oi_payload, instrument)
        open_interest = _to_float(
            oi_row.get("VALUE_QUOTE")          # OI in USDT (confirmed field)
            or oi_row.get("VALUE_SETTLEMENT")
            or oi_row.get("VALUE")
        )
    except CoinDeskError:
        pass

    if raw is None:
        raise CoinDeskError(f"No funding rate for {instrument} on {market}")

    r_8h = raw * (8.0 / interval_h) if interval_h else raw
    r_8h_bps = r_8h * 10_000.0
    apy_pct = r_8h_bps * 3.0 * 365.0 / 100.0

    return {
        "symbol": _symbol(symbol),
        "market": market,
        "instrument": instrument,
        "raw_rate": raw,
        "interval_hours": interval_h,
        "rate_8h": r_8h,
        "rate_8h_bps": round(r_8h_bps, 4),
        "apy_pct": round(apy_pct, 2),
        "open_interest": open_interest,
        "direction": "longs_pay_shorts" if raw > 0 else "shorts_pay_longs" if raw < 0 else "neutral",
        "source": "coindesk",
    }


def funding_rate_history(symbol: str, days: int = 30) -> list[dict[str, Any]]:
    """Historical daily funding-rate OHLC. Newest-first ``{date, close}`` (close = rate)."""
    market = _futures_market()
    instrument = _perp_instrument(symbol)
    limit = max(1, min(int(days), 2000))
    payload = _request(
        _EP_FUT_FUNDING_HISTORY,
        {"market": market, "instrument": instrument, "limit": limit},
    )
    rows: list[dict[str, Any]] = []
    for item in _history_rows(payload):
        ts = item.get("TIMESTAMP")
        close = _to_float(item.get("CLOSE") or item.get("FUNDING_RATE_CLOSE"))
        if ts is None or close is None:
            continue
        try:
            dt = datetime.fromtimestamp(int(ts), tz=UTC)
        except (TypeError, ValueError, OSError):
            continue
        rows.append({"date": dt.strftime("%Y-%m-%d"), "close": close})
    rows.sort(key=lambda r: r["date"], reverse=True)
    return rows


def futures_history(symbol: str, days: int = 30) -> list[dict[str, Any]]:
    """Historical daily perpetual-futures OHLC. Newest-first ``{date, close}``."""
    market = _futures_market()
    instrument = _perp_instrument(symbol)
    limit = max(1, min(int(days), 2000))
    payload = _request(
        _EP_FUT_HISTORY_DAYS,
        {"market": market, "instrument": instrument, "limit": limit},
    )
    rows: list[dict[str, Any]] = []
    for item in _history_rows(payload):
        ts = item.get("TIMESTAMP")
        close = _to_float(item.get("CLOSE"))
        if ts is None or close is None:
            continue
        try:
            dt = datetime.fromtimestamp(int(ts), tz=UTC)
        except (TypeError, ValueError, OSError):
            continue
        rows.append({"date": dt.strftime("%Y-%m-%d"), "close": close})
    rows.sort(key=lambda r: r["date"], reverse=True)
    return rows


def open_interest_history(symbol: str, days: int = 30) -> list[dict[str, Any]]:
    """Historical daily open-interest. Newest-first ``{date, close}`` (OI in USD).

    Confirmed CoinDesk fields: CLOSE_QUOTE (OI in USDT, daily close).
    """
    market = _futures_market()
    instrument = _perp_instrument(symbol)
    limit = max(1, min(int(days), 2000))
    payload = _request(
        _EP_FUT_OI_HISTORY,
        {"market": market, "instrument": instrument, "limit": limit},
    )
    rows: list[dict[str, Any]] = []
    for item in _history_rows(payload):
        ts = item.get("TIMESTAMP")
        # CLOSE_QUOTE is OI denominated in the quote currency (USDT ≈ USD).
        close = _to_float(
            item.get("CLOSE_QUOTE")
            or item.get("CLOSE_SETTLEMENT")
            or item.get("CLOSE")
        )
        if ts is None or close is None:
            continue
        try:
            dt = datetime.fromtimestamp(int(ts), tz=UTC)
        except (TypeError, ValueError, OSError):
            continue
        rows.append({"date": dt.strftime("%Y-%m-%d"), "close": close})
    rows.sort(key=lambda r: r["date"], reverse=True)
    return rows
