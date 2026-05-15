"""Graph builder — FinCoach Capital hierarchy.

Pipeline per user turn::

    START
      │
      ▼
    strategist  ──── plan() ────► dispatches to N specialists in parallel
      │                                  │
      │                                  ▼
      │                       ┌── market_data ──┐
      │                       │── portfolio ────│   each writes its own
      │                       │── budget_coach ─│   findings entry into state
      │                       │── risk_profiler │   (merged via reducer)
      │                       │── news_sentiment│
      │                       │── memory ───────│
      │                       └── document_parser
      │                                  │
      │                                  ▼
      │                            gather (sync barrier)
      │                                  │
      │                ┌─────────────────┴─────────────────┐
      │           requires_advisor?                        │
      │             yes │                              no  │
      │                 ▼                                  │
      │              advisor                               │
      │                 │                                  │
      │                 └──────────────┬───────────────────┘
      │                                ▼
      └──────────────────────► synthesizer ─► END

The strategist makes ONE planning call up front instead of looping. Specialists
run in parallel — N rounds compressed to 1. The advisor only runs when the
question needs allocation/plan synthesis (decided by the strategist). The
synthesizer always produces the final user-facing message.

Public API preserved for ``app.main``:
    AGENT_NODES        — name → callable map, used by the SSE handler
    FINISH             — kept as a sentinel for legacy event handling
    SYNTHESIZER_NODE   — name of the synthesizer node
    ADVISOR_NODE       — name of the advisor node
    STRATEGIST_NODE    — name of the strategist node
    build_supervisor() — compile the graph (signature unchanged)
"""
from __future__ import annotations

import logging
from typing import Any, Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from pydantic import BaseModel, Field

from app.agents.state import AgentState, RESET_SENTINEL
from app.agents.llm import get_llm
from app.agents._helpers import normalize_content
from app.agents import (
    market_data, portfolio, budget_coach, news_sentiment,
    risk_profiler, memory, document_parser, synthesizer, advisor,
)
from app.tools.user_tools import get_user_profile

log = logging.getLogger("fincoach.strategist")


AGENT_NODES = {
    "market_data": market_data.run,
    "portfolio": portfolio.run,
    "budget_coach": budget_coach.run,
    "news_sentiment": news_sentiment.run,
    "risk_profiler": risk_profiler.run,
    "memory": memory.run,
    "document_parser": document_parser.run,
}

STRATEGIST_NODE = "strategist"
GATHER_NODE = "gather"
ADVISOR_NODE = "advisor"
SYNTHESIZER_NODE = "synthesizer"

# Kept for backward compatibility with main.py imports.
FINISH = "FINISH"

SpecialistName = Literal[
    "market_data",
    "portfolio",
    "budget_coach",
    "news_sentiment",
    "risk_profiler",
    "memory",
    "document_parser",
]

QuestionType = Literal["lookup", "client_state", "research", "advisory", "mixed", "follow_up"]


# ── Strategist ───────────────────────────────────────────────────────────────


class ExecutionPlan(BaseModel):
    """Single-shot plan for this turn."""
    specialists: list[SpecialistName] = Field(
        description=(
            "Specialists to consult — listed in priority order. ALL of them run "
            "in parallel. Include EVERY desk whose data is needed. Empty list "
            "means no specialist is required (rare — e.g. pure clarification)."
        ),
        min_length=0,
        max_length=7,
    )
    requires_advisor: bool = Field(
        description=(
            "True ONLY if the user is asking for a recommendation / plan / "
            "allocation guidance ('ne önerirsin?', 'should I buy?', "
            "'is my portfolio balanced?', 'how to deploy this cash?'). "
            "False for pure lookups ('BTC price?', 'latest news on Intel?') "
            "and pure state reports ('show my portfolio')."
        )
    )
    question_type: QuestionType = Field(
        description=(
            "lookup     = single fact ('BTC fiyatı?')\n"
            "client_state = report on user's own data ('portföyüm', 'harcamalarım')\n"
            "research   = market/news ('intel haberi', 'altın fonu önerisi')\n"
            "advisory   = wants a plan / recommendation\n"
            "mixed      = multiple of the above"
        )
    )
    rationale: str = Field(
        description="One short sentence (max 25 words) explaining the plan."
    )
    confidence: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description=(
            "How confident you are that this dispatch correctly matches the user's "
            "intent. 0.9+ = obvious (single clear ask); 0.7-0.9 = solid; "
            "0.5-0.7 = mixed intent or ambiguous wording; <0.5 = guessing. "
            "Low scores cause the orchestrator to enrich memory or re-prompt."
        ),
    )


