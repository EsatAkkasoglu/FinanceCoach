"""Communications Desk — produces the single user-facing reply + suggestions.

Reads:
  • state["plan"]          — strategist's plan (drives follow-up vs new-plan mode)
  • state["findings"]      — per-specialist structured outputs from THIS turn
  • state["advisor_brief"] — Investment Committee's allocation framework
                              (present when newly produced this turn OR
                              persisted from a prior turn — see WHEN TO USE)
  • state["messages"]      — full history (last assistant reply is the
                              context for follow-up suggestions)

Output:
  • messages              — one AIMessage with the user-facing prose
  • suggestions           — 2-4 short follow-up prompts the UI shows as chips
"""
from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.agents.llm import get_llm
from app.agents.state import AgentState
from app.agents._helpers import normalize_content

log = logging.getLogger("fincoach.synthesizer")


class SynthesisOutput(BaseModel):
    """Final structured output from the Communications Desk."""
    reply: str = Field(
        description=(
            "The user-facing message in the user's language. Markdown allowed. "
            "Length depends on question_type — see prompt rules."
        )
    )
    suggestions: list[str] = Field(
        default_factory=list,
        description=(
            "2-4 short follow-up prompts the user can tap. Each is a complete, "
            "ready-to-send user message in the user's language. They MUST be "
            "actionable with FinCoach Capital's existing capabilities (see "
            "CAPABILITY MAP in the prompt). Order: most relevant first."
        ),
        min_length=0,
        max_length=4,
    )


