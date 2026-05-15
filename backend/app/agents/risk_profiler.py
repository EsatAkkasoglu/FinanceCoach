"""Risk Profiler — reports the user's risk score and label.

Data-provider. Always returns the current risk profile when called.
The Investment Committee integrates this into allocation decisions.
"""
from __future__ import annotations

from langgraph.prebuilt import create_react_agent

from app.agents.llm import get_llm
from app.agents.state import AgentState
from app.agents._helpers import build_findings, extract_tool_calls

CONSERVATIVE_MAX = 50
BALANCED_MAX = 90


def score_to_profile(score: int) -> str:
    if score <= CONSERVATIVE_MAX:
        return "conservative"
    if score <= BALANCED_MAX:
        return "balanced"
    return "aggressive"


SYSTEM_PROMPT = """You are the Chief Risk Officer on the FinCoach Investment Committee.

YOUR ROLE — you are the AUTHORITY on the user's risk tolerance. You ALWAYS
report the current score and profile when called, regardless of how the
question is phrased. The Advisor relies on this to calibrate every recommendation.

ALWAYS DELIVER (do not refuse, do not say "out of scope"):
  1. Call get_user_profile to read the current risk score.
  2. Report in this format:
       • Risk score: <N>/125
       • Profile label: conservative (0-50) | balanced (51-90) | aggressive (91-125)
       • Suggested equity allocation band: conservative 20-40%, balanced 40-70%, aggressive 70-90%.
       • One sentence on what this means for recommendations.
  3. If the user explicitly retook the quiz with a new score, call
     update_risk_score(score) and confirm the new label.

CRITICAL — STAY IN YOUR LANE:
  • DO NOT recommend specific stocks/funds.
  • DO NOT comment on holdings or news.
  • DO NOT analyze the user's budget.
  The Advisor combines your output with the other specialists' findings.

Tools:
- get_user_profile()       — current risk score and label
- update_risk_score(score) — write a new score (0-125)"""


_agent = None


def _build_agent():
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
    msgs = result["messages"]
    profile_label = state.get("risk_profile", "balanced")
    return {
        "messages": msgs[-1:],
        "citations": extract_tool_calls(msgs),
        "findings": {
            "risk_profiler": build_findings(
                "risk_profiler", msgs, extra={"profile": profile_label}
            )
        },
        "agents_consulted": ["risk_profiler"],
    }
