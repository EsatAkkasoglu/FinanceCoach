"""Market Data agent — live prices, technicals, 8-dim analysis.

Covers: US stocks, crypto, ETFs, indices, commodities (via ETF proxies),
forex, Treasury yields, futures. For named assets the agent resolves the
yfinance ticker first via ``resolve_symbol``.
"""
from __future__ import annotations

import re
from typing import Any

import requests
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.prebuilt import create_react_agent

from app.agents.llm import get_llm
from app.agents.state import AgentState
from app.agents._helpers import extract_tool_calls
from app.tools.market_tools import (
    get_quote,
    analyze_ticker_8dim,
    get_dividend_metrics,
    scan_hot_trends,
    scan_rumors,
)
from app.tools.symbol_resolver import resolve_symbol, list_supported_categories
from app.tools.fund_tools import (
    get_fund_quote,
    get_fund_history,
    search_fund,
    list_top_funds,
)

SYSTEM_PROMPT_BASE = """You are the Market Data specialist for FinCoach.

ABSOLUTE RULE — TOOLS ONLY:
  • NEVER state a price, change %, volume, dividend, or technical value from
    memory or training data. Those values change daily and your knowledge is
    stale by definition.
  • Every numeric answer MUST come from a tool call (get_quote, get_fund_quote,
    analyze_ticker_8dim, get_dividend_metrics, etc.) in THIS turn.
  • If a tool fails or returns no data, say so plainly — do NOT fall back to
    a remembered number.

STRICT SCOPE — you ONLY answer about:
  • Live prices, historical performance, technical analysis
  • 8-dimension stock analysis, dividend metrics
  • Asset trends (hot scanner) and price-grounded buy/sell reasoning
  • Fund performance (US ETFs and Turkish TEFAS funds)

YOU DO NOT cover any of these — another specialist will:
  • Whether the user OWNS an asset → portfolio specialist
  • Latest news headlines or rumors → news_sentiment specialist
  • The user's spending or budget → budget_coach specialist
  • The user's risk profile → risk_profiler specialist

If the user's question has parts outside your scope, ANSWER ONLY THE MARKET-DATA PART.
Do not check ownership, summarize news, or comment on personal finances — the
supervisor will route those parts to the right specialist.

You can fetch live prices for ANY of these asset classes — never refuse a
query because of asset class alone:

GLOBAL (via yfinance):
- US stocks & ADRs            (AAPL, NVDA, BABA, …)
- Crypto                      (-USD suffix: BTC-USD, ETH-USD, SOL-USD)
- ETFs / index funds          (SPY, QQQ, VTI, BND, VOO, ARKK)
- Stock indices               (^GSPC = S&P 500, ^IXIC = NASDAQ, ^VIX, ^DJI, XU100.IS for BIST)
- Commodities (via ETFs)      (GLD = gold, SLV = silver, USO = oil, UNG = nat gas, CPER = copper)
- Commodity futures           (GC=F gold, CL=F crude, SI=F silver)
- Forex                       (EURUSD=X, USDTRY=X, GBPUSD=X, DX-Y.NYB for DXY)
- Treasury yields             (^TNX = 10Y, ^TYX = 30Y)

TURKISH MUTUAL & PENSION FUNDS (via TEFAS):
- 3-letter fund codes         (AFA, IIH, TI2, NVT, AU1, …)
- NAVs publish once per business day in TRY
- Categories: equity / gold / bond / FX / mixed / money market / pension

WORKFLOW (decision tree):
1. If the user gives a TEFAS fund CODE (3 uppercase letters or one already in
   the 'AAA' format), call ``get_fund_quote(code)`` directly.
2. If the user gives a Turkish fund NAME or theme (e.g. "altın fonu",
   "İş Bankası hisse fonu", "kısa vadeli borçlanma"), call ``search_fund``
   first to find candidate codes, then ``get_fund_quote`` on the best match.
3. If the user mentions a global asset BY NAME (gold, S&P 500, USD/TRY),
   call ``resolve_symbol`` first → then ``get_quote(ticker)``.
4. Plain US ticker / crypto / ETF → ``get_quote(ticker)`` directly.
5. ``analyze_ticker_8dim`` — only for US stocks / crypto, not indices/forex/futures/funds.
6. ``get_dividend_metrics`` — stocks and ETFs only.
7. ``scan_hot_trends`` / ``scan_rumors`` — what's trending / early signals (US-focused).
8. ``list_top_funds`` — Turkish fund leaderboard by category rank.
9. ``list_supported_categories`` — meta-question 'what can you look up?'

DISAMBIGUATION:
- A 3-letter all-caps code in a Turkish-language query → likely a TEFAS fund
- A 3-4 letter all-caps in an English query → likely a US ticker
- When unsure, call BOTH (search_fund + resolve_symbol) and let the response shape itself.
- If ``resolve_symbol`` returns ``ticker: null`` AND ``search_fund`` returns
  empty, tell the user it's not supported.

CITATIONS: every numeric claim is tagged with its source (yfinance, TEFAS,
8-dim analysis, NewsAPI). Two short paragraphs max."""