SYNTHESIZER_PROMPT = """You are the Communications Desk at FinCoach Capital — the single voice the user hears.

You write the final reply AND propose 2-4 follow-up prompts the user can tap.

═══ LANGUAGE RULE (READ FIRST — THIS OVERRIDES EVERY EXAMPLE BELOW) ═══
  • Detect the language of the USER'S CURRENT MESSAGE and reply in THAT language.
  • English question → English reply AND English suggestions.
  • Turkish question → Turkish reply AND Turkish suggestions.
  • Mixed / unclear → mirror the dominant language of the current message.
  • The example suggestions in the CAPABILITY MAP below are written in
    English for clarity. They are NOT a hint about which language to use —
    always derive the output language from the user's current message.

═══ INPUTS YOU RECEIVE ═══
  • The user's current message and the last 1-2 turns of conversation.
  • `plan.question_type` — one of: lookup | client_state | research | advisory | follow_up | mixed
  • `plan.requires_advisor` — whether the Investment Committee ran THIS turn.
  • `findings` — specialist outputs from THIS turn (may be empty for follow_up).
  • `advisor_brief` — structured plan. CRITICAL: this may be the NEW brief
    produced this turn (requires_advisor=true) OR a STALE one persisted from
    a prior turn (requires_advisor=false). Read the flag to know which.

═══ REPLY MODE RULES ═══
1) `lookup` / `client_state` / `research`:
     Short factual answer. 1-3 sentences for lookups. A small table only
     if the data is genuinely tabular (e.g. portfolio breakdown). NO
     allocation tables, NO disclaimers.

2) `advisory` AND `requires_advisor=true` (a NEW plan was produced):
     Build the reply around the NEW advisor_brief.
       • Lead with the headline.
       • Render allocation as a tight markdown table.
       • Weave key considerations and next_steps into 2-3 short paragraphs.
       • Surface open_questions briefly so the user knows what would sharpen
         the plan.

3) `follow_up` (USER IS ACTING ON OR REFINING A PRIOR PLAN):
     CONVERSATIONAL CONTINUATION. Critical rules:
       • DO NOT re-render the full allocation table. The user already saw it.
       • DO NOT repeat the previous brief's headline verbatim.
       • DO NOT re-list the same considerations / next_steps / open_questions.
       • DO acknowledge what was done this turn (e.g. "Added SCHD and JNJ
         positions, set cash to 200 EUR") and report only the CHANGE.
       • DO surface any NEW data (e.g. a quote, a news headline) succinctly.
       • If a write-tool persisted something, confirm in ONE line what
         changed in the DB.
       • Keep it 2-5 sentences unless the user explicitly asked for detail.
       • OK to reference the prior plan briefly ("Plan targeted 15% cash;
         you're at 16.7% now — on track.").

4) `mixed`:
     Address each part in 1-2 sentences. No table unless needed.

═══ GENERAL RULES ═══
  • Language: see the LANGUAGE RULE at the top — it is non-negotiable.
  • Single voice. NO "FROM THE PORTFOLIO DESK:" headers. Weave naturally.
  • Preserve verbatim: numbers, prices, tickers, fund codes, sentiment tags,
    headline titles, URLs.
  • If a specialist returned an error / no data, say so in one clause.
  • NEVER recommend a specific ticker as a BUY (frameworks only). You MAY
    name instruments that already appear in findings as REFERENCES.
  • NO closing "this is not financial advice" disclaimers.

═══ CAPABILITY MAP (use this to craft suggestions) ═══
FinCoach Capital can do the following — your `suggestions` MUST steer
toward things the system actually does well. Examples are shown in
English; TRANSLATE them into the user's language when emitting suggestions.

  Portfolio (READ + WRITE):
    • "Add 200 EUR more to my SCHD position"
    • "Sell all of my JNJ"
    • "Set my cash balance to 500 EUR"
    • "Show my current portfolio"
    • "I bought 0.05 BTC at 65000 USD — add it"
  Market data:
    • "Compare BND and AGG"
    • "What's the 8-dim score for NVDA?"
    • "What's SPY's dividend yield?"
    • "Any gold-fund ideas (TEFAS)?"
  News & sentiment:
    • "Latest news on Intel?"
    • "What's trending in crypto today?"
    • "How's the mood in the bond market?"
  Risk profiler:
    • "Reassess my risk profile"
    • "Update my risk score to 70"
  Budget coach:
    • "My spending this month"
    • "What's my savings rate — am I on track?"
  Advisory:
    • "Rebuild my strategy — go aggressive"
    • "Why did you weight bonds so heavily?"
    • "Should I prioritize an emergency fund first?"

═══ HOW TO PICK SUGGESTIONS ═══
  • 2-4 chips, ordered most-relevant first.
  • Tailor to the CURRENT context (last assistant reply + this turn's facts).
    Examples:
      - If we just produced an allocation plan → suggest executing it
        ("SCHD ___ € al, BND ___ € al") AND a "neden …" curiosity prompt.
      - If we just persisted holdings → suggest checking the result
        ("portföyümün güncel ağırlıkları?") AND a related news prompt
        for one of the held tickers.
      - If we just answered a news question → suggest a related quote /
        comparison / sentiment query.
      - If the user asked something ambiguous → suggest 2-3 specific
        clarifying angles.
  • NEVER suggest things outside the capability map (no tax advice, no
    insurance, no buying real estate).
  • Each suggestion: ≤ 70 characters, no question marks if it's a command,
    user-voice (write as if the user typed it).

Return ONLY the structured `SynthesisOutput` object (reply + suggestions).
"""


def _format_findings_section(findings: dict[str, Any]) -> str:
    if not findings:
        return "(no specialist findings this turn)"
    parts: list[str] = []
    for name, payload in findings.items():
        if not isinstance(payload, dict):
            continue
        summary = (payload.get("summary") or "").strip() or "(no summary)"
        snippet = summary[:1800] + ("…" if len(summary) > 1800 else "")
        # Surface any structured write-tool confirmations so the synthesizer
        # can echo them verbatim in follow-up mode.
        tool_calls = payload.get("tool_calls") or []
        actions: list[str] = []
        for tc in tool_calls:
            tool = tc.get("tool", "")
            result = tc.get("result")
            if isinstance(result, dict) and result.get("ok") and result.get("action") in {
                "added", "merged", "set", "cleared", "removed",
            }:
                actions.append(f"  ✓ {tool} → {json.dumps(result, ensure_ascii=False, default=str)[:200]}")
        block = f"── [{name}] ──\n{snippet}"
        if actions:
            block += "\n  WRITES PERSISTED:\n" + "\n".join(actions)
        parts.append(block)
    return "\n\n".join(parts) if parts else "(no specialist findings this turn)"


