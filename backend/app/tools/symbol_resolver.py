"""Friendly-name → yfinance ticker resolver.

When a user asks "what's the price of gold?" the agent can't pass the word
"gold" to yfinance. This module curates a table of common asset names and
maps them to a yfinance-compatible symbol. The agent calls ``resolve_symbol``
BEFORE ``get_quote`` whenever the user mentions an asset by name.

Categories covered:
- Commodities (ETF proxies — futures often have stale free-tier data)
- Major indices
- Treasury yields
- Forex pairs (incl. USDTRY)
- Popular ETFs / index funds
"""
from __future__ import annotations

from typing import Any

from langchain_core.tools import tool


# Each entry: lowercase phrase → (yfinance_ticker, human description, asset_class)
_TABLE: dict[str, tuple[str, str, str]] = {
    # --- Commodities (via liquid ETFs) ---
    "gold": ("GLD", "SPDR Gold Shares ETF (gold price proxy)", "commodity_etf"),
    "silver": ("SLV", "iShares Silver Trust ETF", "commodity_etf"),
    "oil": ("USO", "United States Oil Fund (WTI proxy)", "commodity_etf"),
    "wti": ("USO", "United States Oil Fund (WTI proxy)", "commodity_etf"),
    "brent": ("BNO", "United States Brent Oil Fund", "commodity_etf"),
    "natural gas": ("UNG", "United States Natural Gas Fund", "commodity_etf"),
    "copper": ("CPER", "United States Copper Index Fund", "commodity_etf"),
    "platinum": ("PPLT", "abrdn Physical Platinum Shares ETF", "commodity_etf"),
    "uranium": ("URA", "Global X Uranium ETF", "commodity_etf"),

    # --- Commodity futures (continuous contract) ---
    "gold futures": ("GC=F", "Gold Futures (continuous)", "future"),
    "silver futures": ("SI=F", "Silver Futures (continuous)", "future"),
    "oil futures": ("CL=F", "Crude Oil Futures (continuous)", "future"),

    # --- Major indices ---
    "s&p 500": ("^GSPC", "S&P 500 Index", "index"),
    "sp500": ("^GSPC", "S&P 500 Index", "index"),
    "spx": ("^GSPC", "S&P 500 Index", "index"),
    "nasdaq": ("^IXIC", "NASDAQ Composite Index", "index"),
    "nasdaq 100": ("^NDX", "NASDAQ-100 Index", "index"),
    "dow": ("^DJI", "Dow Jones Industrial Average", "index"),
    "dow jones": ("^DJI", "Dow Jones Industrial Average", "index"),
    "russell 2000": ("^RUT", "Russell 2000 Small-Cap Index", "index"),
    "vix": ("^VIX", "CBOE Volatility Index", "index"),
    "ftse": ("^FTSE", "FTSE 100 Index", "index"),
    "nikkei": ("^N225", "Nikkei 225 Index", "index"),
    "dax": ("^GDAXI", "DAX Performance Index", "index"),
    "bist 100": ("XU100.IS", "Borsa Istanbul 100 Index", "index"),
    "bist": ("XU100.IS", "Borsa Istanbul 100 Index", "index"),

    # --- Bond yields ---
    "10 year treasury": ("^TNX", "US 10-Year Treasury Yield", "bond_yield"),
    "10y treasury": ("^TNX", "US 10-Year Treasury Yield", "bond_yield"),
    "10y": ("^TNX", "US 10-Year Treasury Yield", "bond_yield"),
    "30 year treasury": ("^TYX", "US 30-Year Treasury Yield", "bond_yield"),
    "30y treasury": ("^TYX", "US 30-Year Treasury Yield", "bond_yield"),
    "2 year treasury": ("^IRX", "US 13-Week Treasury Yield (short proxy)", "bond_yield"),

    # --- Forex (USD pairs) ---
    "eur usd": ("EURUSD=X", "EUR/USD", "forex"),
    "eur/usd": ("EURUSD=X", "EUR/USD", "forex"),
    "gbp usd": ("GBPUSD=X", "GBP/USD", "forex"),
    "gbp/usd": ("GBPUSD=X", "GBP/USD", "forex"),
    "usd jpy": ("USDJPY=X", "USD/JPY", "forex"),
    "usd/jpy": ("USDJPY=X", "USD/JPY", "forex"),
    "usd try": ("USDTRY=X", "USD/TRY", "forex"),
    "usd/try": ("USDTRY=X", "USD/TRY", "forex"),
    "dollar lira": ("USDTRY=X", "USD/TRY", "forex"),
    "lira": ("USDTRY=X", "USD/TRY", "forex"),
    "dxy": ("DX-Y.NYB", "US Dollar Index", "forex"),

    # --- Popular index funds / ETFs ---
    "spy": ("SPY", "SPDR S&P 500 ETF", "etf"),
    "voo": ("VOO", "Vanguard S&P 500 ETF", "etf"),
    "qqq": ("QQQ", "Invesco QQQ (NASDAQ-100)", "etf"),
    "vti": ("VTI", "Vanguard Total Stock Market ETF", "etf"),
    "vxus": ("VXUS", "Vanguard Total International Stock ETF", "etf"),
    "bnd": ("BND", "Vanguard Total Bond Market ETF", "etf"),
    "agg": ("AGG", "iShares Core US Aggregate Bond ETF", "etf"),
    "tlt": ("TLT", "iShares 20+ Year Treasury Bond ETF", "etf"),
    "iwm": ("IWM", "iShares Russell 2000 ETF", "etf"),
    "eem": ("EEM", "iShares MSCI Emerging Markets ETF", "etf"),
    "ark": ("ARKK", "ARK Innovation ETF", "etf"),
    "arkk": ("ARKK", "ARK Innovation ETF", "etf"),
    "soxx": ("SOXX", "iShares Semiconductor ETF", "etf"),
    "smh": ("SMH", "VanEck Semiconductor ETF", "etf"),
}


