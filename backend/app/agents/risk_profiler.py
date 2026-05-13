"""Risk Profiler agent — scores onboarding quiz answers and infers risk
profile from observed behavior over time.

Quiz scoring (see plan section 5):
    0-50    → conservative
    51-90   → balanced
    91-125  → aggressive
"""
from __future__ import annotations

from langgraph.prebuilt import create_react_agent

from app.agents.llm import get_llm
from app.agents.state import AgentState
from app.agents._helpers import extract_tool_calls

CONSERVATIVE_MAX = 50
BALANCED_MAX = 90


def score_to_profile(score: int) -> str:
    if score <= CONSERVATIVE_MAX:
        return "conservative"
    if score <= BALANCED_MAX:
        return "balanced"
    return "aggressive"


SYSTEM_PROMPT = """You are the Risk Profiler specialist for FinCoach.

STRICT SCOPE — you ONLY answer about:
  • The user's risk score (0-125) and profile label (conservative/balanced/aggressive)
  • Updating the risk score from a new quiz result

YOU DO NOT cover any of these — another specialist will:
  • The user's holdings or whether their portfolio fits their risk → portfolio specialist
  • Asset prices or recommendations → market_data specialist
  • News or sentiment → news_sentiment specialist
  • Budget or spending → budget_coach specialist

If the user's question has parts outside your scope, ANSWER ONLY THE RISK-PROFILE PART.

Tools:
- get_user_profile()      — current risk score and label
- update_risk_score(score) — write a new score (0-125)

When the user asks about their risk:
1. Call get_user_profile.
2. Report numeric score, label, and one sentence on what it means for advice.

When the user wants to update their risk (e.g. retook the quiz with score 78):
1. Call update_risk_score(78).
2. Confirm the new label.

Profile labels: conservative (0-50), balanced (51-90), aggressive (91-125)."""


_agent = None


def _build_agent():
    # Lazy import avoids a circular import: user_tools.py imports score_to_profile
    # from THIS module.
    from app.tools.user_tools import get_user_profile, update_risk_score
    return create_react_agent(
        get_llm(),
        tools=[get_user_profile, update_risk_score],
        prompt=SYSTEM_PROMPT,
    )


async def run(state: AgentState) -> AgentState:
    global _agent
    if _agent is None:
        _agent = _build_agent()
    result = await _agent.ainvoke({"messages": state.get("messages", [])})
    return {
        "messages": result["messages"][-1:],
        "citations": extract_tool_calls(result["messages"]),
    }
