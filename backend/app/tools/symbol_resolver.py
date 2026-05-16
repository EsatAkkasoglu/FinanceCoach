"""Friendly-name → ticker resolver.

Resolution order
────────────────
1. Curated aliases  — only for genuinely non-obvious mappings where the
   ticker format itself would be opaque to the agent (^GSPC, USDTRY=X,
   GLD as gold proxy, ^TNX for yields, BTC-USD suffix, etc.).
   Company names are NOT curated here — "Apple" → AAPL is obvious enough
   for the search APIs to handle.

2. Alpha Vantage SYMBOL_SEARCH  — handles US equities, ETFs, and ADRs by
   company name or partial ticker. Best match is returned, US region
   preferred.

3. CoinGecko search  — fallback for crypto queries that AV doesn't index
   (SOL, AVAX, PEPE, …). Appends "-USD" to form the get_quote ticker.

4. Failure  — clear message so the agent can tell the user to use the
   literal ticker.
"""
from __future__ import annotations

import logging
from typing import Any

from langchain_core.tools import tool

import app.services.coingecko as cg
from app.services import alpha_vantage as av
from app.services.alpha_vantage import AlphaVantageError
from app.services.coingecko import CoinGeckoError

log = logging.getLogger("fincoach.tools.resolver")

# ---------------------------------------------------------------------------
# Curated aliases — ONLY for non-obvious format mappings.
# Rule: if a reasonable person would know the ticker already, it does NOT
# belong here. If the ticker format (^, =X, -USD, ETF proxy) is the only
# challenge, it belongs here.
# ---------------------------------------------------------------------------
_TABLE: dict[str, tuple[str, str, str]] = {
    # Commodities → liquid ETF proxies (AV has no direct commodity endpoint)
    "gold": ("GLD", "SPDR Gold Shares ETF (gold price proxy)", "commodity_etf"),
    "silver": ("SLV", "iShares Silver Trust ETF", "commodity_etf"),
    "oil": ("USO", "United States Oil Fund (WTI proxy)", "commodity_etf"),
    "wti": ("USO", "United States Oil Fund (WTI proxy)", "commodity_etf"),
    "brent": ("BNO", "United States Brent Oil Fund", "commodity_etf"),
    "natural gas": ("UNG", "United States Natural Gas Fund", "commodity_etf"),
    "copper": ("CPER", "United States Copper Index Fund", "commodity_etf"),
    "platinum": ("PPLT", "abrdn Physical Platinum Shares ETF", "commodity_etf"),
    "uranium": ("URA", "Global X Uranium ETF", "commodity_etf"),

    # Commodity futures (continuous contract — yfinance style)
    "gold futures": ("GC=F", "Gold Futures (continuous)", "future"),
    "silver futures": ("SI=F", "Silver Futures (continuous)", "future"),
    "oil futures": ("CL=F", "Crude Oil Futures (continuous)", "future"),

    # Major indices — ^ prefix required by AV
    "s&p 500": ("^GSPC", "S&P 500 Index", "index"),
    "sp500": ("^GSPC", "S&P 500 Index", "index"),
    "spx": ("^GSPC", "S&P 500 Index", "index"),
    "nasdaq": ("^IXIC", "NASDAQ Composite Index", "index"),
    "nasdaq 100": ("^NDX", "NASDAQ-100 Index", "index"),
    "ndx": ("^NDX", "NASDAQ-100 Index", "index"),
    "dow": ("^DJI", "Dow Jones Industrial Average", "index"),
    "dow jones": ("^DJI", "Dow Jones Industrial Average", "index"),
    "russell 2000": ("^RUT", "Russell 2000 Small-Cap Index", "index"),
    "vix": ("^VIX", "CBOE Volatility Index", "index"),
    "volatility index": ("^VIX", "CBOE Volatility Index", "index"),
    "ftse": ("^FTSE", "FTSE 100 Index", "index"),
    "nikkei": ("^N225", "Nikkei 225 Index", "index"),
    "dax": ("^GDAXI", "DAX Performance Index", "index"),
    "bist 100": ("XU100.IS", "Borsa Istanbul 100 Index", "index"),
    "bist": ("XU100.IS", "Borsa Istanbul 100 Index", "index"),
    "borsa istanbul": ("XU100.IS", "Borsa Istanbul 100 Index", "index"),

    # Treasury yields — ^ prefix + maturity code
    "10 year treasury": ("^TNX", "US 10-Year Treasury Yield", "bond_yield"),
    "10y treasury": ("^TNX", "US 10-Year Treasury Yield", "bond_yield"),
    "10y": ("^TNX", "US 10-Year Treasury Yield", "bond_yield"),
    "30 year treasury": ("^TYX", "US 30-Year Treasury Yield", "bond_yield"),
    "30y treasury": ("^TYX", "US 30-Year Treasury Yield", "bond_yield"),
    "2 year treasury": ("^IRX", "US 13-Week Treasury Yield (short proxy)", "bond_yield"),

    # Forex — =X suffix required by AV
    "eur usd": ("EURUSD=X", "EUR/USD", "forex"),
    "eur/usd": ("EURUSD=X", "EUR/USD", "forex"),
    "eurusd": ("EURUSD=X", "EUR/USD", "forex"),
    "gbp usd": ("GBPUSD=X", "GBP/USD", "forex"),
    "gbp/usd": ("GBPUSD=X", "GBP/USD", "forex"),
    "gbpusd": ("GBPUSD=X", "GBP/USD", "forex"),
    "usd jpy": ("USDJPY=X", "USD/JPY", "forex"),
    "usd/jpy": ("USDJPY=X", "USD/JPY", "forex"),
    "usdjpy": ("USDJPY=X", "USD/JPY", "forex"),
    "usd try": ("USDTRY=X", "USD/TRY", "forex"),
    "usd/try": ("USDTRY=X", "USD/TRY", "forex"),
    "usdtry": ("USDTRY=X", "USD/TRY", "forex"),
    "dollar lira": ("USDTRY=X", "USD/TRY", "forex"),
    "dolar lira": ("USDTRY=X", "USD/TRY", "forex"),
    "lira": ("USDTRY=X", "USD/TRY (Turkish lira)", "forex"),
    "dxy": ("DX-Y.NYB", "US Dollar Index", "forex"),
    "dollar index": ("DX-Y.NYB", "US Dollar Index", "forex"),
}

