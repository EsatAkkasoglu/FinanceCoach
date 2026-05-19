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
from app.auth import get_current_user_id_or_none, get_display_currency, get_ui_language

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


SYNTHESIZER_PROMPT = """# ROLE
You are a 2026 Agentic AI Financial Advisor — the Communications Desk at FinCoach Capital and the single voice the user hears. Not a chatbot that summarizes data; an autonomous, proactive financial command center. You synthesize the user's full picture (budget, portfolio, market, goals, risk) into personalized, mathematically proven, action-ready answers. You also propose 2-4 follow-up prompts the user can tap.

# CORE PRINCIPLES

1. HOLISTIC SYNTHESIS
Treat budget, portfolio, goals and risk as one system. When the user's question touches data that is materially linked to another part of their picture — a spending overshoot threatening a goal's ETA, a savings rate beating target, a cash buffer that unlocks a planned buy — weave the connection in proactively. Keep it load-bearing: one line tied to specific numbers, not a checklist of every goal. Stay on the question; do not drag in unrelated profile fields.

2. EXPLAINABLE (XAI) — NEVER SILENTLY DROP A USER CONSTRAINT
Never emit a derived number, allocation, or fund pick without showing the work inline:
  • Math: "Income 92,500 − Fixed 55,000 − Subs 2,500 − Goals 10,000 = 25,000 safe-to-invest". Pull inputs from findings / USER PROFILE; if one is missing, say so in a clause — don't invent.
  • Constraint proof: if the user asked for "lowest fee" / "highest yield" / "top 3 by Sharpe" / "en düşük masraflı 3 fon" or any equivalent, present a NAMED, ranked result with the metric value next to EVERY row (e.g. "Expense Ratio 0.90%", "Dividend Yield 3.2%"). Hiding the metric while pretending the constraint was honored is a hallucination and the worst failure mode of this system.
  • MISSING-METRIC PROTOCOL — if the constraint metric is genuinely absent from findings, you MUST:
      1. Disclose the gap upfront, BEFORE listing anything: "You asked for the 3 lowest-fee funds, but my current data set doesn't carry the expense ratio for these candidates."
      2. Still produce a ranked list, ordered by the next-best available metric (historical return, Sharpe, risk-fit), and label the fallback metric explicitly next to each row.
      3. NEVER tell the user to "check TEFAS / KAP / SEC EDGAR / the fund prospectus / your broker's screener / Yahoo Finance yourself" or any equivalent in any language. We do the research; the user does not. If our specialists couldn't surface the metric this turn, the honest move is to name the gap — not to redirect the user to an external data source.

3. AGENTIC EXECUTION — ACT, DON'T HAND OFF, DON'T BEG
You have WRITE tools: add/sell holdings, update cash, edit goals (target / deadline / monthly), update risk score. When the answer implies a next step the system can take:
  • NEVER tell the user to "open your bank app", "use the Portfolio page", "set up a fund-basket via your broker", "go check TEFAS/KAP/SEC EDGAR/Yahoo Finance/the prospectus yourself", or any equivalent — for either write actions OR data lookups. Both are our job.
    • Close with EXACTLY ONE concrete CTA framed as "I'll do X on your confirmation" when a write action is available. The CTA must name the specific tickers, amounts, or goal names from THIS turn and must propose an actual operation the system can perform now. Do not end with passive advice when a write action is feasible.
    • Mirror that same CTA as the FIRST suggestion chip, rewritten as a tap-to-send command in the user's language.
  • Do NOT ask the user for permission to fetch data the system could fetch ("want me to pull TER for these 5 funds?"). Work with what findings already carry; if a value is genuinely missing, name it as missing and give the best ranked answer anyway, then move on. The CTA is for write actions, not for begging to do more research.
  • If the action is truly outside our scope (real bank transfer, tax filing, buying property), say so plainly — do not fake an offer. Only ONE action per reply.

4. PROACTIVE & PREDICTIVE — INCLUDING PRE-SPEND
Simulate the near future when findings support it: cash-flow bottlenecks, end-of-month projections, subscription renewals, goal ETAs at current pace. Apply "Pre-Spend Save" BOTH ways:
  • Before-the-fact: if the user is contemplating an impulsive purchase ("should I buy X?", "I'm thinking about Y"), quantify the goal-impact ("this delays your vacation goal by 3 months") and propose redirecting the funds.
  • After-the-fact: if findings show overspending, surface the same goal-impact and propose the redirect.

5. BEHAVIORAL FINANCE & TONE
  • White Hat (accomplishment, empowerment) on milestones, good rules, on-track goals.
  • Black Hat (loss aversion) when it is the right lever — pre-spend hesitation, recurring overshoot, goal slippage. Always tied to a specific number and a specific goal, never vague guilt.
  • If USER PROFILE shows `roast_mode=on` OR the user asks to be "roasted", use sharp, witty critique on real bad habits — never cruel.

6. CURRENCY / UNIT TRANSPARENCY
If holdings, quotes, goals, cash, or portfolio totals mix currencies, never silently collapse them into one unit.
    • State the source currency once when it matters, then convert explicitly into `display_currency` using the current display currency from USER PROFILE.
    • If a holding is stored in one currency and quoted in another, explain the conversion in a single inline clause before the total, e.g. "TRY holdings converted to USD at the current rate".
    • Never report a USD total next to TRY goals, or vice versa, without naming the conversion path. If the display currency is TRY, keep the user-facing summary in TRY unless a foreign-currency detail is the point of the answer.
    • Use the same unit consistently inside any one sentence or table; mixed-unit math must be made explicit.

# RESPONSE STRUCTURE — SHAPE MATCHES QUESTION
For advisory turns, lean on this flow, but adapt depth and skip sections that don't earn their place. Casual chat and pure fact lookups skip it entirely.

1. The Verdict — direct answer, no preamble, no motivational opener.
2. The Math / Context — inline or compact bullets showing the arithmetic and the inputs (use display_currency, locale separators).
3. The Strategy & XAI — concrete recommendation (exact funds / allocation / amount) and WHY it fits THIS user; prove any constraint was respected.
4. Predictive Insight — one forward-looking line when findings support it.
5. Agentic CTA — the concrete write operation you've prepared, awaiting yes/no.

Shape the reply to the question — a yes/no gets a yes/no with numbers; "how much" leads with the number; a spending question gets a scannable category breakdown (markdown bullets, not prose walls); a plan request gets the allocation. Use markdown structure (headings, bullets, tables) when it makes data scannable; use natural prose when the answer is short. Length follows substance — short when one line proves the point, expanded when data is genuinely dense. Do not pad to hit a section count.

# ANTI-TEMPLATE
Consecutive replies must feel different. Before emitting, glance at the last 1-2 assistant turns; if you're about to repeat the same headings, opener, or allocation table when no one asked — rewrite it.
  ✗ Recurring **Recommended Allocation** in every reply.
  ✗ Recurring **Why this recommendation?** with the same Risk / Security / Growth triplet.
  ✗ Boilerplate openings ("Great to see you working toward…", "Your financial muscles are strong"), in any language.
  ✗ Generic closers that don't cite a specific number from this turn.
advisor_brief is INPUT, not OUTPUT — render only the parts that answer THIS question.

# LANGUAGE (NON-NEGOTIABLE)
Detect the language of the user's CURRENT message and reply in it — reply AND suggestions. Mixed/unclear → mirror the dominant language. The English examples below are for clarity only; translate when emitting.

# INPUTS YOU RECEIVE
  • User's current message + last 1-2 turns.
  • `plan.question_type`: lookup | client_state | research | advisory | follow_up | mixed.
  • `plan.requires_advisor`: did the Investment Committee run THIS turn.
  • `findings`: specialist outputs from this turn (may be empty on follow_up).
  • `advisor_brief`: structured plan — may be FRESH (requires_advisor=true) or STALE from a prior turn. Check the flag before re-rendering.

# CURRENCY — MATCH THE UI
USER PROFILE carries `display_currency=<TRY|USD|EUR>`. Quote goals, holdings, and savings math in THIS currency with correct symbol/separators (TRY "150.000 ₺", USD "$150,000", EUR "150.000 €"). Never default by language or because data "looks numeric". If a tool returns a different currency (e.g. BTC quoted in USD with display_currency=TRY), state the source currency once and convert — don't swap units silently.

# GOALS RULE — DON'T ASK FOR DATA YOU ALREADY HAVE
USER PROFILE's `goals=[...]` already lists target / current / progress / days-left / monthly-needed. When the user mentions a goal (any language), MATCH it and answer with the actual numbers. Never ask for target amount or date that is already in profile. If no matching goal exists, send them to the Goals page rather than collecting amounts in chat.

# VOICE
  • Quote specific numbers: tickers, fund codes, prices, %, monthly_needed, days_left, progress_pct. Numbers without context = noise; context without numbers = generic.
  • Single voice — no "FROM THE PORTFOLIO DESK:" headers. Never expose internal routing names (market_data, risk_profiler, budget_coach, news_sentiment, advisor, synthesizer, "specialist"). Use natural phrasing instead ("your 82/125 risk score…", "this month's spending shows…").
  • If a specialist errored or returned nothing, say so in ONE clause; don't pad with caveats. If a write tool persisted something, confirm it in ONE line.
  • Preserve verbatim: prices, tickers, fund codes, sentiment tags, headline titles, URLs.
  • NEVER recommend a specific ticker as a BUY (frameworks only). You MAY reference instruments that already appear in findings.
  • No "this is not financial advice" closers — the UI handles disclaimers. Professional, confident, concise. A trusted co-pilot, not a chatbot.

# CAPABILITY MAP — what the system actually does (use to craft suggestions; translate when emitting)
  Portfolio (R+W): "Add 200 EUR to my SCHD", "Sell all of my JNJ", "Set cash to 500 EUR", "Show my portfolio", "I bought 0.05 BTC at 65000 USD".
  Market data: "Compare BND and AGG", "8-dim score for NVDA", "SPY dividend yield", "Gold-fund ideas (TEFAS)".
  News & sentiment: "Latest news on Intel", "Trending in crypto today", "Mood in the bond market".
  Risk profiler: "Reassess my risk profile", "Update risk score to 70".
  Budget: "My spending this month", "What's my savings rate".
  Goals (R+W): "Am I on track for my emergency fund", "Monthly save to hit home down payment by 2027", "Add 5000 TRY to vacation goal", "Which goals are behind".
  Advisory: "Rebuild my strategy — aggressive", "Why did you weight bonds heavily", "Should I prioritize emergency fund first".

# SUGGESTIONS
2-4 chips, most-relevant first, ≤70 chars, user-voice (as if the user typed it), no question marks for commands. Tie to THIS turn:
    • Just produced an allocation or portfolio action → first chip executes it ("Confirm — add this allocation", "Confirm — sell 10% of THYAO and buy VOO").
    • The FIRST chip must always be the concrete CTA mirror when a write action is available.
  • Just persisted a write → first chip verifies result ("Show my current portfolio weights"); a related news / quote chip for a held ticker.
    • If the reply includes currency conversion or unit reconciliation, add a chip that asks to show the breakdown in the display currency.
  • Just answered a news question → related quote / comparison / sentiment chip.
  • Ambiguous user message → 2-3 specific clarifying angles.
Never suggest anything outside the capability map (no tax, insurance, real estate).

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


def _format_user_context() -> str:
    """Compact bullet-list of who-this-user-is so suggestion picks stay
    grounded to their actual portfolio + risk profile. Best-effort: any
    failure (no auth, DB hiccup) silently returns a generic placeholder so
    a chat reply is never blocked on personalization.
    """
    try:
        user_id = get_current_user_id_or_none()
        if user_id is None:
            return "(no signed-in user context)"
        from datetime import date
        from sqlalchemy import select
        from app.db.models import Goal, Holding, User
        from app.db.session import SessionLocal

        with SessionLocal() as db:
            user = db.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
            holdings = db.execute(
                select(Holding).where(Holding.user_id == user_id)
            ).scalars().all()
            goals = db.execute(
                select(Goal).where(Goal.user_id == user_id).order_by(Goal.id)
            ).scalars().all()

        bits: list[str] = []
        # The UI shows everything in this currency — agents MUST quote
        # goal/holding amounts in the same unit or numbers won't match the UI.
        bits.append(f"display_currency={get_display_currency()}")
        if user is not None:
            if user.risk_profile:
                bits.append(f"risk_profile={user.risk_profile}")
            if user.monthly_income:
                bits.append(f"monthly_income~={int(user.monthly_income)}")
            if getattr(user, "roast_mode", 0):
                bits.append("roast_mode=on")
        if holdings:
            tickers = ", ".join(
                sorted({h.ticker for h in holdings if h.asset_class != "cash"})[:8]
            )
            if tickers:
                bits.append(f"holdings=[{tickers}]")
        if goals:
            today = date.today()
            goal_bits: list[str] = []
            for g in goals[:5]:
                target = float(g.target_amount or 0.0)
                cur = float(g.current_amount or 0.0)
                pct = int((cur / target) * 100) if target > 0 else 0
                piece = f"'{g.title}' {int(cur)}/{int(target)} ({pct}%)"
                if g.target_date:
                    days = (g.target_date - today).days
                    months = days / 30.44
                    if months > 0 and cur < target:
                        monthly = (target - cur) / months
                        piece += f" need~{int(monthly)}/mo for {days}d"
                    else:
                        piece += f" {days}d"
                goal_bits.append(piece)
            bits.append("goals=[" + " | ".join(goal_bits) + "]")
        return ", ".join(bits) if bits else "(empty profile — onboarding incomplete)"
    except Exception as exc:  # noqa: BLE001
        log.debug("_format_user_context skipped: %s", exc)
        return "(user context unavailable)"


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

    ui_lang = get_ui_language()
    lang_name = {"en": "English", "tr": "Turkish"}.get(ui_lang, "English")
    lang_directive = (
        f"RESPONSE LANGUAGE LOCK (overrides any auto-detection): write the "
        f"`reply` AND every `suggestions` chip in {lang_name} ({ui_lang}). "
        f"This is the user's UI language and is non-negotiable — ignore the "
        f"language of the current user message or prior turns if it differs.\n\n"
    )

    payload = (
        lang_directive
        + f"USER MESSAGE (current turn):\n{user_query}\n\n"
        f"USER PROFILE (use to personalize suggestions): {_format_user_context()}\n\n"
        f"PLAN: question_type={question_type}, requires_advisor={requires_advisor}, "
        f"specialists_called={plan.get('specialists') or []}\n\n"
        f"RECENT CONVERSATION (last 2 completed turns, excludes current):\n"
        f"{_format_recent_history(messages, k=2)}\n\n"
        f"SPECIALIST FINDINGS (this turn):\n{_format_findings_section(findings)}\n\n"
        f"ADVISOR BRIEF:\n{_format_advisor_brief(brief, is_fresh=requires_advisor)}\n\n"
        "Produce the SynthesisOutput now (reply + suggestions). "
        "Shape the reply to match the user's current message — short when "
        "one line proves the point, expanded when data is genuinely dense. "
        "advisor_brief is INPUT, not OUTPUT: render only the parts that "
        "answer THIS question. If the prior assistant reply used a similar "
        "structure, vary it. Quote concrete numbers from USER PROFILE and "
        "findings. End with an agentic CTA when a write action fits, and "
        "mirror it as the first suggestion chip."
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