STRATEGIST_PROMPT = """You are the Chief Strategist of FinCoach Capital — a small finance firm
of specialist agents. At the top of every turn you produce ONE execution plan
that names which desks to consult (in parallel) and whether the Investment
Committee (advisor) should integrate their findings.

THE FIRM:
  research desk:
    market_data        Live prices, technicals, fund performance — any asset.
    news_sentiment     Headlines, sentiment, trending tickers, rumors.
    document_parser    PDFs / bank statements the user uploaded.
  client desk:
    portfolio          The user's OWN holdings, weights, P&L, concentration.
    budget_coach       The user's spending, savings rate, investable surplus.
    risk_profiler      The user's risk score and profile label.
    memory             What was said in earlier conversations (rarely needed).

PLANNING RULES:
  • Decompose the user question into its information needs. For each, pick
    the SINGLE desk that owns it.
  • LIST EVERY desk that holds a piece of the answer — do NOT settle for one.
    "Ne önerirsin?" needs budget_coach + risk_profiler + portfolio + market_data
    (and usually news_sentiment for catalyst awareness). They run in parallel.
  • `requires_advisor=True` whenever the user is asking for a recommendation,
    allocation, plan, or judgment ("should I…", "what do you recommend",
    "is my portfolio balanced", "how to deploy"). The Investment Committee
    will integrate the findings into a framework — without it the answer is
    just a pile of facts.
  • `requires_advisor=False` for pure lookups and pure state reports. The
    user just wants the data; no synthesis needed.
  • Memory desk is usually skipped unless the user references prior turns.

FOLLOW-UP DETECTION — READ THE PREVIOUS TURNS:
  You will receive recent conversation context (last 2-3 user/assistant turns
  + a snapshot of the previous Investment Committee brief headline if one
  exists). USE IT.

  A turn is a FOLLOW-UP when the user is acting on, refining, or confirming
  something already discussed — not asking a brand-new question. Signals:
    • Acknowledgement / confirmation words: "tamam", "ok", "evet",
      "anladım", "yes", "sounds good"
    • Action / execution language tied to prior content: "ekle şunları",
      "şunu yap", "git ahead", "uygula", "şunu yap o zaman"
    • A small refinement to the previous plan: "peki ya tahvil tarafı?",
      "bunu BND yerine AGG ile yapsak?"
    • Questions that pronoun-refer to the prior brief: "neden o oran?",
      "bu kadar nakit gereksiz değil mi?"

  WHEN it's a follow-up:
    → question_type = "follow_up"
    → requires_advisor = FALSE  (the plan already exists; don't regenerate it).
       The only exception is if the user explicitly asks for a fresh plan
       ("baştan planlayalım", "stratejiyi yeniden kur").
    → specialists = the MINIMAL set needed to act on or answer the follow-up.
       Examples:
         • "tamam SCHD 700€ aldım, ekle"      → [portfolio]   (action on holdings)
         • "peki tahvil için BND mi AGG mi?"  → [market_data] (compare two tickers)
         • "vergi mukimliği TR"                → []           (just info; no desk)
         • "bu kadar nakit gereksiz değil mi?" → [risk_profiler] (judgement, no full re-plan)
       Do NOT call the full 5-desk lineup again unless the user truly is
       asking for a new plan.

EXAMPLES (first-turn, no prior context):
  "BTC fiyatı kaç?"
    → specialists=[market_data], requires_advisor=False, question_type=lookup

  "intel haberlerini getirir misin?"
    → specialists=[news_sentiment], requires_advisor=False, question_type=research

  "portföyüm nasıl?"
    → specialists=[portfolio], requires_advisor=False, question_type=client_state

  "toplam bütçeme göre fon ve hisse satın almak istiyorum. ne önerirsin?"
    → specialists=[budget_coach, risk_profiler, portfolio, market_data, news_sentiment]
      requires_advisor=True, question_type=advisory

  "NVDA düştü, portföyümde var mı ve son haberler ne?"
    → specialists=[portfolio, news_sentiment, market_data]
      requires_advisor=False, question_type=mixed

EXAMPLES (with prior context — note how follow-up changes everything):
  Prior brief headline: "Muhafazakar profile uygun dengeli tahsis önerisi…"
  User: "tamam SCHD 700 euro aldım, JNJ 300 euro aldım, kalan nakit kalsın"
    → specialists=[portfolio], requires_advisor=False, question_type=follow_up
       (user is executing on the prior plan; call portfolio to record the
       holdings; do NOT re-run the full committee.)

  Prior brief headline: "Muhafazakar profile uygun dengeli tahsis önerisi…"
  User: "peki tahvil tarafı için BND yerine AGG kullanabilir miyim?"
    → specialists=[market_data], requires_advisor=False, question_type=follow_up

  Prior assistant reply mentioned vergi mukimliği as an open question.
  User: "vergi mukimliği Türkiye"
    → specialists=[], requires_advisor=False, question_type=follow_up
       (pure information delivery; no desk needs to run.)

  Prior brief exists, user: "stratejiyi sıfırdan kurabilir misin, agresife döndüm"
    → specialists=[risk_profiler, portfolio, budget_coach, market_data]
      requires_advisor=True, question_type=advisory
      (user explicitly wants a fresh plan — back to full lineup.)"""