RISK_GUIDANCE = {
    "conservative": """
RISK PROFILE: Conservative (0-50 score)
RECOMMENDED ASSET CLASSES (prioritize in this order):
- Blue-chip US stocks: AAPL, MSFT, JNJ, PG (low volatility, strong dividends)
- Dividend-focused ETFs: VOY, VYM, SCHD (high dividend yield, stability)
- Bond ETFs: BND, AGG, IEF (investment-grade bonds)
- Defensive sectors: Utilities (XLU), Healthcare (XLV), Consumer Staples (XLP)
- Turkish bond funds: stable government and corporate bonds

ANALYSIS PRIORITIES (for each stock):
- Dividend yield (emphasize consistent payers)
- P/E ratio (lower = more stable)
- Debt/equity ratio (lower is better)
- 52-week volatility (avoid high-volatility names)

AVOID: crypto, small-cap growth, emerging markets, speculative options""",
    "balanced": """
RISK PROFILE: Balanced (51-90 score)
RECOMMENDED ASSET CLASSES (balanced mix):
- Growth + Value stocks: Mix of AAPL, NVDA, MSFT with TSM, GIS
- Diversified ETFs: VOO, VTI (broad market), QQQ (tech-heavy but quality)
- Bond ETFs: BND, VBTLX (40-60% stock allocation)
- Sector rotation: Include 2-3 sector ETFs for diversification
- Turkish equity + bond funds: Mixed balanced portfolios

ANALYSIS PRIORITIES (for each stock):
- Growth rate vs. P/E ratio (balance both)
- Dividend yield + capital appreciation potential
- Sector exposure (ensure diversity)
- 52-week performance trend

SUGGESTIONS: Rebalance when single asset class drifts >20% from target""",
    "aggressive": """
RISK PROFILE: Aggressive (91-125 score)
RECOMMENDED ASSET CLASSES (growth-focused):
- Growth stocks: NVDA, AAPL (tech), TSLA, AMZN (disruptive)
- Small-cap / micro-cap growth: QQQ, XLV sector rotation, emerging leaders
- Crypto & alternative assets: BTC-USD, ETH-USD for diversification
- High-growth sector ETFs: XLK (tech), FTEC (fintech), URTH (emerging markets)
- Turkish small-cap / growth funds: Higher yield potential

ANALYSIS PRIORITIES (for each stock):
- Revenue growth rate (prioritize rapid growth)
- Profit margin trajectory (expansion is key)
- Volatility & momentum (OK with higher 52-week swing)
- Market share gains in high-growth sectors

SUGGESTIONS: Consider concentrated positions in high-conviction growth bets""",
}


def _build_prompt(risk_profile: str = "balanced") -> str:
    """Build risk-aware system prompt based on user's risk profile."""
    risk_guidance = RISK_GUIDANCE.get(risk_profile, RISK_GUIDANCE["balanced"])
    return SYSTEM_PROMPT_BASE + "\n" + risk_guidance


_TOOLS = [
    resolve_symbol,
    list_supported_categories,
    get_quote,
    analyze_ticker_8dim,
    get_dividend_metrics,
    scan_hot_trends,
    scan_rumors,
    # TEFAS Turkish funds
    search_fund,
    get_fund_quote,
    get_fund_history,
    list_top_funds,
]

_STABLECOIN_SYMBOLS = {"USDT", "USDC", "DAI", "FDUSD", "USDE", "TUSD", "BUSD"}


def _latest_user_text(state: AgentState) -> str:
    for message in reversed(state.get("messages", []) or []):
        if isinstance(message, HumanMessage):
            content = message.content
            return content if isinstance(content, str) else str(content)
    return ""


def _wants_top_crypto_market_cap(text: str) -> bool:
    text_l = text.lower()
    return (
        ("crypto" in text_l or "kripto" in text_l)
        and ("market cap" in text_l or "market hac" in text_l or "piyasa değ" in text_l)
        and ("top" in text_l or "ilk" in text_l or "en yüksek" in text_l)
    )


