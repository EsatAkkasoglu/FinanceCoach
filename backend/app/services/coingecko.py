"""CoinGecko REST client — crypto prices, trending, global market stats.

Free public API: ~30 req/min, no API key required.
All endpoints target v3 of the public API (api.coingecko.com/api/v3).

Role in FinCoach:
  • Primary source for crypto trending and global market data (no AV equivalent)
  • Fallback for crypto quotes when AV DIGITAL_CURRENCY_DAILY rate-limits
  • Top-N coins by market cap for the market_data agent
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

import requests

log = logging.getLogger("fincoach.coingecko")

_BASE_URL = "https://api.coingecko.com/api/v3"
_DEFAULT_TIMEOUT = 8

# Per-path TTL seconds. Keyed by exact path or by prefix (first two segments).
_TTL: dict[str, int] = {
    "simple/price": 60,
    "coins/markets": 60,
    "search/trending": 5 * 60,
    "global": 5 * 60,
    "search": 24 * 3600,
    "coins/list": 24 * 3600,
    "coins/": 10 * 60,  # coins/{id}/ohlc and similar
}
_DEFAULT_TTL = 2 * 60

_cache: dict[str, tuple[float, Any]] = {}
_cache_lock = threading.Lock()

# Stablecoins to exclude from trending / top-N results.
_STABLECOINS: frozenset[str] = frozenset(
    {"USDT", "USDC", "DAI", "FDUSD", "USDE", "TUSD", "BUSD", "USDP", "GUSD", "FRAX", "LUSD"}
)

# Hardcoded symbol → CoinGecko ID for the most-traded coins.
# Used by _symbol_to_id to avoid a search-API round-trip for common lookups.
_SYMBOL_TO_ID: dict[str, str] = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "BNB": "binancecoin",
    "SOL": "solana",
    "XRP": "ripple",
    "ADA": "cardano",
    "DOGE": "dogecoin",
    "TON": "the-open-network",
    "TRX": "tron",
    "AVAX": "avalanche-2",
    "SHIB": "shiba-inu",
    "DOT": "polkadot",
    "LINK": "chainlink",
    "MATIC": "matic-network",
    "POL": "matic-network",
    "LTC": "litecoin",
    "BCH": "bitcoin-cash",
    "UNI": "uniswap",
    "NEAR": "near",
    "APT": "aptos",
    "ICP": "internet-computer",
    "FIL": "filecoin",
    "ATOM": "cosmos",
    "ARB": "arbitrum",
    "OP": "optimism",
    "STX": "blockstack",
    "VET": "vechain",
    "ALGO": "algorand",
    "FTM": "fantom",
    "HBAR": "hedera-hashgraph",
    "GRT": "the-graph",
    "SAND": "the-sandbox",
    "MANA": "decentraland",
    "AXS": "axie-infinity",
    "THETA": "theta-token",
    "XLM": "stellar",
    "EOS": "eos",
    "AAVE": "aave",
    "MKR": "maker",
    "COMP": "compound-governance-token",
    "SNX": "havven",
    "CRV": "curve-dao-token",
    "LDO": "lido-dao",
    "RUNE": "thorchain",
    "INJ": "injective-protocol",
    "SUI": "sui",
    "SEI": "sei-network",
    "PEPE": "pepe",
    "WIF": "dogwifcoin",
    "BONK": "bonk",
    "FLOKI": "floki",
    "IMX": "immutable-x",
    "XMR": "monero",
    "DASH": "dash",
    "ZEC": "zcash",
    "BAT": "basic-attention-token",
    "ZRX": "0x",
    "ENJ": "enjincoin",
    "CHZ": "chiliz",
    "IOTA": "iota",
    "WAVES": "waves",
    "KAVA": "kava",
    "ONE": "harmony",
    "FLOW": "flow",
    "XTZ": "tezos",
    "ETC": "ethereum-classic",
    "FET": "fetch-ai",
    "RENDER": "render-token",
    "TAO": "bittensor",
    "JUP": "jupiter-exchange-solana",
    "WLD": "worldcoin-wld",
    "NOT": "notcoin",
    "BRETT": "based-brett",
    "STRK": "starknet",
    "PYTH": "pyth-network",
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


class CoinGeckoError(RuntimeError):
    """Raised on transport / rate-limit / not-found errors."""


def _ttl_for(path: str) -> int:
    if path in _TTL:
        return _TTL[path]
    # prefix match: "coins/bitcoin/ohlc" → "coins/"
    for prefix, ttl in _TTL.items():
        if prefix.endswith("/") and path.startswith(prefix):
            return ttl
    return _DEFAULT_TTL


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
    """GET {_BASE_URL}/{path} with TTL caching and error normalisation."""
    params = params or {}
    cache_key = path + ":" + ":".join(f"{k}={v}" for k, v in sorted(params.items()))
    ttl = _ttl_for(path)

    cached = _cache_get(cache_key, ttl)
    if cached is not None:
        return cached

    url = f"{_BASE_URL}/{path}"
    try:
        resp = requests.get(url, params=params, timeout=_DEFAULT_TIMEOUT)
        if resp.status_code == 429:
            raise CoinGeckoError("CoinGecko rate limit (429) — try again in a moment")
        if resp.status_code == 404:
            raise CoinGeckoError(f"CoinGecko: resource not found — {path}")
        resp.raise_for_status()
        payload = resp.json()
    except requests.RequestException as exc:
        raise CoinGeckoError(f"CoinGecko transport error ({path}): {exc}") from exc
    except ValueError as exc:
        raise CoinGeckoError(f"CoinGecko bad JSON ({path}): {exc}") from exc

    _cache_set(cache_key, payload)
    return payload


def _symbol_to_id(symbol: str) -> str:
    """Convert a ticker symbol (e.g. 'BTC') to a CoinGecko coin ID.

    Uses the hardcoded map first (free, instant). Falls back to the /search
    endpoint for unknown symbols — result is cached 24 h.
    """
    sym = symbol.strip().upper()
    mapped = _SYMBOL_TO_ID.get(sym)
    if mapped:
        return mapped

    try:
        result = _request("search", {"query": sym})
        coins = result.get("coins") or []
        for coin in coins:
            if (coin.get("symbol") or "").upper() == sym:
                coin_id = str(coin["id"])
                _SYMBOL_TO_ID[sym] = coin_id  # warm the cache
                return coin_id
        if coins:
            coin_id = str(coins[0]["id"])
            _SYMBOL_TO_ID[sym] = coin_id
            return coin_id
    except CoinGeckoError as exc:
        log.warning("CoinGecko symbol search failed for %s: %s", sym, exc)

    return sym.lower()


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


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def coin_market_data(
    symbols: list[str],
    currency: str = "usd",
) -> list[dict[str, Any]]:
    """Price + market data for a specific list of symbols.

    Converts symbols → CoinGecko IDs, then calls /coins/markets.
    Returns a list of normalised dicts, one per coin found.
    """
    ids = [_symbol_to_id(s) for s in symbols]
    data: list[dict[str, Any]] = _request(
        "coins/markets",
        {
            "vs_currency": currency,
            "ids": ",".join(ids),
            "order": "market_cap_desc",
            "per_page": min(len(ids) + 10, 250),
            "page": 1,
            "sparkline": "false",
            "price_change_percentage": "24h",
        },
    )
    return [_normalise_market_row(item, currency) for item in (data or [])]


def coin_price(symbol: str, currency: str = "usd") -> dict[str, Any]:
    """Single-coin price quote.  Returns same shape as coin_market_data rows."""
    rows = coin_market_data([symbol], currency=currency)
    if not rows:
        raise CoinGeckoError(f"No market data for '{symbol}' from CoinGecko")
    return rows[0]


def top_coins(
    limit: int = 10,
    currency: str = "usd",
    *,
    exclude_stablecoins: bool = True,
) -> list[dict[str, Any]]:
    """Top N coins by market cap.

    Fetches up to 50 from CoinGecko and filters stablecoins if requested,
    then trims to ``limit``.
    """
    data: list[dict[str, Any]] = _request(
        "coins/markets",
        {
            "vs_currency": currency,
            "order": "market_cap_desc",
            "per_page": 50,
            "page": 1,
            "sparkline": "false",
            "price_change_percentage": "24h",
        },
    )
    rows: list[dict[str, Any]] = []
    for item in data or []:
        sym = (item.get("symbol") or "").upper()
        if exclude_stablecoins and sym in _STABLECOINS:
            continue
        rows.append(_normalise_market_row(item, currency))
        if len(rows) >= limit:
            break
    return rows


def trending_coins() -> list[dict[str, Any]]:
    """Top-7 trending coins from CoinGecko search trends.

    Trending is based on search volume over the last 24 h — a good
    proxy for social/market interest without requiring an API key.
    """
    data = _request("search/trending")
    items = data.get("coins") or []
    out: list[dict[str, Any]] = []
    for item in items:
        coin = item.get("item") or {}
        sym = (coin.get("symbol") or "").upper()
        # Try to enrich with price from the coin data block (CG includes it
        # in newer API versions under item.data).
        coin_data = coin.get("data") or {}
        price_raw = coin_data.get("price")
        price = _to_float(price_raw)
        cap = coin_data.get("market_cap") or coin_data.get("market_cap_btc")
        out.append({
            "id": coin.get("id"),
            "name": coin.get("name"),
            "symbol": sym,
            "rank": coin.get("market_cap_rank"),
            "price_usd": price,
            "market_cap": cap,
            "score": coin.get("score"),  # 0 = most trending
        })
    return out


def global_market() -> dict[str, Any]:
    """Global crypto market statistics."""
    data = _request("global")
    d = data.get("data") or {}
    caps = d.get("market_cap_percentage") or {}
    return {
        "total_market_cap_usd": (d.get("total_market_cap") or {}).get("usd"),
        "total_volume_24h_usd": (d.get("total_volume") or {}).get("usd"),
        "btc_dominance_pct": _to_float(caps.get("btc")),
        "eth_dominance_pct": _to_float(caps.get("eth")),
        "market_cap_change_pct_24h": _to_float(d.get("market_cap_change_percentage_24h_usd")),
        "active_cryptocurrencies": d.get("active_cryptocurrencies"),
        "markets": d.get("markets"),
    }


def ohlcv(coin_id: str, vs_currency: str = "usd", days: int = 7) -> list[dict[str, Any]]:
    """OHLCV candlesticks for a coin. ``coin_id`` is the CoinGecko ID.

    Candle granularity is set automatically by CoinGecko based on ``days``
    (1d → hourly, ≤90d → 4-hourly, >90d → daily).
    """
    data: list[list] = _request(
        f"coins/{coin_id}/ohlc",
        {"vs_currency": vs_currency, "days": str(days)},
    )
    rows: list[dict[str, Any]] = []
    for item in data or []:
        if len(item) >= 5:
            rows.append({
                "timestamp": item[0],
                "open": item[1],
                "high": item[2],
                "low": item[3],
                "close": item[4],
            })
    rows.sort(key=lambda r: r["timestamp"], reverse=True)
    return rows


def coin_history(symbol: str, days: int = 365, vs_currency: str = "usd") -> list[dict[str, Any]]:
    """Daily close history for a coin via CoinGecko ``market_chart``.

    Returns newest-first list of ``{date, close}`` dicts. ``days`` >=90 yields
    daily granularity; values up to 365 are supported on the free tier.
    """
    coin_id = _symbol_to_id(symbol)
    data = _request(
        f"coins/{coin_id}/market_chart",
        {"vs_currency": vs_currency, "days": str(days), "interval": "daily"},
    )
    from datetime import datetime, timezone  # noqa: PLC0415
    prices: list[list] = data.get("prices") or []
    rows: list[dict[str, Any]] = []
    for ts_ms, price in prices:
        try:
            dt = datetime.fromtimestamp(int(ts_ms) / 1000, tz=timezone.utc)
            rows.append({"date": dt.strftime("%Y-%m-%d"), "close": float(price)})
        except (TypeError, ValueError):
            continue
    rows.sort(key=lambda r: r["date"], reverse=True)
    return rows


def search_coins(query: str) -> list[dict[str, Any]]:
    """Search CoinGecko for coins matching ``query``. Returns up to 10 hits."""
    data = _request("search", {"query": query})
    coins = data.get("coins") or []
    return [
        {
            "id": c.get("id"),
            "symbol": (c.get("symbol") or "").upper(),
            "name": c.get("name"),
            "rank": c.get("market_cap_rank"),
        }
        for c in coins[:10]
    ]


# ---------------------------------------------------------------------------
# Internal normaliser
# ---------------------------------------------------------------------------


def _normalise_market_row(item: dict[str, Any], currency: str) -> dict[str, Any]:
    price = _to_float(item.get("current_price"))
    change_24h = _to_float(item.get("price_change_percentage_24h"))
    prev = (
        price / (1.0 + change_24h / 100.0)
        if price is not None and change_24h is not None
        else price
    )
    return {
        "id": item.get("id"),
        "symbol": (item.get("symbol") or "").upper(),
        "name": item.get("name"),
        "price": price,
        "previous_close": prev,
        "change_pct_24h": round(change_24h, 4) if change_24h is not None else None,
        "market_cap": item.get("market_cap"),
        "volume_24h": item.get("total_volume"),
        "rank": item.get("market_cap_rank"),
        "currency": currency.upper(),
        "last_updated": item.get("last_updated"),
        "source": "coingecko",
    }