_strategist_llm = None


def _get_strategist_llm():
    global _strategist_llm
    if _strategist_llm is None:
        _strategist_llm = get_llm().with_structured_output(ExecutionPlan)
    return _strategist_llm


def _keyword_fallback_plan(
    user_text: str, has_prior_context: bool = False
) -> ExecutionPlan:
    """Used only if the structured-output LLM call fails."""
    text = (user_text or "").lower().strip()
    chosen: list[SpecialistName] = []

    # Crude follow-up detection: short acknowledgement + prior context exists.
    short = len(text) < 60
    ack_words = ("tamam", "ok ", "okay", "evet", "anladım", "anladim", "yes ")
    follow_up = has_prior_context and (
        short and any(text.startswith(w) or text == w.strip() for w in ack_words)
    )

    advisory = (not follow_up) and any(
        k in text
        for k in (
            "öner", "tavsiye", "ne yap", "ne alm", "ne satayım", "recommend",
            "should i", "what should", "dengeli mi", "tahsis", "allocation",
            "plan", "strateji",
        )
    )
    if any(k in text for k in ("portföy", "portfolio", "holding", "elimde", "varlığım")):
        chosen.append("portfolio")
    if any(k in text for k in ("harcama", "bütçe", "budget", "spend", "saving", "tasarruf")):
        chosen.append("budget_coach")
    if any(k in text for k in ("haber", "news", "söylenti", "sentiment", "trend")):
        chosen.append("news_sentiment")
    if any(k in text for k in ("risk", "profil")):
        chosen.append("risk_profiler")
    if any(k in text for k in ("pdf", "ekstre", "statement", "dekont", "fatura")):
        chosen.append("document_parser")
    if advisory or not chosen:
        # Default exposure to market_data for advisory or unclear queries.
        if "market_data" not in chosen:
            chosen.append("market_data")
    if advisory:
        for needed in ("budget_coach", "risk_profiler", "portfolio"):
            if needed not in chosen:
                chosen.append(needed)  # type: ignore[arg-type]

    if follow_up:
        q_type: QuestionType = "follow_up"
    elif advisory:
        q_type = "advisory"
    else:
        q_type = "lookup"

    return ExecutionPlan(
        specialists=chosen[:6],
        requires_advisor=advisory,
        question_type=q_type,
        rationale="keyword fallback (LLM unavailable)",
        confidence=0.4,
    )


def _last_user_text(messages: list) -> str:
    for m in reversed(messages or []):
        if isinstance(m, HumanMessage):
            return normalize_content(getattr(m, "content", ""))
    return ""


