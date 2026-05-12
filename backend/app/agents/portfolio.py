"""Portfolio agent — analyzes user's holdings: performance, sector
concentration, drift from target allocation."""
from __future__ import annotations

from langgraph.prebuilt import create_react_agent

from app.agents.llm import get_llm
from app.agents.state import AgentState
from app.agents._helpers import extract_tool_calls
from app.tools.portfolio_tools import list_holdings, list_transactions
from app.tools.market_tools import get_quote

SYSTEM_PROMPT_BASE = """You are the Portfolio agent for FinCoach.

Tools:
- list_holdings()         — current portfolio rows
- list_transactions(limit) — recent income/expense rows (used to compute cash flow)
- get_quote(ticker)        — refresh prices for held tickers

For a portfolio question:
1. Call list_holdings.
2. Refresh prices for each ticker via get_quote.
3. Compute total value, unrealized P&L per position, sector / asset-class
   concentration (highest single position).
4. Report concisely: total value first, then any concentration risks.

Never invent positions. If list_holdings is empty, say so plainly."""

RISK_GUIDANCE = {
    "conservative": """
RISK PROFILE: Conservative (0-50 score)
- Emphasize stability, low volatility, and consistent dividends.
- Alert if ANY single position exceeds 15% of portfolio value.
- Recommend dividend-yielding stocks and bonds for stability.
- Flag high-volatility holdings as concentration risks.
- Suggest regular rebalancing toward stable asset classes.""",
    "balanced": """
RISK PROFILE: Balanced (51-90 score)
- Mixed approach: balance growth with stability.
- Alert if ANY single position exceeds 25% of portfolio value.
- Highlight sector concentration and suggest diversification.
- Include both growth and dividend plays in recommendations.
- Rebalancing advice when drift from 60/40 (stocks/bonds) occurs.""",
    "aggressive": """
RISK PROFILE: Aggressive (91-125 score)
- Focus on growth opportunities and long-term capital appreciation.
- Higher concentration tolerance; alert only if single position exceeds 40%.
- Highlight high-growth sectors and smaller-cap opportunities.
- Recommend growth stocks and emerging-market opportunities.
- Allow for tactical concentration in high-conviction bets.""",
}


def _build_prompt(risk_profile: str = "balanced") -> str:
    """Build risk-aware system prompt based on user's risk profile."""
    risk_guidance = RISK_GUIDANCE.get(risk_profile, RISK_GUIDANCE["balanced"])
    return SYSTEM_PROMPT_BASE + "\n" + risk_guidance


_TOOLS = [list_holdings, list_transactions, get_quote]


def _build_agent(risk_profile: str = "balanced"):
    prompt = _build_prompt(risk_profile)
    return create_react_agent(get_llm(), tools=_TOOLS, prompt=prompt)


async def run(state: AgentState) -> AgentState:
    risk_profile = state.get("risk_profile", "balanced")
    agent = _build_agent(risk_profile)
    result = await agent.ainvoke({"messages": state.get("messages", [])})
    return {
        "messages": result["messages"][-1:],
        "citations": extract_tool_calls(result["messages"]),
    }
