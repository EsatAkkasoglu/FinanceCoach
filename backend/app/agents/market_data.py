"""Market Data agent — live prices, technicals, 8-dim analysis.

Covers: US stocks, crypto, ETFs, indices, commodities (via ETF proxies),
forex, Treasury yields, futures. For named assets the agent resolves the
yfinance ticker first via ``resolve_symbol``.
"""
from __future__ import annotations

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

SYSTEM_PROMPT = """You are the Market Data agent for FinCoach.

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


def _build_agent():
    """Lazy build so missing GEMINI_API_KEY doesn't break import."""
    return create_react_agent(get_llm(), tools=_TOOLS, prompt=SYSTEM_PROMPT)


_agent = None


async def run(state: AgentState) -> AgentState:
    global _agent
    if _agent is None:
        _agent = _build_agent()
    result = await _agent.ainvoke({"messages": state.get("messages", [])})
    return {
        "messages": result["messages"][-1:],
        "citations": extract_tool_calls(result["messages"]),
    }