def _extract_recent_turns(messages: list, k: int = 3) -> list[dict[str, str]]:
    """Return the last ``k`` COMPLETED user/assistant turn pairs (oldest → newest).

    "Completed" = a user message followed by at least one AI message before
    the next user message. The synthesizer reply is the LAST AI message in
    that span (intermediate specialist outputs are in there too but we only
    surface the final user-facing reply).

    The current (in-flight) turn — the trailing HumanMessage with no AI
    reply yet — is excluded so the strategist focuses on it separately.
    """
    if not messages:
        return []

    # Find every HumanMessage index in order.
    human_idxs = [i for i, m in enumerate(messages) if isinstance(m, HumanMessage)]
    if not human_idxs:
        return []

    turns: list[dict[str, str]] = []
    # Iterate over all but the last HumanMessage (that one is the current turn).
    for i in range(len(human_idxs) - 1):
        start = human_idxs[i]
        end = human_idxs[i + 1]  # exclusive
        user_text = normalize_content(getattr(messages[start], "content", "")).strip()
        # Last AI message strictly between this human and the next is the
        # synthesizer reply for that turn.
        assistant_text = ""
        for j in range(end - 1, start, -1):
            if isinstance(messages[j], AIMessage):
                assistant_text = normalize_content(
                    getattr(messages[j], "content", "")
                ).strip()
                break
        turns.append({"user": user_text, "assistant": assistant_text})

    return turns[-k:]


def _fetch_memory_hints(query: str, k: int = 3) -> list[dict[str, Any]]:
    """Run a semantic search over the user's past chats / decisions BEFORE
    the strategist plans, so the LLM knows about durable preferences ("I hate
    crypto", "tax residency TR") that would otherwise require an explicit
    memory-agent fan-out.

    Best-effort: any failure (no collection, ChromaDB hiccup) returns [] —
    the planner still runs normally without hints.
    """
    text = (query or "").strip()
    if not text:
        return []
    try:
        from app.tools.memory_tools import query_memory
        hits = query_memory.invoke({"text": text, "k": k}) or []
        if not isinstance(hits, list):
            return []
        cleaned: list[dict[str, Any]] = []
        for h in hits:
            if not isinstance(h, dict):
                continue
            snippet = (h.get("text") or "").strip()
            if not snippet:
                continue
            cleaned.append({
                "text": snippet[:300] + ("…" if len(snippet) > 300 else ""),
                "metadata": h.get("metadata") or {},
            })
        return cleaned
    except Exception as exc:  # noqa: BLE001
        log.warning("memory hint fetch failed: %s", exc)
        return []


def _format_strategist_context(
    turns: list[dict[str, str]],
    prev_brief: dict[str, Any] | None,
    current_query: str,
    memory_hints: list[dict[str, Any]] | None = None,
) -> str:
    """Build the human-message payload for the strategist LLM."""
    lines: list[str] = []

    if turns:
        lines.append("RECENT CONVERSATION (oldest → newest, EXCLUDES the current message):")
        for i, t in enumerate(turns, 1):
            u = t["user"][:400] + ("…" if len(t["user"]) > 400 else "")
            a = t["assistant"][:500] + ("…" if len(t["assistant"]) > 500 else "")
            lines.append(f"\n[turn -{len(turns) - i + 1}]")
            lines.append(f"  USER: {u}")
            lines.append(f"  ASSISTANT: {a or '(no reply on record)'}")
        lines.append("")
    else:
        lines.append("RECENT CONVERSATION: (this is the FIRST turn — no prior context)")
        lines.append("")

    if prev_brief:
        headline = (prev_brief.get("headline") or "").strip()
        allocation = prev_brief.get("allocation") or []
        if headline or allocation:
            lines.append("PREVIOUS INVESTMENT COMMITTEE BRIEF (still on the table):")
            if headline:
                lines.append(f"  headline: {headline[:300]}")
            if allocation:
                alloc_strs = []
                for band in allocation[:6]:
                    if isinstance(band, dict):
                        ac = band.get("asset_class", "?")
                        lo = band.get("weight_pct_low", "?")
                        hi = band.get("weight_pct_high", "?")
                        alloc_strs.append(f"{ac} {lo}-{hi}%")
                if alloc_strs:
                    lines.append("  allocation: " + " / ".join(alloc_strs))
            lines.append("")
    else:
        lines.append("PREVIOUS INVESTMENT COMMITTEE BRIEF: (none — no plan on the table yet)")
        lines.append("")

    if memory_hints:
        lines.append("DURABLE MEMORY HITS (semantic search over past conversations — may or may not be relevant):")
        for i, h in enumerate(memory_hints, 1):
            snippet = (h.get("text") or "").strip()
            if snippet:
                lines.append(f"  {i}. {snippet}")
        lines.append(
            "  → Use these only if they meaningfully constrain the answer "
            "(e.g. a stated preference, prior decision, or known fact about "
            "the user). Ignore otherwise."
        )
        lines.append("")

    lines.append(f"CURRENT USER MESSAGE:\n{current_query}")
    lines.append("\nDecide the plan now.")
    return "\n".join(lines)


