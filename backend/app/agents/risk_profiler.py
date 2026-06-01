"""Risk Profiler — reports the user's risk score and label.

Data-provider on the Investment Committee. ALWAYS returns a structured
``RiskProfileBrief`` so the Advisor and the XAI ("why this recommendation")
panel can quote concrete drivers — score, profile, suggested equity band,
2-3 reasoning sentences, and the factors that shaped the profile.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.agents._helpers import normalize_content
from app.agents.advisor import ReasoningDriver
from app.agents.llm import get_llm
from app.agents.state import AgentState
from app.settings import settings

log = logging.getLogger("fincoach.risk_profiler")

CONSERVATIVE_MAX = 50
BALANCED_MAX = 90


def score_to_profile(score: int) -> str:
    if score <= CONSERVATIVE_MAX:
        return "conservative"
    if score <= BALANCED_MAX:
        return "balanced"
    return "aggressive"


def _equity_band_for(profile: str) -> tuple[int, int]:
    if profile == "conservative":
        return (20, 40)
    if profile == "aggressive":
        return (70, 90)
    return (40, 70)


class RiskProfileBrief(BaseModel):
    """Structured XAI-ready report from the Chief Risk Officer."""
    score: int = Field(ge=0, le=125, description="Current risk score, 0-125.")
    profile: str = Field(description="conservative | balanced | aggressive")
    equity_low: int = Field(ge=0, le=100, description="Suggested equity lower bound %.")
    equity_high: int = Field(ge=0, le=100, description="Suggested equity upper bound %.")
    reasoning: list[str] = Field(
        default_factory=list,
        description=(
            "2-3 short sentences (user's language) explaining what THIS score "
            "implies for allocation choices — volatility tolerance, time "
            "horizon assumption, equity sleeve sizing."
        ),
    )
    drivers: list[ReasoningDriver] = Field(
        default_factory=list,
        description=(
            "2-3 concrete drivers behind the profile. Sources: 'user_input' "
            "(quiz result, explicit override), 'risk_profiler' (the score "
            "itself), 'memory' (prior preference)."
        ),
    )


SYSTEM_PROMPT = """You are the Chief Risk Officer on the FinCoach Investment Committee.

You will receive the user's current risk score and the latest user message,
and produce a `RiskProfileBrief` (structured object) — NOT prose.

ALWAYS:
  • Map score → profile: 0-50 conservative, 51-90 balanced, 91-125 aggressive.
  • Use these equity bands:
      conservative → 20-40 %
      balanced     → 40-70 %
      aggressive   → 70-90 %
  • Write `reasoning` as 2-3 short sentences in the SAME LANGUAGE as the
    user's message. Explain what the score implies — volatility tolerance,
    typical time horizon, and the equity sleeve it justifies.
  • Populate `drivers` with 2-3 entries naming what produced this profile.
    Examples (source / factor / impact):
      - 'risk_profiler' / 'Risk skoru 72 (orta üst)' / 'balanced profile, equity 40-70%'
      - 'user_input'    / 'Quizde uzun vade tercih ettin' / 'volatility toleransını yukarı taşır'

STAY IN YOUR LANE:
  • DO NOT recommend specific stocks, funds, or tickers.
  • DO NOT comment on news, holdings, or the user's budget.
  • The Advisor will combine your brief with the other specialists' findings.

