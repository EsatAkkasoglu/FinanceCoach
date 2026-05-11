"""Budget Coach agent — spending analysis, savings, with optional roast mode."""
from __future__ import annotations

from langgraph.prebuilt import create_react_agent
from sqlalchemy import select

from app.agents.llm import get_llm
from app.agents.state import AgentState
from app.agents._helpers import extract_tool_calls
from app.db.models import User
from app.db.session import SessionLocal
from app.tools.portfolio_tools import list_transactions
from app.tools.user_tools import get_user_profile

SYSTEM_PROMPT_DEFAULT = """You are the Budget Coach agent for FinCoach.

Tools:
- list_transactions(limit) — recent income/expense rows
- get_user_profile()        — monthly_income reference

For a budget question:
1. Pull the last 200 transactions.
2. Group expenses by category for the current and prior month.
3. Highlight the largest variance and one concrete behavioral nudge.
4. Project end-of-month spend if pace continues.

Tone: warm, specific, non-judgmental. End with one small actionable suggestion."""

SYSTEM_PROMPT_ROAST = """You are the Budget Coach agent for FinCoach in ROAST MODE.

Same data analysis as default, but the delivery is playful sass:
- Tease overspending categories with light humor (not mean)
- Dramatize the math (e.g. "you spent 40% of rent on coffee, friend")
- Use 1-2 emojis max
- Always end with a constructive nudge

Tools:
- list_transactions(limit)
- get_user_profile()"""


_TOOLS = [list_transactions, get_user_profile]
_agent_default = None
_agent_roast = None


def _build(prompt: str):
    return create_react_agent(get_llm(), tools=_TOOLS, prompt=prompt)


def _is_roast(user_id: int = 1) -> bool:
    with SessionLocal() as db:
        u = db.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
        return bool(u and u.roast_mode)


async def run(state: AgentState) -> AgentState:
    global _agent_default, _agent_roast
    if _is_roast():
        if _agent_roast is None:
            _agent_roast = _build(SYSTEM_PROMPT_ROAST)
        agent = _agent_roast
    else:
        if _agent_default is None:
            _agent_default = _build(SYSTEM_PROMPT_DEFAULT)
        agent = _agent_default
    result = await agent.ainvoke({"messages": state.get("messages", [])})
    return {
        "messages": result["messages"][-1:],
        "citations": extract_tool_calls(result["messages"]),
    }