def _resolve_risk_profile(state: AgentState) -> str:
    cached = state.get("risk_profile")
    if cached:
        return cached
    try:
        profile_data = get_user_profile.invoke({})
        return profile_data.get("risk_profile", "balanced")
    except Exception as exc:
        log.warning("strategist: failed to fetch risk_profile: %s", exc)
        return "balanced"


def _strategist_node(state: AgentState) -> dict[str, Any]:
    """Produce the execution plan and cache the risk profile."""
    messages = state.get("messages") or []
    user_text = _last_user_text(messages).strip()
    risk_profile = _resolve_risk_profile(state)
    recent_turns = _extract_recent_turns(messages, k=3)
    prev_brief = state.get("advisor_brief")
    # Proactive memory: pull durable preferences / facts from past turns BEFORE
    # planning so the strategist can route on them.
    memory_hints = _fetch_memory_hints(user_text, k=3) if user_text else []

    log.info("")
    log.info("┌── STRATEGIST ────────────────────────────────────────")
    log.info("│  user query   : %s", (user_text[:140] + "…") if len(user_text) > 140 else user_text)
    log.info("│  risk profile : %s", risk_profile)
    log.info("│  prior turns  : %d", len(recent_turns))
    log.info("│  prev brief   : %s", "yes" if prev_brief else "no")
    log.info("│  memory hints : %d", len(memory_hints))

    if not user_text:
        log.info("│  decision     : empty query → memory fallback")
        log.info("└──────────────────────────────────────────────────────")
        return {
            "plan": ExecutionPlan(
                specialists=["memory"],
                requires_advisor=False,
                question_type="lookup",
                rationale="empty query fallback",
            ).model_dump(),
            "risk_profile": risk_profile,
            "memory_hints": memory_hints,
            "next_action": "memory",
            # Clear findings so the previous turn's findings don't leak into
            # this turn's advisor / synthesizer.
            "findings": {RESET_SENTINEL: True},
            "agents_consulted": None,
            "citations": None,
            # advisor_brief deliberately NOT reset — when this turn has no
            # advisor, the prior brief still represents "the plan on the
            # table" and the synthesizer is allowed to reference it.
        }

    payload = _format_strategist_context(recent_turns, prev_brief, user_text, memory_hints)

    plan: ExecutionPlan
    try:
        plan = _get_strategist_llm().invoke(
            [SystemMessage(content=STRATEGIST_PROMPT), HumanMessage(content=payload)]
        )
    except Exception as exc:
        log.warning("strategist LLM call failed (%s) — using keyword fallback", exc)
        plan = _keyword_fallback_plan(
            user_text, has_prior_context=bool(recent_turns or prev_brief)
        )

    # Dedupe and validate specialist list against AGENT_NODES.
    seen: set[str] = set()
    cleaned: list[str] = []
    for name in plan.specialists:
        if name in AGENT_NODES and name not in seen:
            seen.add(name)
            cleaned.append(name)
    plan = plan.model_copy(update={"specialists": cleaned})

    log.info("│  specialists  : %s", cleaned or "(none)")
    log.info("│  advisor      : %s", plan.requires_advisor)
    log.info("│  question_type: %s", plan.question_type)
    log.info("│  confidence   : %.2f", plan.confidence)
    log.info("│  rationale    : %s", plan.rationale)
    log.info("└──────────────────────────────────────────────────────")

    # Low-confidence + nothing memory-related was already routed → silently
    # add the memory desk so the synthesizer has more to work with. This is
    # cheap (one ReAct turn against ChromaDB) and avoids re-prompting.
    if plan.confidence < 0.6 and "memory" not in cleaned and len(cleaned) < 6:
        cleaned.append("memory")
        plan = plan.model_copy(update={"specialists": cleaned})
        log.info("   (low-confidence rescue) appended memory desk → %s", cleaned)

    return {
        "plan": plan.model_dump(),
        "risk_profile": risk_profile,
        "memory_hints": memory_hints,
        "next_action": "FAN_OUT" if cleaned else FINISH,
        # Reset turn-local accumulators so stale entries from prior turns
        # don't leak into the advisor / synthesizer this turn.
        "findings": {RESET_SENTINEL: True},
        "agents_consulted": None,
        "citations": None,
        # See above: advisor_brief is deliberately not reset.
    }