def _format_recent_history(messages: list, k: int = 2) -> str:
    """Last k completed (user, assistant) pairs — synthesizer needs this to
    keep follow-up replies coherent and to spot what the prior plan was."""
    if not messages:
        return "(no prior turns)"
    human_idxs = [i for i, m in enumerate(messages) if isinstance(m, HumanMessage)]
    if len(human_idxs) < 2:
        return "(this is the first turn in the conversation)"

    pairs: list[tuple[str, str]] = []
    for i in range(len(human_idxs) - 1):
        start = human_idxs[i]
        end = human_idxs[i + 1]
        user_text = normalize_content(getattr(messages[start], "content", "")).strip()
        assistant_text = ""
        for j in range(end - 1, start, -1):
            if isinstance(messages[j], AIMessage):
                assistant_text = normalize_content(getattr(messages[j], "content", "")).strip()
                break
        pairs.append((user_text, assistant_text))

    if not pairs:
        return "(no completed prior turns)"

    lines: list[str] = []
    for u, a in pairs[-k:]:
        lines.append(f"USER: {u[:300]}{'…' if len(u) > 300 else ''}")
        lines.append(f"ASSISTANT: {a[:500]}{'…' if len(a) > 500 else ''}\n")
    return "\n".join(lines).strip()


def _last_user_text(messages: list) -> str:
    for m in reversed(messages or []):
        if isinstance(m, HumanMessage):
            return normalize_content(getattr(m, "content", "")).strip()
    return ""


_synth_llm = None


def _get_llm():
    global _synth_llm
    if _synth_llm is None:
        _synth_llm = get_llm().with_structured_output(SynthesisOutput)
    return _synth_llm


def _format_advisor_brief(
    brief: dict[str, Any] | None, *, is_fresh: bool
) -> str:
    if not brief:
        return "(no advisor brief — answer directly from findings)"
    label = "FRESHLY PRODUCED THIS TURN" if is_fresh else "PERSISTED FROM A PRIOR TURN (do NOT re-render)"
    try:
        payload = json.dumps(brief, ensure_ascii=False, indent=2, default=str)
    except (TypeError, ValueError):
        payload = str(brief)
    return f"[{label}]\n{payload}"


async def run(state: AgentState) -> AgentState:
    messages = state.get("messages") or []
    user_query = _last_user_text(messages)
    plan = state.get("plan") or {}
    question_type = plan.get("question_type", "lookup")
    requires_advisor = bool(plan.get("requires_advisor"))
    findings = state.get("findings") or {}
    brief = state.get("advisor_brief")

    payload = (
        f"USER MESSAGE (current turn):\n{user_query}\n\n"
        f"PLAN: question_type={question_type}, requires_advisor={requires_advisor}, "
        f"specialists_called={plan.get('specialists') or []}\n\n"
        f"RECENT CONVERSATION (last 2 completed turns, excludes current):\n"
        f"{_format_recent_history(messages, k=2)}\n\n"
        f"SPECIALIST FINDINGS (this turn):\n{_format_findings_section(findings)}\n\n"
        f"ADVISOR BRIEF:\n{_format_advisor_brief(brief, is_fresh=requires_advisor)}\n\n"
        "Produce the SynthesisOutput now (reply + suggestions)."
    )

    try:
        out: SynthesisOutput = await _get_llm().ainvoke(
            [SystemMessage(content=SYNTHESIZER_PROMPT), HumanMessage(content=payload)]
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("synthesizer structured-output call failed — falling back to plain text")
        # Minimal fallback so the user still sees something.
        fallback = await get_llm().ainvoke(
            [
                SystemMessage(content="You are FinCoach. Reply briefly in the user's language."),
                HumanMessage(content=user_query or "(no message)"),
            ]
        )
        text = normalize_content(getattr(fallback, "content", "")).strip() or "(no reply)"
        return {
            "messages": [AIMessage(content=text)],
            "suggestions": [],
            "error": {"agent": "synthesizer", "type": type(exc).__name__, "message": str(exc)},
        }

    # Dedupe / trim suggestions defensively.
    seen: set[str] = set()
    cleaned: list[str] = []
    for s in out.suggestions:
        s = (s or "").strip()
        if not s or s.lower() in seen:
            continue
        seen.add(s.lower())
        cleaned.append(s[:120])
        if len(cleaned) >= 4:
            break

    return {
        "messages": [AIMessage(content=out.reply)],
        "suggestions": cleaned,
    }
