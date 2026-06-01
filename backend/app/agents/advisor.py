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
from pydantic import BaseModel, Field, model_validator

from app.agents.llm import get_llm
from app.agents.state import AgentState
from app.settings import settings

log = logging.getLogger("fincoach.advisor")


class ReasoningDriver(BaseModel):
    """One concrete factor that influenced an allocation decision.

    Used for XAI ("why this recommendation") — connects each weight to a
    specific data point the specialists actually returned.
    """
    source: str = Field(
        description=(
            "Which specialist or signal produced this factor. One of: "
            "'risk_profiler', 'market_data', 'portfolio', 'budget', "
            "'news', 'memory', 'user_input'."
        )
    )
    factor: str = Field(
        description=(
            "One short clause naming the concrete observation in the user's "
            "language. Examples: 'Risk skoru 78 (balanced)', "
            "'Portföyde NVDA %42 ağırlık', 'Aylık nakit fazlası 3.500 TL', "
            "'VOO 6 aylık trend +12%'."
        )
    )
    impact: str = Field(
        description=(
            "How this factor moved the allocation, in the user's language. "
            "Examples: 'hisse payını yukarı çeker', 'nakit tamponu artırır', "
            "'tek hisseye konsantrasyonu sınırlar', 'nötr'."
        )
    )


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
    drivers: list[ReasoningDriver] = Field(
        default_factory=list,
        description=(
            "2-4 concrete drivers (source + factor + impact) that produced "
            "THIS band's weight. Pull directly from specialist findings — "
            "do not invent factors that were not in the inputs."
        ),
    )

    @model_validator(mode="after")
    def _band_order(self) -> AllocationBand:
        if self.weight_pct_low > self.weight_pct_high:
            raise ValueError(
                f"{self.asset_class}: weight_pct_low ({self.weight_pct_low}) "
                f"cannot exceed weight_pct_high ({self.weight_pct_high})"
            )
        return self


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
    why_summary: str = Field(
        default="",
        description=(
            "1-2 sentences (in the user's language) summarising the dominant "
            "reasons this overall plan took its shape. Should reference the "
            "user's risk profile and the most influential specialist signal."
        ),
    )
    key_drivers: list[ReasoningDriver] = Field(
        default_factory=list,
        description=(
            "3-5 dominant factors that shaped the OVERALL plan (not band-"
            "specific). These power the XAI 'Why this recommendation?' panel."
        ),
    )

    @model_validator(mode="after")
    def _allocation_sums(self) -> AdvisorBrief:
        # Mid-band weights should represent ~100% of a portfolio. A wild sum
        # means the model emitted incoherent bands — raise so the advisor
        # retries with a corrective hint before falling back.
        if self.allocation:
            mid = sum((b.weight_pct_low + b.weight_pct_high) / 2 for b in self.allocation)
            if not (70.0 <= mid <= 130.0):
                raise ValueError(
                    f"allocation mid-band weights sum to {mid:.0f}% — expected ~100%"
                )
        return self


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
  3. Use the cash-flow / budget findings to size the plan. ALWAYS provide
     a full allocation framework with example fund types/references, even
     when the user has no recorded investable surplus. Flag "build emergency
     fund first" as next_step[0], but still answer the question — give the
     allocation bands and reference instruments the user should look at once
     ready. Never withhold the framework just because budget data is missing.
  4. Use the portfolio findings to flag concentration / gaps. If the user
     already holds 50% of one stock, your considerations must surface that.
  5. If a critical input is missing (e.g. no risk score, no budget data),
     add it to `open_questions` rather than guessing.
  6. Keep prose terse. Each rationale / consideration / step is ONE sentence.
  7. LANGUAGE: detect the language of the USER QUESTION below and write
     EVERY string field (headline, asset_class, rationale, considerations,
     next_steps, open_questions, why_summary, drivers.factor, drivers.impact)
     in THAT language. English question → English output. Turkish question
     → Turkish output. This applies even if specialist findings were
     summarised in a different language.
  8. EXPLAINABILITY (XAI) — REQUIRED:
     • For EACH allocation band, populate `drivers` with 2-4 concrete
       factors PULLED FROM SPECIALIST FINDINGS (risk_profiler.extra,
       portfolio data, budget numbers, market signals, news sentiment).
       Each driver has `source`, `factor` (the observation), `impact`
       (how it moved THIS band).
     • Populate `key_drivers` (3-5 entries) with the OVERALL dominant
       factors — typically: the user's risk profile, portfolio gaps,
       cash runway, one market/news signal.
     • Populate `why_summary` (1-2 sentences) explaining the plan as a
       whole. Reference the risk profile and the strongest signal.
     • NEVER invent a driver that did not appear in the inputs. If a
       source is missing, omit it — do not fabricate numbers.
  9. DEPTH — REQUIRED FOR ADVISORY QUESTIONS:
     • Integrate ALL available specialist findings. A satisfactory answer
       must connect: the user's financial situation, risk appetite, existing
       holdings/concentration, market trend/history, and recent news/catalysts.
     • Do not produce generic advice that could apply to anyone. Every
       consideration and next step should be anchored to a concrete user
       fact or current market/news observation when available.
     • Avoid internal desk labels in user-facing strings. Do not write
       phrases like "according to market_data" or "risk_profiler says".
       Use natural phrasing: "recent price momentum", "your current cash
       buffer", "your aggressive risk score", "recent headlines".
     • If market/news/history data is missing because tools returned no data,
       explicitly include that limitation as a consideration rather than
       pretending the analysis is complete.