def _requested_limit(text: str, default: int = 5) -> int:
    match = re.search(r"\b(?:top|ilk)?\s*(\d{1,2})\b", text.lower())
    if not match:
        return default
    return max(1, min(10, int(match.group(1))))


def _fetch_top_crypto_tickers(limit: int) -> list[dict[str, Any]]:
    url = (
        "https://api.coingecko.com/api/v3/coins/markets"
        "?vs_currency=usd&order=market_cap_desc&per_page=30&page=1"
    )
    response = requests.get(url, timeout=8)
    response.raise_for_status()

    rows: list[dict[str, Any]] = []
    for item in response.json():
        symbol = str(item.get("symbol") or "").upper()
        if not symbol or symbol in _STABLECOIN_SYMBOLS:
            continue
        rows.append(
            {
                "ticker": f"{symbol}-USD",
                "name": item.get("name") or symbol,
                "market_cap": item.get("market_cap"),
                "rank": item.get("market_cap_rank"),
            }
        )
        if len(rows) >= limit:
            break
    return rows


def _fmt_money(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "n/a"
    if number >= 1_000_000_000:
        return f"${number / 1_000_000_000:.1f}B"
    if number >= 1_000_000:
        return f"${number / 1_000_000:.1f}M"
    return f"${number:,.2f}"


def _handle_top_crypto_request(state: AgentState) -> AgentState | None:
    user_text = _latest_user_text(state)
    if not _wants_top_crypto_market_cap(user_text):
        return None

    limit = _requested_limit(user_text, default=5)
    try:
        coins = _fetch_top_crypto_tickers(limit)
    except Exception as exc:  # noqa: BLE001
        return {
            "messages": [AIMessage(content=f"Top kripto listesi CoinGecko'dan alınamadı: {exc}")],
            "citations": [],
        }

    lines = [
        f"Piyasa değerine göre ilk {len(coins)} kripto için stablecoinleri hariç tuttum; 8-dim skor stablecoinlerde anlamlı değil.",
        "",
        "| Kripto | Fiyat | 24s değişim | Market cap | 8-dim skor | Öneri |",
        "|---|---:|---:|---:|---:|---|",
    ]
    citations: list[dict[str, Any]] = []

    for coin in coins:
        ticker = str(coin["ticker"])
        quote = get_quote.invoke({"ticker": ticker})
        analysis = analyze_ticker_8dim.invoke({"ticker": ticker, "fast": True})

        price = quote.get("price") if isinstance(quote, dict) else None
        change = quote.get("change_pct") if isinstance(quote, dict) else None
        score = analysis.get("final_score") if isinstance(analysis, dict) else None
        recommendation = analysis.get("recommendation") if isinstance(analysis, dict) else None
        error = analysis.get("error") if isinstance(analysis, dict) else None

        score_text = f"{float(score):.2f}" if isinstance(score, int | float) else "n/a"
        recommendation_text = str(recommendation or ("hata" if error else "n/a"))
        price_text = f"${float(price):,.4f}" if isinstance(price, int | float) else "n/a"
        change_text = f"{float(change):+.2f}%" if isinstance(change, int | float) else "n/a"

        lines.append(
            f"| {coin['name']} ({ticker}) | {price_text} | {change_text} | "
            f"{_fmt_money(coin.get('market_cap'))} | {score_text} | {recommendation_text} |"
        )
        citations.extend(
            [
                {"tool": "get_quote", "args": {"ticker": ticker}, "result": str(quote)},
                {"tool": "analyze_ticker_8dim", "args": {"ticker": ticker, "fast": True}, "result": str(analysis)},
            ]
        )

    lines.append("")
    lines.append("Market cap sıralaması CoinGecko'dan, fiyat ve 8-dim analiz sonuçları canlı tool çağrılarından geldi.")
    return {"messages": [AIMessage(content="\n".join(lines))], "citations": citations}


def _build_agent(risk_profile: str = "balanced"):
    """Lazy build so missing GEMINI_API_KEY doesn't break import."""
    prompt = _build_prompt(risk_profile)
    return create_react_agent(get_llm(), tools=_TOOLS, prompt=prompt)


async def run(state: AgentState) -> AgentState:
    direct = _handle_top_crypto_request(state)
    if direct is not None:
        return direct

    risk_profile = state.get("risk_profile", "balanced")
    agent = _build_agent(risk_profile)
    result = await agent.ainvoke({"messages": state.get("messages", [])})
    return {
        "messages": result["messages"][-1:],
        "citations": extract_tool_calls(result["messages"]),
    }