@tool
def resolve_symbol(name: str) -> dict[str, Any]:
    """Map a common asset name (like 'gold', 'S&P 500', 'oil', 'usd/try') to
    a yfinance-compatible ticker. ALWAYS call this FIRST when the user
    mentions an asset by name rather than ticker. Then pass the resolved
    ticker to get_quote.

    Returns:
        {input, ticker, description, asset_class, source} on hit
        {input, ticker: null, suggestion} when nothing matches
    """
    key = name.lower().strip().rstrip("?.!")
    # Try direct match
    if key in _TABLE:
        ticker, desc, asset_class = _TABLE[key]
        return {
            "input": name,
            "ticker": ticker,
            "description": desc,
            "asset_class": asset_class,
            "source": "curated",
        }
    # Try contains match (e.g. "the gold price")
    for phrase, (ticker, desc, asset_class) in _TABLE.items():
        if phrase in key:
            return {
                "input": name,
                "ticker": ticker,
                "description": desc,
                "asset_class": asset_class,
                "source": "curated_partial",
                "matched_phrase": phrase,
            }
    return {
        "input": name,
        "ticker": None,
        "suggestion": (
            "Not in curated list. If it looks like a US stock or crypto, try "
            "the literal ticker (AAPL, BTC-USD). Otherwise tell the user it's "
            "not supported in this prototype."
        ),
    }


@tool
def list_supported_categories() -> dict[str, list[str]]:
    """Return the asset categories this agent can price. Useful when the
    user asks 'what can you look up?'."""
    by_class: dict[str, list[str]] = {}
    for phrase, (_ticker, _desc, asset_class) in _TABLE.items():
        by_class.setdefault(asset_class, []).append(phrase)
    by_class["us_stock"] = ["any US ticker — e.g. AAPL, NVDA, TSLA"]
    by_class["crypto"] = ["any -USD pair — e.g. BTC-USD, ETH-USD, SOL-USD"]
    return by_class