# ── Routing ──────────────────────────────────────────────────────────────────


def _dispatch_from_strategist(state: AgentState) -> list[Send] | str:
    """Fan out to every specialist named in the plan (in parallel)."""
    plan = state.get("plan") or {}
    specialists: list[str] = plan.get("specialists") or []
    if not specialists:
        # No specialist needed → go straight to gather (which will route to synthesizer).
        return GATHER_NODE
    return [Send(name, state) for name in specialists if name in AGENT_NODES]


def _gather_node(state: AgentState) -> dict[str, Any]:
    """Sync barrier after parallel specialist execution. Pure passthrough —
    LangGraph waits here until every parallel branch has finished."""
    findings = state.get("findings") or {}
    log.info("gather: findings collected from %s", list(findings.keys()))
    return {}


def _route_after_gather(state: AgentState) -> str:
    plan = state.get("plan") or {}
    if plan.get("requires_advisor"):
        return ADVISOR_NODE
    return SYNTHESIZER_NODE


# ── Error wrapping ───────────────────────────────────────────────────────────


def _wrap_specialist(name: str, fn):
    """Catch exceptions inside a specialist; surface as structured findings."""
    async def wrapped(state: AgentState) -> AgentState:
        try:
            return await fn(state)
        except Exception as exc:  # noqa: BLE001
            log.exception("specialist %s raised — surfacing as findings error", name)
            err_payload = {
                "agent": name,
                "type": type(exc).__name__,
                "message": str(exc),
            }
            return {
                "findings": {
                    name: {
                        "summary": f"(error: {type(exc).__name__}: {exc})",
                        "tool_calls": [],
                        "extra": {"error": True},
                        # Structured per-agent error so the advisor /
                        # synthesizer can degrade gracefully instead of
                        # exploding when one desk fails.
                        "error": err_payload,
                    }
                },
                "agents_consulted": [name],
                "error": err_payload,
            }
    return wrapped


def _wrap_synth_or_advisor(name: str, fn):
    """Catch exceptions for synthesizer / advisor (single-instance nodes)."""
    async def wrapped(state: AgentState) -> AgentState:
        try:
            return await fn(state)
        except Exception as exc:  # noqa: BLE001
            log.exception("node %s raised", name)
            return {
                "error": {
                    "agent": name,
                    "type": type(exc).__name__,
                    "message": str(exc),
                }
            }
    return wrapped


# ── Graph build ──────────────────────────────────────────────────────────────


def build_supervisor(checkpointer=None):
    """Compile the FinCoach Capital graph.

    Edges:
        START → strategist
        strategist → Send(...specialists)   (conditional fan-out)
        each specialist → gather
        gather → advisor OR synthesizer     (conditional)
        advisor → synthesizer
        synthesizer → END
    """
    graph = StateGraph(AgentState)

    graph.add_node(STRATEGIST_NODE, _strategist_node)
    for name, fn in AGENT_NODES.items():
        graph.add_node(name, _wrap_specialist(name, fn))
    graph.add_node(GATHER_NODE, _gather_node)
    graph.add_node(ADVISOR_NODE, _wrap_synth_or_advisor(ADVISOR_NODE, advisor.run))
    graph.add_node(SYNTHESIZER_NODE, _wrap_synth_or_advisor(SYNTHESIZER_NODE, synthesizer.run))

    graph.add_edge(START, STRATEGIST_NODE)

    # Strategist fans out (Send) or routes straight to gather.
    graph.add_conditional_edges(
        STRATEGIST_NODE,
        _dispatch_from_strategist,
        [*AGENT_NODES.keys(), GATHER_NODE],
    )
    # Each specialist edges to the gather barrier.
    for name in AGENT_NODES:
        graph.add_edge(name, GATHER_NODE)

    # Gather → advisor or synthesizer.
    graph.add_conditional_edges(
        GATHER_NODE,
        _route_after_gather,
        {ADVISOR_NODE: ADVISOR_NODE, SYNTHESIZER_NODE: SYNTHESIZER_NODE},
    )

    graph.add_edge(ADVISOR_NODE, SYNTHESIZER_NODE)
    graph.add_edge(SYNTHESIZER_NODE, END)

    return graph.compile(checkpointer=checkpointer)