Return ONLY the structured object."""


_brief_llm = None


def _get_llm():
    global _brief_llm
    if _brief_llm is None:
        # Structured brief — near-deterministic for a stable risk read.
        _brief_llm = get_llm(
            settings.gemini_structured_temperature
        ).with_structured_output(RiskProfileBrief)
    return _brief_llm


_UPDATE_RE = re.compile(
    r"(?:update|set|change|make|güncelle|ayarla|yap)\D{0,40}?(\d{1,3})",
    re.IGNORECASE,
)


def _last_user_text(messages: list) -> str:
    for m in reversed(messages or []):
        if isinstance(m, HumanMessage):
            return normalize_content(getattr(m, "content", "")).strip()
    return ""


async def run(state: AgentState) -> AgentState:
    """Read the user's profile, optionally apply a score update, then ask the
    LLM to produce a structured `RiskProfileBrief`.

    Tools are invoked manually (no ReAct loop) so we can pin the output to a
    Pydantic schema and emit XAI drivers consistently.
    """
    from app.tools.user_tools import get_user_profile, update_risk_score

    messages = state.get("messages") or []
    user_text = _last_user_text(messages)

    tool_calls: list[dict[str, Any]] = []

    # 1) Read current profile
    profile_payload = await get_user_profile.ainvoke({})
    tool_calls.append({"tool": "get_user_profile", "args": {}, "result": profile_payload})

    # 2) If the user explicitly asks to update the score, do it.
    new_score: int | None = None
    if user_text:
        m = _UPDATE_RE.search(user_text)
        if m:
            try:
                candidate = int(m.group(1))
                if 0 <= candidate <= 125 and any(
                    kw in user_text.lower()
                    for kw in ("risk", "score", "skor", "profil")
                ):
                    new_score = candidate
            except ValueError:
                new_score = None
    if new_score is not None:
        upd = await update_risk_score.ainvoke({"score": new_score})
        tool_calls.append({"tool": "update_risk_score", "args": {"score": new_score}, "result": upd})
        if isinstance(upd, dict) and "risk_score" in upd:
            profile_payload = {**(profile_payload if isinstance(profile_payload, dict) else {}), **upd}

    # 3) Derive deterministic fields the LLM should NOT be free to invent.
    score = 70
    if isinstance(profile_payload, dict) and isinstance(profile_payload.get("risk_score"), int):
        score = profile_payload["risk_score"]
    derived_profile = score_to_profile(score)
    equity_low, equity_high = _equity_band_for(derived_profile)

    # 4) Ask the LLM to produce reasoning + drivers given the locked numbers.
    payload = (
        f"USER MESSAGE:\n{user_text or '(no explicit question)'}\n\n"
        f"CURRENT RISK DATA (LOCKED — copy these exact numbers into the output):\n"
        f"  • score: {score}\n"
        f"  • profile: {derived_profile}\n"
        f"  • equity band: {equity_low}-{equity_high}%\n"
        + (f"  • NOTE: user just updated their score this turn to {new_score}.\n" if new_score is not None else "")
        + "\nProduce the RiskProfileBrief now."
    )

    try:
        brief: RiskProfileBrief = await _get_llm().ainvoke(
            [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=payload)]
        )
        # Hard-pin the deterministic fields in case the LLM drifted.
        brief = brief.model_copy(update={
            "score": score,
            "profile": derived_profile,
            "equity_low": equity_low,
            "equity_high": equity_high,
        })
    except Exception as exc:  # noqa: BLE001
        log.exception("risk_profiler structured-output failed — falling back to minimal brief")
        brief = RiskProfileBrief(
            score=score,
            profile=derived_profile,
            equity_low=equity_low,
            equity_high=equity_high,
            reasoning=[],
            drivers=[],
        )
        # Return the error too so the synthesizer can mention it if needed.
        summary_text = (
            f"Risk score: {score}/125 — {derived_profile}. "
            f"Suggested equity band: {equity_low}-{equity_high}%."
        )
        return {
            "messages": [AIMessage(content=summary_text)],
            "citations": tool_calls,
            "findings": {
                "risk_profiler": {
                    "summary": summary_text,
                    "tool_calls": tool_calls,
                    "extra": {"profile": derived_profile, "brief": brief.model_dump()},
                }
            },
            "agents_consulted": ["risk_profiler"],
            "error": {"agent": "risk_profiler", "type": type(exc).__name__, "message": str(exc)},
        }

    # 5) Build the user-facing summary message (terse — synthesizer will weave).
    reasoning_text = " ".join(brief.reasoning).strip()
    summary_text = (
        f"Risk score: {brief.score}/125 — {brief.profile}. "
        f"Suggested equity band: {brief.equity_low}-{brief.equity_high}%."
    )
    if reasoning_text:
        summary_text = f"{summary_text} {reasoning_text}"

    return {
        "messages": [AIMessage(content=summary_text)],
        "citations": tool_calls,
        "findings": {
            "risk_profiler": {
                "summary": summary_text,
                "tool_calls": tool_calls,
                "extra": {"profile": brief.profile, "brief": brief.model_dump()},
            }
        },
        "agents_consulted": ["risk_profiler"],
    }