# Keywords that indicate the user is asking about a cryptocurrency.
# Used to route the search to CoinGecko before AV.
_CRYPTO_HINTS = frozenset(
    {"coin", "token", "crypto", "kripto", "blockchain", "defi", "nft", "web3"}
)


def _looks_like_crypto(query: str) -> bool:
    q = query.lower()
    return any(h in q for h in _CRYPTO_HINTS)


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------


@tool
def resolve_symbol(name: str) -> dict[str, Any]:
    """Map any asset name to a ticker accepted by ``get_quote``.

    Handles: company names ("Microsoft", "Nvidia"), index names ("S&P 500",
    "Nikkei"), commodity names ("gold", "oil"), crypto names ("Bitcoin",
    "Solana"), forex pairs ("USD/TRY"), and ETF/fund names.

    Always call this BEFORE ``get_quote`` when the user mentions an asset
    by name instead of ticker.

    Returns:
        {input, ticker, description, asset_class, source}  on success
        {input, ticker: null, suggestion}                   on failure
    """
    key = (name or "").lower().strip().rstrip("?.!")

    # 1 ── Curated aliases (format-sensitive mappings only)
    if key in _TABLE:
        ticker, desc, asset_class = _TABLE[key]
        return {"input": name, "ticker": ticker, "description": desc,
                "asset_class": asset_class, "source": "curated"}

    for phrase, (ticker, desc, asset_class) in _TABLE.items():
        if phrase in key:
            return {"input": name, "ticker": ticker, "description": desc,
                    "asset_class": asset_class, "source": "curated_partial",
                    "matched_phrase": phrase}

    is_crypto = _looks_like_crypto(key)

    if is_crypto:
        # Explicit crypto query → CoinGecko is the right source; AV doesn't index altcoins.
        result = _try_coingecko(name, key)
        if result:
            return result
    else:
        # 2a ── Pre-check CoinGecko for top-30 coins by exact name match.
        #       This catches "Bitcoin", "Solana", "Ethereum" etc. even without
        #       explicit crypto keywords, while rejecting obscure tokens that
        #       share a name with a stock (e.g. "Apple" → some rank-5000 token).
        result = _try_coingecko(name, key, max_rank=30, require_exact_name=True)
        if result:
            return result

        # 2b ── Alpha Vantage SYMBOL_SEARCH for US equities / ETFs / ADRs.
        av_result = _try_av_search(name)
        if av_result:
            return av_result

        # 2c ── Broader CoinGecko fallback (rank < 200) when AV found nothing.
        result = _try_coingecko(name, key, max_rank=200)
        if result:
            return result

    return {
        "input": name,
        "ticker": None,
        "suggestion": (
            f"Could not resolve '{name}'. "
            "Use the exact ticker symbol instead "
            "(e.g. AAPL for Apple, BTC-USD for Bitcoin, EURUSD=X for EUR/USD)."
        ),
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _try_av_search(name: str) -> dict[str, Any] | None:
    """Call AV SYMBOL_SEARCH; return normalised result or None."""
    try:
        matches = av.symbol_search(name)
    except AlphaVantageError as exc:
        log.info("AV SYMBOL_SEARCH error for %r: %s", name, exc)
        return None  # rate-limit or network — don't cascade to CoinGecko

    us = [m for m in matches if (m.get("region") or "").lower() == "united states"]
    best = (us or matches)[0] if (us or matches) else None
    if not best or not best.get("symbol"):
        return None
    return {
        "input": name,
        "ticker": str(best["symbol"]).upper(),
        "description": best.get("name") or best["symbol"],
        "asset_class": (best.get("type") or "stock").lower(),
        "source": "alpha_vantage_search",
        "match_score": best.get("match_score"),
    }


def _try_coingecko(
    original: str,
    key: str,
    max_rank: int | None = None,
    require_exact_name: bool = False,
) -> dict[str, Any] | None:
    """Search CoinGecko; return normalised result or None.

    max_rank: reject coins ranked below this threshold (higher number = less strict).
    require_exact_name: only accept a hit if the coin's name matches exactly (case-insensitive).
    """
    try:
        hits = cg.search_coins(key)
    except CoinGeckoError as exc:
        log.info("CoinGecko search failed for %r: %s", original, exc)
        return None

    if not hits:
        return None

    # Prefer exact name match (case-insensitive), then exact symbol, then first hit.
    exact_name = next((h for h in hits if (h.get("name") or "").lower() == key), None)
    exact_sym = next(
        (h for h in hits if (h.get("symbol") or "").upper() == key.upper()), None
    )
    best = exact_name or exact_sym or (None if require_exact_name else hits[0])

    if best is None:
        return None

    rank = best.get("rank")
    if max_rank is not None and rank is not None and rank > max_rank:
        log.debug(
            "CoinGecko best for %r is rank %s > max %s — skipping",
            original, rank, max_rank,
        )
        return None

    symbol = (best.get("symbol") or "").upper()
    if not symbol:
        return None

    ticker = f"{symbol}-USD"
    return {
        "input": original,
        "ticker": ticker,
        "description": best.get("name") or ticker,
        "asset_class": "crypto",
        "source": "coingecko_search",
        "rank": rank,
    }


@tool
def list_supported_categories() -> dict[str, list[str]]:
    """Return the asset categories this agent can price. Useful when the
    user asks 'what can you look up?'."""
    by_class: dict[str, list[str]] = {}
    for phrase, (_ticker, _desc, asset_class) in _TABLE.items():
        by_class.setdefault(asset_class, []).append(phrase)
    by_class["us_stock"] = [
        "any company name (e.g. 'Apple', 'Tesla') or US ticker (AAPL, NVDA, TSLA)",
    ]
    by_class["crypto"] = [
        "any crypto name (e.g. 'Bitcoin', 'Solana') or -USD pair (BTC-USD, ETH-USD)",
    ]
    by_class["turkish_fund"] = ["3-letter TEFAS codes (AFA, IIH, TI2, …)"]
    return by_class
