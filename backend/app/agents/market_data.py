"""Market Data agent — live prices, technicals, fundamentals, 8-dim analysis.

Covers: US stocks, crypto, ETFs, indices, commodities (via ETF proxies),
forex, Treasury yields, futures. Backed by yfinance (no key, no rate limits)
with CoinGecko for crypto trending.

For named assets the agent resolves the ticker first via ``resolve_symbol``.
"""
from __future__ import annotations

import re
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.prebuilt import create_react_agent

import app.services.coingecko as cg
from app.agents.llm import get_llm
from app.agents.state import AgentState
from app.agents._helpers import build_findings, extract_tool_calls, latest_human_turn
from app.tools.market_tools import (
    get_quote,
    analyze_ticker_8dim,
    get_dividend_metrics,
    get_bist_dividend_leaders,
    get_bist_movers,
    scan_hot_trends,
    scan_rumors,
    get_company_overview,
    get_technical_indicators,
)
from app.tools.symbol_resolver import resolve_symbol, list_supported_categories
from app.tools.fund_tools import (
    get_fund_quote,
    get_fund_history,
    search_fund,
    list_top_funds,
)

SYSTEM_PROMPT_BASE = """You are the Equity & Fund Research Analyst on the FinCoach Investment Committee.

ABSOLUTE RULE — TOOLS ONLY:
  • NEVER state a price, change %, volume, dividend, or technical value from
    memory or training data. Those values are stale.
  • Every numeric answer MUST come from a tool call (get_quote, get_fund_quote,
    analyze_ticker_8dim, get_dividend_metrics, etc.) in THIS turn.
  • If a tool fails or returns no data, say so plainly — do NOT fall back to
    a remembered number.

YOUR ROLE — you are the AUTHORITY on market data, prices, technicals, and
fund/asset performance. You ALWAYS deliver a structured market snapshot when
called. The Advisor uses your numbers to assemble plans.

ALWAYS DELIVER (do not refuse):
  • Live prices & % changes for any ticker/fund mentioned (or implied —
    e.g. "fund and stock recommendation" → quote SPY/QQQ/VTI + 1-2 risk-aligned
    ETFs as representative candidates so the Advisor has reference data).
  • Historical / trend context when relevant: use get_technical_indicators
    for stocks/ETFs/indices, get_fund_history for TEFAS funds, and 8-dim
    fast analysis for US stocks/ETFs when the user asks for suitability,
    recommendation, or a deeper analysis.
  • Dividend metrics for income-oriented questions.
  • If no specific ticker is named but the question is about investing,
    fetch quotes for a small SHORTLIST of broad-market reference instruments
    aligned with the user's risk profile (see RISK PROFILE block below).
    Include at least one broad equity reference, one bond/defensive reference,
    and one risk-appropriate alternative/growth reference so the Advisor can
    compare the user's choices against a baseline.

CRITICAL — STAY IN YOUR LANE:
  • DO NOT comment on whether the user OWNS an asset (Portfolio Manager's job).
  • DO NOT summarize news headlines (News Desk's job).
  • DO NOT analyze the user's budget or risk score.

You can fetch live prices for ANY of these asset classes — never refuse a
query because of asset class alone:

GLOBAL (via yfinance + CoinGecko):
- US stocks & ADRs            (AAPL, NVDA, BABA, …)
- Crypto                      (-USD suffix: BTC-USD, ETH-USD) — CoinGecko primary
- ETFs / index funds          (SPY, QQQ, VTI, BND, VOO, ARKK)
- Stock indices               (^GSPC, ^IXIC, ^VIX, ^DJI; BIST=XU100.IS)
- Commodities (via ETFs)      (GLD=gold, SLV=silver, USO=oil, UNG=nat gas, CPER=copper)
- Commodity futures           (GC=F→GLD, CL=F→USO, SI=F→SLV — auto-proxied)
- Forex                       (EURUSD=X, USDTRY=X, GBPUSD=X)
- Treasury yields             (^TNX=10Y, ^TYX=30Y, ^IRX=3M)

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
5. ``get_company_overview`` — P/E, margins, sector, 52W range, analyst target,
   analyst rating distribution (strong buy / buy / hold / sell / strong sell)
   and dividend metadata. ONE call covers fundamentals + sentiment.
6. ``get_technical_indicators`` — SMA + RSI snapshot (overbought / oversold
   / above-SMA / below-SMA signals). Use whenever momentum/trend matters.
7. ``analyze_ticker_8dim`` — only for US stocks / ETFs (NOT crypto / indices
   / forex / futures / Turkish funds). Prefer ``fast=True`` unless the user
   explicitly asks for deep analysis.
8. ``get_dividend_metrics`` — any ticker; backed by yfinance.
8b. ``get_bist_dividend_leaders`` — use THIS (not get_dividend_metrics) when
   the user asks for the top high-dividend Turkish stocks or a BIST dividend
   ranking. Scans a curated BIST universe and returns the top N by yield.
8c. ``get_bist_movers`` — use THIS when the user asks for BIST top gainers,
   top losers, "en çok yükselenler", "en çok düşenler", or today's movers
   on Borsa Istanbul. Returns a ranked list of gainers and losers with % change.
9. ``scan_hot_trends`` — CoinGecko trending crypto + global market stats.
   US stock movers are no longer available.
10. ``scan_rumors`` — not available (data source removed). Direct users to
    the news/sentiment agent for current headlines.
11. ``list_top_funds`` — Turkish fund leaderboard by category rank.
12. ``list_supported_categories`` — meta-question 'what can you look up?'

DISAMBIGUATION:
- A 3-letter all-caps code in a Turkish-language query → likely a TEFAS fund
- A 3-4 letter all-caps in an English query → likely a US ticker
- When unsure, call BOTH (search_fund + resolve_symbol) and let the response shape itself.
- If ``resolve_symbol`` returns ``ticker: null`` AND ``search_fund`` returns
  empty, tell the user it's not supported.

CITATIONS: every numeric claim is tagged with its source (yfinance, coingecko,
TEFAS, 8-dim analysis, NewsAPI).

OUTPUT DEPTH:
- Single asset query (one price, one quote): brief — 2-3 lines.
- Scanner / trending / comparison / leaderboard: comprehensive — include
  ALL rows returned by the tool, organized under bold headings with a brief
  interpretive comment per section. Do not truncate lists.
- Advisory / suitability analysis: provide a research note, not a ticker dump.
  Include:
    1) current quote snapshot,
    2) trend / technical context from the available historical tool,
    3) fundamentals or 8-dim signals when available,
    4) how the asset behaves as risk-on, defensive, income, or alternative
       exposure.
  Keep it factual and tool-grounded; the Advisor will decide what it means
  for the user's personal plan.

LANGUAGE: write your report in the SAME language as the user's current
message. English question → English report. Turkish question → Turkish
report. The Turkish-fund phrasing above ("altın fonu", "İş Bankası hisse
fonu") is for INTENT DETECTION only — not a hint about output language."""

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
    get_company_overview,
    get_technical_indicators,
    analyze_ticker_8dim,
    get_dividend_metrics,
    get_bist_dividend_leaders,
    get_bist_movers,
    scan_hot_trends,
    scan_rumors,
    # TEFAS Turkish funds
    search_fund,
    get_fund_quote,
    get_fund_history,
    list_top_funds,
]

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


