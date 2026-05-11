"""Portfolio agent — analyzes user's holdings: performance, sector
concentration, drift from target allocation."""
from __future__ import annotations

from langgraph.prebuilt import create_react_agent

from app.agents.llm import get_llm
from app.agents.state import AgentState
from app.agents._helpers import extract_tool_calls
from app.tools.portfolio_tools import list_holdings, list_transactions
from app.tools.market_tools import get_quote

SYSTEM_PROMPT = """You are the Portfolio agent for FinCoach.

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


_TOOLS = [list_holdings, list_transactions, get_quote]
_agent = None


def _build_agent():
    return create_react_agent(get_llm(), tools=_TOOLS, prompt=SYSTEM_PROMPT)


async def run(state: AgentState) -> AgentState:
    global _agent
    if _agent is None:
        _agent = _build_agent()
    result = await _agent.ainvoke({"messages": state.get("messages", [])})
    return {
        "messages": result["messages"][-1:],
        "citations": extract_tool_calls(result["messages"]),
    }
