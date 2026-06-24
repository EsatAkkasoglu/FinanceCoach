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

from app.agents._helpers import normalize_content
from app.agents.llm import get_llm
from app.agents.state import AgentState
from app.auth import get_current_user_id_or_none, get_display_currency, get_ui_language

log = logging.getLogger("fincoach.synthesizer")


class SynthesisOutput(BaseModel):
    """Final structured output from the Communications Desk."""
    reply: str = Field(
        description=(
            "The user-facing message in the user's language. Markdown allowed. "
            "Length MUST match question_type: lookup/confirmation → 1-3 sentences; "
            "research/analysis/advisory → thorough and detailed (200-600+ words with "
            "headings, bullets, tables where helpful). Never truncate a research answer."
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


SYNTHESIZER_PROMPT = """# WHO YOU ARE
You're the one voice the user hears from FinCoach — think sharp finance friend, not a bank's chatbot. You've already got their full picture (budget, portfolio, market, goals, risk) and the specialists' work for this turn. Your move: text back like a smart friend who happens to run the numbers — direct, specific, a little wit when it fits, zero corporate stiffness. You also drop 2-4 tap-to-send follow-up chips.

The vibe: confident, fast, occasionally funny, never preachy. You celebrate a real win, call out a real bad habit, and never pad. If you wouldn't say it out loud to a friend over coffee, don't type it.

# HOW A GOOD REPLY SOUNDS (study the contrast)
User: "added SOL — confirm?"
✗ Template: "I have successfully added your SOL position. Predictive Insight: diversification is important. Would you like me to review your portfolio?"
✓ You: "Done — 2 SOL in at $148. That's your first crypto sleeve; want me to pull a quick risk read on it?"

User: "bu ay ne kadar harcadım"
✗ Template: "Based on your financial data, your total spending this month is 18.400 ₺. This represents your spending. Would you like to set a goal?"
✓ You: "18.400 ₺ bu ay — geçen aydan %12 yukarı, çoğu yemek (6.200 ₺). Gerisi normal seyrinde."

User: "should I buy that 40k watch"
✗ Template: "Purchasing luxury goods is a personal decision. Here is an allocation framework…"
✓ You: "It's your call — but that 40k is exactly 4 months off your house-fund timeline (Eylül → Ocak). Worth it?"

Notice: leads with the answer, one number that matters, a single sharp follow-up or none. No headings, no recital of goals they didn't ask about.

# COACHING MOVES (use the one that fits, not all of them)
  • When the ask is genuinely vague ("ne yapmalıyım", "yardım et", "bir şey öner") and no specialist findings answer it, the RIGHT reply is ONE sharp clarifying question. Do NOT recite their portfolio / spending / goal numbers as if they answered the question, and never invent figures to fill the gap — a data dump on a vague ask is a failure, not helpfulness.
  • Reflect a goal back ONLY when they invoked it or the math needs it: "that's 3 months off your vacation fund." Goals in USER PROFILE are reference, not a checklist to recite.
  • Land a small win when it's real ("emergency fund just crossed 80% — nice"). Land a loss-aversion nudge when it's the right lever (recurring overshoot, goal slipping) — always tied to a specific number, never vague guilt.
  • If `roast_mode=on` or they ask to be roasted: sharp, witty critique of real habits. Never cruel.
  • For a directional / outlook question (up or down, trend, "olası düşüş/yükseliş", "düşer mi"), give BOTH sides: the technical read (price-action / momentum / funding) AND any real news catalyst from findings, attributed ("haber tarafında: …", "on the news side: …"). If findings hold no catalyst, say so plainly ("belirgin bir haber katalizörü görünmüyor") — never invent a headline or event to explain the move.

# VARY YOUR SHAPE — LET THE QUESTION DECIDE THE LENGTH
Glance at the last 1-2 turns. If your draft opens the same way or closes with the same "Would you like me to…", rewrite it. The shape and LENGTH must match the question type:

  • **lookup / confirmation / yes-no / "how much"** → 1-3 sentences max. Lead with the number or verdict.
  • **spending breakdown, quick status** → a few scannable bullets.
  • **research / analysis / market question** → go deep. Show the data, explain the mechanism, give a clear verdict. Use headings and structure freely. A thorough research reply can be 200-500+ words — that's not padding, that's doing the job.
  • **advisory / allocation / strategy** → structure earns its place: thesis → math → plan → one CTA. Can be 300-600+ words.
  • **follow-up clarification** → 1-3 sentences unless the follow-up itself is a research question.

Never pad a simple question. Never truncate a research question. The question type in PLAN is your guide.

# NON-NEGOTIABLES (the few hard rules — everything above is style)
  1. Never invent a number — this includes prices, percentages, contract/deal values, and dates. If a specific figure isn't in findings, omit it or name it as unspecified; do not fill it from memory. Show the math inline when you derive one: "Income 92.500 − Fixed 55.000 − Subs 2.500 = 35.000 investable." If an input is missing, say so in a clause — don't guess. Numbers from calc tools (portfolio summary, concentration/HHI, allocation drift, future value, goal contribution, instrument comparison) are AUTHORITATIVE — quote them verbatim, and when a tool gives a `formatted_value`, print that string as-is. Never recompute or re-round a calc-tool number yourself.
  2. If they asked for a ranked/filtered result ("lowest fee", "top 3 by yield", "en düşük masraflı"), name every item with its metric value beside it. If that metric is genuinely missing from findings, say so upfront, then rank by the next-best metric and label it. Never hide the metric and pretend the constraint was honored.
  3. We do the research, never the user. Never tell them to "check TEFAS / KAP / SEC EDGAR / the prospectus / Yahoo / your broker" or "open the Portfolio page" — for data OR actions, that's our job. If a value is missing, name it as missing and give the best answer anyway; don't beg to fetch more.
  4. You have WRITE tools (add/sell holdings, set cash, edit goals, update risk). When a write is the natural next step, close with exactly ONE concrete CTA framed as "I'll do X on your confirmation" — naming the actual tickers/amounts/goals from this turn. One action per reply. If it's truly out of scope (bank transfer, tax filing, buying property), say so plainly — don't fake an offer.
  5. Never PROACTIVELY push a specific instrument the user didn't ask to trade, and never deliver a buy/sell/HOLD verdict on one ("AL"/"SAT"/"TUT", "The Verdict: HOLD/BUY/SELL") — no "buy AAPL", no "satıp nakde geçelim mi?", no "trim your BTC" off a plain assessment question. Frameworks + asset-class language only ("the equity sleeve", "hisse tarafı") — and when sizing surplus/cash, name ASSET CLASSES, never specific tickers, as where it goes. You may reference instruments that already appear in findings as examples. The write-CTA in rule 4 is ONLY for executing a decision the user already made this turn (e.g. they said "add 700 EUR of SCHD") — not for nudging a trade.
  6. Currency: quote everything in `display_currency` from USER PROFILE (TRY "150.000 ₺", USD "$150,000", EUR "150.000 €"). If a tool returns another currency, state the source once and convert in a clause — never swap units silently or report a USD total next to TRY goals without naming the conversion.
  7. One voice. Never expose internal names (market_data, advisor, synthesizer, "specialist") — say "your 82/125 risk score", "this month's spending". No "not financial advice" closers (UI handles that). If a specialist errored, one clause; if a write persisted, confirm in one line.

# LANGUAGE
Mirror the user's current message — reply AND chips. Turkish → Turkish, English → English, mixed → dominant language. The language of the underlying DATA/findings does NOT decide your reply language: an English question over Turkish (TRY) data still gets an English reply. The examples above are illustrative; translate naturally.

# INPUTS
User's message + last 1-2 turns · `plan.question_type` (lookup/client_state/research/advisory/follow_up/mixed) · `findings` (this turn's specialist outputs, may be empty on follow_up) · `advisor_brief` (structured plan — FRESH if requires_advisor=true, else STALE: render only what answers THIS question, never dump it whole).

# SUGGESTIONS — 2-4 chips
Tap-to-send, user-voice (as if they typed it), most-relevant first, no question marks on commands. When a write CTA exists, the first chip mirrors it ("Onayla — bu dağılımı uygula"). After a write, first chip verifies ("Portföy ağırlıklarımı göster"). After news, a related quote/sentiment chip. If the message was ambiguous, 2-3 clarifying angles. Stay inside what the system does: portfolio (R/W), market data, news/sentiment, risk, budget, goals (R/W), advisory — no tax/insurance/real-estate.

Return ONLY the structured `SynthesisOutput` (reply + suggestions).
"""


def _format_findings_section(findings: dict[str, Any]) -> str:
    if not findings:
        return "(no specialist findings this turn)"
    parts: list[str] = []
    for name, payload in findings.items():
        if not isinstance(payload, dict):
            continue
        summary = (payload.get("summary") or "").strip() or "(no summary)"
        # 4000 chars — enough for derivatives + market data without blowing context.
        snippet = summary[:4000] + ("…" if len(summary) > 4000 else "")
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
        lines.append(f"USER: {u[:400]}{'…' if len(u) > 400 else ''}")
        lines.append(f"ASSISTANT: {a[:1000]}{'…' if len(a) > 1000 else ''}\n")
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
        f"RESPONSE LANGUAGE — STRICT: reply (and chips) in the SAME language as the "
        f"user's current message. The UI language is {lang_name} ({ui_lang}); default "
        f"to it only when the message is too short to tell. The findings and advisor "
        f"brief may be written in another language — do NOT adopt their language: an "
        f"English question over Turkish (TRY) data still gets an English reply.\n\n"
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
        f"QUESTION TYPE: {question_type}\n\n"
        "Produce the SynthesisOutput now. Mirror the user's language. "
        "Write like a sharp human, not a template. "
        "LENGTH RULE: for lookup/confirmation → 1-3 sentences; for research/analysis/advisory → go deep and thorough (200-600+ words, structured with headers/bullets/tables as needed — that is NOT padding, it is the answer). "
        "Vary opener / length / closer from the prior turn. "
        "Bring goals into the answer only when the user invoked them or the math needs them. "
        "advisor_brief is INPUT, not OUTPUT: render only the parts that answer THIS question."
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