def _handle_top_crypto_request(state: AgentState) -> AgentState | None:
    """Fast-path for 'top N crypto by market cap' queries using CoinGecko."""
    user_text = _latest_user_text(state)
    if not _wants_top_crypto_market_cap(user_text):
        return None

    tr = any(t in user_text.lower() for t in ("kripto", "piyasa değ", "ilk ", "en yüksek"))
    limit = _requested_limit(user_text, default=5)

    try:
        coins = cg.top_coins(limit=limit, exclude_stablecoins=True)
    except cg.CoinGeckoError as exc:
        err_msg = (
            f"Top kripto listesi CoinGecko'dan alınamadı: {exc}"
            if tr
            else f"Couldn't fetch top crypto list from CoinGecko: {exc}"
        )
        return {"messages": [AIMessage(content=err_msg)], "citations": []}

    if tr:
        intro = (
            f"Piyasa değerine göre ilk {len(coins)} kripto — stablecoinler hariç; "
            "8-dim skor stablecoinlerde anlamlı değil."
        )
        header = "| Kripto | Fiyat | 24s değişim | Market cap | 8-dim skor | Öneri |"
    else:
        intro = (
            f"Top {len(coins)} cryptos by market cap, stablecoins excluded "
            "(8-dim score isn't meaningful for stables)."
        )
        header = "| Crypto | Price | 24h change | Market cap | 8-dim score | Reco |"

    lines = [intro, "", header, "|---|---:|---:|---:|---:|---|"]
    citations: list[dict[str, Any]] = []

    for coin in coins:
        ticker = f"{coin['symbol']}-USD"
        quote = get_quote.invoke({"ticker": ticker})
        analysis = analyze_ticker_8dim.invoke({"ticker": ticker, "fast": True})

        price = quote.get("price") if isinstance(quote, dict) else None
        change = quote.get("change_pct") if isinstance(quote, dict) else coin.get("change_pct_24h")
        score = analysis.get("final_score") if isinstance(analysis, dict) else None
        recommendation = analysis.get("recommendation") if isinstance(analysis, dict) else None
        error = analysis.get("error") if isinstance(analysis, dict) else None

        score_text = f"{float(score):.2f}" if isinstance(score, int | float) else "n/a"
        fallback_reco = ("hata" if tr else "error") if error else "n/a"
        recommendation_text = str(recommendation or fallback_reco)
        price_text = f"${float(price):,.4f}" if isinstance(price, int | float) else "n/a"
        change_text = f"{float(change):+.2f}%" if isinstance(change, int | float) else "n/a"
        cap_text = cg._fmt_money(coin.get("market_cap"))

        lines.append(
            f"| {coin['name']} ({ticker}) | {price_text} | {change_text} | "
            f"{cap_text} | {score_text} | {recommendation_text} |"
        )
        citations.extend([
            {"tool": "get_quote", "args": {"ticker": ticker}, "result": str(quote)},
            {"tool": "analyze_ticker_8dim", "args": {"ticker": ticker, "fast": True}, "result": str(analysis)},
        ])

    lines.append("")
    lines.append(
        "Market cap sıralaması CoinGecko'dan, fiyat ve 8-dim analiz canlı tool çağrılarından geldi."
        if tr
        else "Market cap ranking from CoinGecko; price and 8-dim figures from live tool calls."
    )
    return {"messages": [AIMessage(content="\n".join(lines))], "citations": citations}


def _build_agent(risk_profile: str = "balanced"):
    """Lazy build so missing GEMINI_API_KEY doesn't break import."""
    prompt = _build_prompt(risk_profile)
    return create_react_agent(get_llm(), tools=_TOOLS, prompt=prompt)


async def run(state: AgentState) -> AgentState:
    direct = _handle_top_crypto_request(state)
    if direct is not None:
        # Preserve the fast-path response but still surface findings.
        from langchain_core.messages import AIMessage
        synthetic_msgs = [AIMessage(content=direct["messages"][0].content)]
        return {
            **direct,
            "findings": {"market_data": build_findings("market_data", synthetic_msgs)},
            "agents_consulted": ["market_data"],
        }

    risk_profile = state.get("risk_profile", "balanced")
    agent = _build_agent(risk_profile)
    result = await agent.ainvoke({"messages": latest_human_turn(state.get("messages", []))})
    msgs = result["messages"]
    return {
        "messages": msgs[-1:],
        "citations": extract_tool_calls(msgs),
        "findings": {"market_data": build_findings("market_data", msgs)},
        "agents_consulted": ["market_data"],
    }