Return ONLY the structured object."""


_advisor_llm = None


def _get_llm():
    global _advisor_llm
    if _advisor_llm is None:
        # Structured brief — run near-deterministic for consistent allocations.
        _advisor_llm = get_llm(
            settings.gemini_structured_temperature
        ).with_structured_output(AdvisorBrief)
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


def _format_snapshot(snap: dict[str, Any]) -> str:
    """Compact holdings + goal context so the committee reasons about the
    user's actual concentration and savings runway. Returns '' if empty."""
    if not snap:
        return ""
    lines: list[str] = []
    holdings = snap.get("holdings") or []
    if holdings:
        parts = []
        for h in holdings:
            qty = h.get("quantity")
            tkr = h.get("ticker") or "?"
            parts.append(f"{tkr}×{qty:g}" if isinstance(qty, (int, float)) else str(tkr))
        cnt = snap.get("holdings_count", len(holdings))
        more = f" (+{cnt - len(holdings)} more)" if cnt > len(holdings) else ""
        lines.append(f"USER HOLDINGS ON FILE: {', '.join(parts)}{more}")
    g = snap.get("goals_summary") or {}
    if g.get("count"):
        ccy = g.get("currency") or ""
        lines.append(
            f"USER GOALS: {g.get('count')} active, "
            f"~{g.get('combined_monthly_needed')} {ccy}/mo needed, "
            f"{g.get('total_remaining')} {ccy} remaining"
        )
    return ("\n".join(lines) + "\n\n") if lines else ""


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
    snapshot = state.get("user_snapshot") or {}

    payload = (
        f"USER QUESTION:\n{user_query}\n\n"
        f"USER RISK PROFILE: {risk_profile}\n\n"
        f"{_format_snapshot(snapshot)}"
        f"SPECIALIST FINDINGS:\n{_format_findings(findings)}\n"
        "Produce the AdvisorBrief now."
    )

    base_msgs = [SystemMessage(content=ADVISOR_PROMPT), HumanMessage(content=payload)]
    last_exc: Exception | None = None
    # One corrective retry: at temp ~0 a re-ask is only useful if we feed the
    # validation error back so the model can fix the bands it got wrong.
    for attempt in range(2):
        msgs = base_msgs
        if attempt == 1 and last_exc is not None:
            msgs = base_msgs + [HumanMessage(content=(
                f"Your previous AdvisorBrief was rejected: {last_exc}. "
                "Fix it — every band needs weight_pct_low <= weight_pct_high, and "
                "the mid-band weights across all asset classes must sum to roughly "
                "100%. Return the corrected AdvisorBrief."
            ))]
        try:
            brief: AdvisorBrief = await _get_llm().ainvoke(msgs)
            return {"advisor_brief": brief.model_dump()}
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            log.warning("advisor attempt %d failed: %s", attempt + 1, exc)

    log.error("advisor failed after retry — synthesizer will fall back to raw findings")
    return {
        "advisor_brief": None,
        "error": {
            "agent": "advisor",
            "type": type(last_exc).__name__ if last_exc else "Error",
            "message": str(last_exc) if last_exc else "unknown advisor error",
        },
    }
