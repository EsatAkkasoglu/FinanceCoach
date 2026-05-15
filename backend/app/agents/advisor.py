"""Investment Committee / Advisor — assembles an allocation framework.

Runs AFTER the parallel specialist fan-out, ONLY when the strategist marks
``requires_advisor=True`` (advisory-type questions: "what should I buy?",
"is my portfolio balanced?", "how should I deploy this cash?").

Input  : state["findings"] — structured outputs from each consulted specialist.
Output : state["advisor_brief"] — a Pydantic-validated plan with allocation
         bands, key risks, action steps, and an explicit "not financial
         advice" disclaimer. The synthesizer renders it as prose.

The advisor NEVER recommends specific tickers — it produces a *framework*
(asset-class weights, considerations, next steps) so the disclaimer that
this is not financial advice remains honest.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.agents.llm import get_llm
from app.agents.state import AgentState

log = logging.getLogger("fincoach.advisor")


class AllocationBand(BaseModel):
    asset_class: str = Field(
        description=(
            "Asset class label, written in the SAME LANGUAGE as the user's "
            "current message. Examples — English: 'Equity / ETF', 'Bonds', "
            "'Cash', 'Gold', 'Crypto'. Turkish: 'Hisse Senedi / ETF', "
            "'Tahvil', 'Nakit', 'Altın', 'Kripto'."
        )
    )
    weight_pct_low: int = Field(ge=0, le=100)
    weight_pct_high: int = Field(ge=0, le=100)
    rationale: str = Field(description="One short sentence on why this weight for THIS user.")


class AdvisorBrief(BaseModel):
    """Structured plan produced by the Investment Committee."""
    headline: str = Field(description="One-sentence framing of the recommendation.")
    allocation: list[AllocationBand] = Field(
        description="Asset-class allocation bands. Weights should roughly sum to 100% mid-band."
    )
    considerations: list[str] = Field(
        description="3-5 bullet points the user must weigh (risk, time horizon, budget, concentration, taxes, FX, …)."
    )
    next_steps: list[str] = Field(
        description="2-4 concrete next actions (e.g. 'Build emergency fund first', 'Open a TEFAS account', 'Set monthly auto-invest')."
    )
    open_questions: list[str] = Field(
        default_factory=list,
        description="Information still missing that would sharpen the plan (e.g. 'time horizon', 'tax residency').",
    )


ADVISOR_PROMPT = """You are the Investment Committee at FinCoach — a small, senior team
that integrates findings from specialists into a clear allocation framework.

You receive:
  • The user's question (verbatim).
  • The user's risk profile label (conservative / balanced / aggressive).
  • Specialist findings (one per consulted desk) — each with a summary and
    the tool results they fetched.

Your job: produce a STRUCTURED PLAN as `AdvisorBrief`. NOT prose. The
Communications team turns this into the final user-facing message.

HARD RULES:
  1. NEVER recommend a specific ticker / fund code as a buy. You may NAME
     instruments that appeared in market_data findings as REFERENCES (e.g.
     "broad-market ETFs such as VOO/VTI are the typical reference for the
     equity sleeve"), but never "Buy X". You produce frameworks, not picks.
  2. Allocation weights MUST be calibrated to the risk profile:
       conservative  → equity 20-40%, bonds 40-60%, cash 10-20%, alt 0-10%
       balanced      → equity 40-70%, bonds 20-40%, cash 5-15%,  alt 0-15%
       aggressive    → equity 70-90%, bonds 0-20%,  cash 0-10%,  alt 5-20%
     Treat these as starting bands; tighten them based on findings (e.g. if
     the budget desk shows no emergency fund, raise cash; if portfolio is
     already concentrated, lower equity).
  3. Use the cash-flow / budget findings to size the plan. If the user has
     no investable surplus, the FIRST next step is "build investable
     surplus" — do not pretend money exists.
  4. Use the portfolio findings to flag concentration / gaps. If the user
     already holds 50% of one stock, your considerations must surface that.
  5. If a critical input is missing (e.g. no risk score, no budget data),
     add it to `open_questions` rather than guessing.
  6. Keep prose terse. Each rationale / consideration / step is ONE sentence.
  7. LANGUAGE: detect the language of the USER QUESTION below and write
     EVERY string field (headline, asset_class, rationale, considerations,
     next_steps, open_questions) in THAT language. English question →
     English output. Turkish question → Turkish output. This applies even
     if specialist findings were summarised in a different language.

Return ONLY the structured object."""


_advisor_llm = None


def _get_llm():
    global _advisor_llm
    if _advisor_llm is None:
        _advisor_llm = get_llm().with_structured_output(AdvisorBrief)
    return _advisor_llm


def _format_findings(findings: dict[str, Any]) -> str:
    """Render the findings dict into a compact prompt section."""
    if not findings:
        return "(no specialist findings collected)"
    lines: list[str] = []
    for name, payload in findings.items():
        if not isinstance(payload, dict):
            continue
        summary = (payload.get("summary") or "").strip()
        if not summary:
            summary = "(no summary)"
        snippet = summary[:1500] + ("…" if len(summary) > 1500 else "")
        lines.append(f"── [{name}] ──\n{snippet}")
        # Include compact tool results so the advisor can see actual numbers.
        tool_calls = payload.get("tool_calls") or []
        if tool_calls:
            tool_lines = []
            for tc in tool_calls[:6]:
                tool = tc.get("tool", "?")
                args = tc.get("args") or {}
                result = tc.get("result")
                if isinstance(result, (dict, list)):
                    try:
                        result_str = json.dumps(result, default=str, ensure_ascii=False)[:400]
                    except (TypeError, ValueError):
                        result_str = str(result)[:400]
                else:
                    result_str = str(result)[:400] if result is not None else ""
                tool_lines.append(f"   • {tool}({json.dumps(args, default=str, ensure_ascii=False)[:120]}) → {result_str}")
            lines.append("\n".join(tool_lines))
        lines.append("")
    return "\n".join(lines)


def _last_user_text(messages: list) -> str:
    for m in reversed(messages or []):
        if isinstance(m, HumanMessage):
            content = m.content
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                return "".join(
                    p.get("text", "") if isinstance(p, dict) else str(p) for p in content
                )
    return ""


async def run(state: AgentState) -> AgentState:
    """Produce a structured AdvisorBrief from the specialists' findings."""
    user_query = _last_user_text(state.get("messages") or [])
    risk_profile = state.get("risk_profile", "balanced")
    findings = state.get("findings") or {}

    payload = (
        f"USER QUESTION:\n{user_query}\n\n"
        f"USER RISK PROFILE: {risk_profile}\n\n"
        f"SPECIALIST FINDINGS:\n{_format_findings(findings)}\n"
        "Produce the AdvisorBrief now."
    )

    try:
        brief: AdvisorBrief = await _get_llm().ainvoke(
            [SystemMessage(content=ADVISOR_PROMPT), HumanMessage(content=payload)]
        )
        return {"advisor_brief": brief.model_dump()}
    except Exception as exc:  # noqa: BLE001
        log.exception("advisor failed — synthesizer will fall back to raw findings")
        return {
            "advisor_brief": None,
            "error": {
                "agent": "advisor",
                "type": type(exc).__name__,
                "message": str(exc),
            },
        }
