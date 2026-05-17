"""Budget Coach — reports the user's cash-flow and savings capacity.

Data-provider. Always returns a structured snapshot of monthly income,
spending, savings rate and projected end-of-month spend. The Advisor uses
this to size any investment recommendation.
"""
from __future__ import annotations

from langgraph.prebuilt import create_react_agent
from sqlalchemy import select

from app.agents.llm import get_llm
from app.agents.state import AgentState
from app.agents._helpers import build_findings, extract_tool_calls, latest_human_turn
from app.db.models import User
from app.db.session import SessionLocal
from app.tools.portfolio_tools import list_transactions
from app.tools.user_tools import get_user_profile

SYSTEM_PROMPT_DEFAULT_BASE = """You are the Cash-Flow Analyst on the FinCoach Investment Committee.

YOUR ROLE — you are the AUTHORITY on the user's spending, income, and
savings capacity. You ALWAYS deliver a structured cash-flow report when
called, even if the user's question is about something broader (e.g.
"what should I buy?"). The Advisor needs your numbers to size any plan.

ALWAYS DELIVER (do not refuse, do not say "out of scope"):
  1. Call get_user_profile (for monthly_income) and list_transactions(limit=200).
  2. Group expenses by category for the current and prior month.
  3. Report:
       • Monthly income (or "not on file")
       • Total spend this month vs. prior month (with delta)
       • Top 3 expense categories
       • Estimated savings rate (income - spend) / income, as %
       • Projected end-of-month spend if pace continues
       • Approximate monthly investable surplus (income - committed spend)
  4. End with ONE concrete behavioral nudge (one sentence).

CRITICAL — STAY IN YOUR LANE:
  • DO NOT recommend specific stocks, funds, or asset allocations.
  • DO NOT comment on portfolio holdings or news.
  • The Advisor combines your output with the Risk Officer and Portfolio Manager.

Tools:
- list_transactions(limit)
- get_user_profile()

Tone: warm, specific, non-judgmental."""

RISK_GUIDANCE_DEFAULT = {
    "conservative": """
RISK PROFILE: Conservative — target savings rate 25-30%. Note any
discretionary category > 5% of income.""",
    "balanced": """
RISK PROFILE: Balanced — target savings rate 20-25%. Flag the top 3
categories for optimization.""",
    "aggressive": """
RISK PROFILE: Aggressive — target savings rate 15-20%. Emphasize that
sitting on excess cash is itself a drag.""",
}

SYSTEM_PROMPT_ROAST_BASE = """You are the Cash-Flow Analyst on the FinCoach Investment Committee — ROAST MODE.

Same job, same data, same structured report — but the prose is playful sass:
- Tease overspend with light humor (never mean).
- Dramatize the math ("you spent 40% of rent on coffee, friend").
- 1-2 emojis max.
- Always end with one constructive nudge.

ALWAYS DELIVER your normal cash-flow report — the roast layer is on top, not
instead of. The Advisor still needs the numbers.

Tools:
- list_transactions(limit)
- get_user_profile()"""

RISK_GUIDANCE_ROAST = {
    "conservative": "Lean into 'boring is good' jokes; protect them from speculative spend.",
    "balanced": "Friendly accountability vibe; call out specific overspend categories.",
    "aggressive": "Hype them to deploy excess cash; tease tracking-every-coffee energy.",
}


def _build_prompt(prompt_base: str, risk_profile: str, use_roast: bool) -> str:
    guidance_dict = RISK_GUIDANCE_ROAST if use_roast else RISK_GUIDANCE_DEFAULT
    guidance = guidance_dict.get(risk_profile, guidance_dict["balanced"])
    return prompt_base + "\n" + guidance


_TOOLS = [list_transactions, get_user_profile]


def _build(prompt: str):
    return create_react_agent(get_llm(), tools=_TOOLS, prompt=prompt)


def _is_roast(user_id: int | None) -> bool:
    if user_id is None:
        return False
    with SessionLocal() as db:
        u = db.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
        return bool(u and u.roast_mode)


async def run(state: AgentState) -> AgentState:
    risk_profile = state.get("risk_profile", "balanced")
    use_roast = _is_roast(state.get("user_id"))
    base = SYSTEM_PROMPT_ROAST_BASE if use_roast else SYSTEM_PROMPT_DEFAULT_BASE
    prompt = _build_prompt(base, risk_profile, use_roast)
    agent = _build(prompt)
    result = await agent.ainvoke({"messages": latest_human_turn(state.get("messages", []))})
    msgs = result["messages"]
    return {
        "messages": msgs[-1:],
        "citations": extract_tool_calls(msgs),
        "findings": {"budget_coach": build_findings("budget_coach", msgs)},
        "agents_consulted": ["budget_coach"],
    }
