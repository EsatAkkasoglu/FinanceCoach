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

from app.agents import (
    advisor,
    budget_coach,
    document_parser,
    market_data,
    memory,
    news_sentiment,
    portfolio,
    risk_profiler,
    synthesizer,
)
from app.agents._helpers import normalize_content
from app.agents.llm import get_llm
from app.agents.state import RESET_SENTINEL, AgentState
from app.settings import settings
from app.tools.goal_tools import list_user_goals
from app.tools.portfolio_tools import list_holdings
from app.tools.user_tools import get_user_profile

log = logging.getLogger("fincoach.strategist")

# Keep the per-turn user snapshot compact — summary holdings only, never
# transaction history, so carrying it through state stays cheap.
_MAX_SNAPSHOT_HOLDINGS = 12


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
                       Also does deterministic side-by-side comparison of
                       multiple tickers/funds ("X vs Y", "compare these").
    news_sentiment     Headlines, sentiment, trending tickers, rumors.
    document_parser    The ONLY desk that can read uploaded files (PDFs,
                       images, statements, trading notes). Use it for ANY
                       question whose answer may live in a previously
                       uploaded document — trade-setup levels
                       (entry / TP / SL), positions described in a Yayın
                       Notu, bank-statement line items, fund factsheet
                       figures, contents of any prior attachment. The
                       document text is NOT in chat history; this desk
                       re-queries the document index every turn, so
                       follow-up questions about a file attached many
                       turns ago still work. WHEN the strategist context
                       lists `UPLOADED DOCUMENTS` and the user's question
                       could plausibly be answered from one of them, the
                       desk MUST be in the specialist list (in any language).
  client desk:
    portfolio          The user's OWN holdings, weights, P&L, concentration.
                       Computes these deterministically (exact weights,
                       HHI concentration, allocation drift, risk metrics) —
                       so "how concentrated am I", "what's my real return"
                       resolve here with hard numbers.
    budget_coach       The user's spending, savings rate, investable surplus,
                       AND savings goals (target amount / date / progress /
                       monthly contribution needed). Computes exact goal
                       contributions and investment projections (compounded).
                       Any "am I on track for my goal", "how much should I
                       save per month to hit X", "what will X/month grow to",
                       "is my emergency fund enough" style question (in any
                       language) MUST include budget_coach in the specialist
                       list.
    risk_profiler      The user's risk score and profile label.
    memory             What was said in earlier conversations (rarely needed).

PLANNING RULES:
  • Decompose the user question into its information needs. For each, pick
    the SINGLE desk that owns it.
  • LIST EVERY desk that holds a piece of the answer — do NOT settle for one.
    "What do you recommend?" needs budget_coach + risk_profiler + portfolio +
    market_data (and usually news_sentiment for catalyst awareness). They
    run in parallel.
  • DIRECTIONAL / OUTLOOK questions — "will X go up/down", "is it in a down/
    up-trend", "olası düşüş/yükseliş", "düşer mi / yükselir mi", "what's the
    outlook" (any language) — dispatch BOTH market_data (price-action /
    technicals / derivatives) AND news_sentiment (catalysts). A directional
    call must be researched on price-action AND headlines, so the answer can
    say "technically X, and on the news side Y" — never one side alone.
  • For questions that DO require a fresh allocation plan (see the
    requires_advisor test below), default to the full lineup:
      [budget_coach, risk_profiler, portfolio, market_data, news_sentiment].
    For questions that DON'T (state checks, on-track questions, simple
    quantification, "is X too much"), pick the SINGLE owning desk. Adding
    extra desks here just bloats the response and tempts the synthesizer
    into a generic allocation table.
  • `requires_advisor` IS THE EXPENSIVE BIT. It triggers a full allocation
    framework with bands + drivers + key risks. Default it to FALSE and only
    flip to TRUE when the user is asking for a NEW PLAN OR ALLOCATION CHANGE.
    Apply this test: "If I answer this with just data and one sentence of
    judgment, is the user satisfied?" — if yes, advisor is NOT needed.

    advisor=TRUE looks like (in any language):
      - "What should I buy / how should I build my portfolio / suggest an
         allocation"
      - "Rebuild my plan from scratch"
      - "How should I deploy this cash"
      - "Is my portfolio balanced"

    advisor=FALSE (data + judgment, no new framework):
      - "Am I on track for my goal" → state question
      - "If I keep this pace, is it enough" → state question
      - "How much should I save per month" → quantification, not strategy
      - "Is my BTC weight too high" → judgment but no NEW plan needed
      - "Show my portfolio / my spending"

    The synthesizer can still deliver pointed judgment without advisor —
    triggering advisor unnecessarily produces a canned allocation-table
    response the user did not ask for and damages the chat UX.
  • `requires_advisor=False` for pure lookups and pure state reports. The
    user just wants the data; no synthesis needed.
  • Memory desk is usually skipped unless the user references prior turns.

  • CRITICAL — DO NOT TRIGGER ADVISOR FOR GOAL-PROGRESS QUESTIONS.
    Questions like "am I on track", "will I reach my goal in time",
    "is what I'm saving enough", "on pace?" (in any language) are STATE
    REPORTS about a goal — not requests for an allocation plan. Route
    ONLY to budget_coach with requires_advisor=False,
    question_type=client_state. Triggering the advisor here produces a
    generic strategic-allocation table that the user did not ask for and
    feels canned.
    The ONLY trigger for advisor on goal questions is an explicit
    allocation / investment ask: "how should I INVEST for my goal",
    "suggest an ALLOCATION", "build a STRATEGY", "rebuild my plan".

FOLLOW-UP DETECTION — READ THE PREVIOUS TURNS:
  You will receive recent conversation context (last 2-3 user/assistant turns
  + a snapshot of the previous Investment Committee brief headline if one
  exists). USE IT.

  A turn is a FOLLOW-UP when the user is acting on, refining, or confirming
  something already discussed — not asking a brand-new question. Signals
  apply in ANY language:
    • Acknowledgement / confirmation words ("ok", "yes", "sounds good",
      "got it", and their equivalents)
    • Action / execution language tied to prior content ("add these",
      "do that", "go ahead", "apply it")
    • A small refinement to the previous plan ("what about the bond side?",
      "could we use AGG instead of BND?")
    • Questions that pronoun-refer to the prior brief ("why that ratio?",
      "isn't that too much cash?")

  WHEN it's a follow-up:
    → question_type = "follow_up"
    → requires_advisor = FALSE  (the plan already exists; don't regenerate
       it). The only exception is if the user explicitly asks for a fresh
       plan ("let's start over", "rebuild the strategy").
    → specialists = the MINIMAL set needed to act on or answer the follow-up.
       Examples:
         • "ok, I bought 700 EUR of SCHD, add it"   → [portfolio]   (action on holdings)
         • "BND or AGG for the bond side?"          → [market_data] (compare two tickers)
         • "tax residency: TR"                      → []            (just info; no desk)
         • "isn't that too much cash?"              → [risk_profiler] (judgement, no full re-plan)
       Do NOT call the full 5-desk lineup again unless the user truly is
       asking for a new plan.

EXAMPLES (first-turn, no prior context — phrasings shown in English for
clarity; apply the same logic regardless of the user's language):
  "What's the BTC price?"
    → specialists=[market_data], requires_advisor=False, question_type=lookup

  "Pull up the latest Intel news"
    → specialists=[news_sentiment], requires_advisor=False, question_type=research

  "How's my portfolio?"
    → specialists=[portfolio], requires_advisor=False, question_type=client_state

  "How much should I save per month to hit my home down-payment goal?"
    → specialists=[budget_coach], requires_advisor=False, question_type=client_state

  "If I keep this pace, will I hit my home goal?"
  "Am I on track for my emergency fund?"
    → specialists=[budget_coach], requires_advisor=False, question_type=client_state
       (THIS IS NOT AN ADVISORY QUESTION. The user wants a yes/no + the gap.
       budget_coach alone has goals + cash-flow. Do NOT add risk_profiler,
       portfolio, or market_data — that triggers a generic allocation-table
       response. The advisor MUST NOT run.)

  "How should I invest to hit my home goal? Suggest an allocation."
  "Rebuild my strategy around this goal"
    → specialists=[budget_coach, risk_profiler, portfolio, market_data]
       requires_advisor=True, question_type=advisory
       (ONLY when the user explicitly asks for an allocation / investment plan.)

  "Given my total budget I want to buy funds and stocks. What do you recommend?"
    → specialists=[budget_coach, risk_profiler, portfolio, market_data, news_sentiment]
      requires_advisor=True, question_type=advisory

  "NVDA dropped — do I hold any and what's the latest news?"
    → specialists=[portfolio, news_sentiment, market_data]
      requires_advisor=False, question_type=mixed

  UPLOADED DOCUMENTS section lists `20.05.2026 - Yayın Notu.pdf`.
  User (turn 1): "SOL için giriş ve hedef seviyelerini göster"
  User (turn 5, no further attachment): "Doge coin için hangi pozisyon verilmiş?"
    → specialists=[document_parser], requires_advisor=False, question_type=lookup
       (Both questions resolve from the uploaded note. document_parser
       re-queries the index every turn; do NOT assume the doc text is in
       chat history. NEVER answer "no information about X" from chat
       memory alone when an uploaded document is listed and could contain X.)

EXAMPLES (with prior context — note how follow-up changes everything):
  Prior brief headline: balanced allocation recommendation for a conservative profile.
  User: "ok, I bought 700 EUR of SCHD and 300 EUR of JNJ, leave the rest as cash"
    → specialists=[portfolio], requires_advisor=False, question_type=follow_up
       (user is executing on the prior plan; call portfolio to record the
       holdings; do NOT re-run the full committee.)

  Prior assistant reply contained a fund/ticker allocation table (e.g. PHE 40%,
  CPT 30%, YIT 30% for 10.000 TL).
  User: "split the 10000 as you said above"
    → specialists=[portfolio], requires_advisor=False, question_type=follow_up
       (anaphoric reference to the prior allocation. The amounts/instruments
       are ALREADY in the prior assistant reply — portfolio agent reads the
       conversation and executes the buys. DO NOT route to budget_coach: the
       user is buying funds, not contributing to savings goals. "Split"
       here means split across the named instruments, not across goals.)

ANAPHORA RULE — when the user refers to a prior turn ("as discussed",
"like you said", "that allocation", "the one above", or any equivalent
in any language): resolve the referent by reading the most recent assistant reply.
  • If the referent is a fund/ticker allocation → specialists=[portfolio].
  • If the referent is a goal/contribution plan → specialists=[budget_coach].
  • If the referent is ambiguous, prefer the closer (most recent) match.
Never route the same "execute it" turn to BOTH portfolio and budget_coach —
that produces a reply where the money is double-counted (recorded as a buy
AND as a goal contribution).

  Prior brief exists.
  User: "for the bond side, can I use AGG instead of BND?"
    → specialists=[market_data], requires_advisor=False, question_type=follow_up

  Prior assistant reply asked about tax residency as an open question.
  User: "tax residency: Turkey"
    → specialists=[], requires_advisor=False, question_type=follow_up
       (pure information delivery; no desk needs to run.)

  Prior brief exists, user: "can you rebuild the strategy from scratch, I went aggressive"
    → specialists=[risk_profiler, portfolio, budget_coach, market_data]
      requires_advisor=True, question_type=advisory
      (user explicitly wants a fresh plan — back to full lineup.)"""


_strategist_llm = None


def _get_strategist_llm():
    global _strategist_llm
    if _strategist_llm is None:
        # Routing is a structured decision — run it near-deterministic so the
        # same question routes to the same desks every time.
        _strategist_llm = get_llm(
            settings.gemini_structured_temperature
        ).with_structured_output(ExecutionPlan)
    return _strategist_llm


def _keyword_fallback_plan(
    user_text: str,
    has_prior_context: bool = False,
    has_uploaded_documents: bool = False,
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
            "plan", "strategy", "strateji", "analyze", "analyse", "analysis",
            "what do you think", "is it good", "suitable", "uygun mu",
        )
    )
    if any(k in text for k in ("portföy", "portfolio", "holding", "elimde", "varlığım")):
        chosen.append("portfolio")
    if any(
        k in text
        for k in (
            "harcama", "bütçe", "budget", "spend", "saving", "tasarruf",
            "hedef", "goal", "biriktir", "peşinat", "acil fon",
            "emergency fund", "on track", "yolda", "yeter mi", "tempo",
        )
    ):
        chosen.append("budget_coach")
    if any(k in text for k in ("haber", "news", "söylenti", "sentiment", "trend")):
        chosen.append("news_sentiment")
    # Directional / outlook questions ("olası düşüş/yükseliş", "düşer mi", "rally",
    # "outlook") must combine BOTH the technical read AND news catalysts, so the
    # up/down call is researched on price-action AND headlines, never one alone.
    directional = any(
        k in text
        for k in (
            "düşüş", "yükseliş", "düşer", "yüksel", "düşecek", "yükselecek",
            "ralli", "rally", "drop", "fall", "pump", "rise", "selloff",
            "outlook", "beklenti", "olası", "yön", "hareket",
        )
    )
    if directional:
        if "news_sentiment" not in chosen:
            chosen.append("news_sentiment")
        if "market_data" not in chosen:
            chosen.append("market_data")
    if any(k in text for k in ("risk", "profil")):
        chosen.append("risk_profiler")
    # Explicit document keywords always pull in document_parser.
    if any(k in text for k in ("pdf", "ekstre", "statement", "dekont", "fatura")):
        chosen.append("document_parser")
    # If any document is indexed, route doc-flavoured questions there too.
    # Trade-setup vocabulary (entry / TP / SL / position / level) in any
    # language is a strong signal the user is asking about an attached note.
    elif has_uploaded_documents and any(
        k in text
        for k in (
            "tp", "sl", "stop", "hedef", "giriş", "giris", "entry",
            "pozisyon", "position", "seviye", "level", "long", "short",
            "yayın", "yayin", "not", "notu", "belge", "doküman", "dokuman",
            "dosya", "file", "document", "yüklediğim", "yukledigim",
            "uploaded", "ekledim",
        )
    ):
        chosen.append("document_parser")
    if advisory or not chosen:
        # Default exposure to market_data for advisory or unclear queries.
        if "market_data" not in chosen:
            chosen.append("market_data")
    if advisory:
        for needed in ("budget_coach", "risk_profiler", "portfolio", "market_data", "news_sentiment"):
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


def _fetch_uploaded_documents() -> list[dict[str, Any]]:
    """Best-effort enumeration of files indexed for the user, used to enrich
    the strategist context so it knows when to route to document_parser.

    Returns ``[{"filename": str, "chunks": int}, ...]`` (empty on failure).
    The call hits Chroma's local persistent client — cheap, no network.
    """
    try:
        from app.tools.document_tools import list_uploaded_documents
        hits = list_uploaded_documents.invoke({}) or []
        return hits if isinstance(hits, list) else []
    except Exception as exc:  # noqa: BLE001
        log.warning("uploaded-documents lookup failed: %s", exc)
        return []


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
    uploaded_documents: list[dict[str, Any]] | None = None,
    user_snapshot: dict[str, Any] | None = None,
) -> str:
    """Build the human-message payload for the strategist LLM."""
    lines: list[str] = []

    if turns:
        lines.append("RECENT CONVERSATION (oldest → newest, EXCLUDES the current message):")
        for i, t in enumerate(turns, 1):
            u = t["user"][:600] + ("…" if len(t["user"]) > 600 else "")
            a = t["assistant"][:1500] + ("…" if len(t["assistant"]) > 1500 else "")
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

    lines.extend(_format_snapshot_block(user_snapshot))

    if uploaded_documents:
        lines.append(
            "UPLOADED DOCUMENTS (already extracted and embedded — the "
            "document_parser desk can retrieve passages on demand; the text "
            "is NOT in chat history):"
        )
        for d in uploaded_documents[:8]:
            name = (d.get("filename") or "(unknown)").strip()
            chunks = d.get("chunks") or 0
            lines.append(f"  - {name} ({chunks} chunk(s) indexed)")
        lines.append(
            "  → If the current question may be answered from any of these "
            "files (trade levels, positions, statement line items, anything "
            "the user asked about a previously attached document), include "
            "document_parser in the specialist list."
        )
        lines.append("")
    else:
        lines.append("UPLOADED DOCUMENTS: (none — the user has not attached any files)")
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


def _fetch_portfolio_snapshot(risk_profile: str) -> dict[str, Any]:
    """Compact, turn-local picture of who the user is, fetched ONCE before
    planning so the strategist routes on real holdings/goals (and the advisor
    can read it from state).

    Deliberately CHEAP and summary-only — list_holdings + goal aggregates are
    single SQLite reads with NO live pricing and NO transaction history, so it
    runs every turn without latency/token cost. Live valuation + concentration
    are computed by the portfolio desk (compute_portfolio_summary) only when it
    is actually dispatched. Best-effort: never raises.
    """
    snap: dict[str, Any] = {"risk_profile": risk_profile}
    try:
        holdings = list_holdings.invoke({}) or []
        snap["holdings_count"] = len(holdings)
        snap["holdings"] = [
            {
                "ticker": h.get("ticker"),
                "asset_class": h.get("asset_class"),
                "quantity": h.get("quantity"),
                "avg_cost": h.get("cost_basis"),
                "currency": h.get("currency"),
            }
            for h in holdings[:_MAX_SNAPSHOT_HOLDINGS]
        ]
    except Exception as exc:  # noqa: BLE001
        log.info("snapshot: holdings fetch failed: %s", exc)
    try:
        goals = list_user_goals.invoke({})
        summary = goals.get("summary") if isinstance(goals, dict) else None
        if isinstance(summary, dict):
            snap["goals_summary"] = {
                "count": summary.get("count"),
                "total_remaining": summary.get("total_remaining"),
                "combined_monthly_needed": summary.get("combined_monthly_savings_needed"),
                "currency": summary.get("currency"),
            }
    except Exception as exc:  # noqa: BLE001
        log.info("snapshot: goals fetch failed: %s", exc)
    return snap


def _format_snapshot_block(snap: dict[str, Any] | None) -> list[str]:
    """Render the user snapshot into strategist-context lines (compact)."""
    if not snap:
        return []
    lines = ["USER SNAPSHOT (who you're planning for — summary only, no live prices):"]
    lines.append(f"  risk profile: {snap.get('risk_profile', 'balanced')}")
    holdings = snap.get("holdings") or []
    count = snap.get("holdings_count", len(holdings))
    if holdings:
        parts = []
        for h in holdings:
            tkr = h.get("ticker") or "?"
            qty = h.get("quantity")
            parts.append(f"{tkr}×{qty:g}" if isinstance(qty, (int, float)) else tkr)
        more = f" …(+{count - len(holdings)} more)" if count > len(holdings) else ""
        lines.append(f"  holdings ({count}): " + ", ".join(parts) + more)
    else:
        lines.append("  holdings: (none on file)")
    g = snap.get("goals_summary") or {}
    if g.get("count"):
        ccy = g.get("currency") or ""
        lines.append(
            f"  goals: {g.get('count')} active, ~{g.get('combined_monthly_needed')} {ccy}/mo needed, "
            f"{g.get('total_remaining')} {ccy} remaining"
        )
    lines.append("")
    return lines


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
    uploaded_documents = _fetch_uploaded_documents()
    user_snapshot = _fetch_portfolio_snapshot(risk_profile)

    log.info("")
    log.info("┌── STRATEGIST ────────────────────────────────────────")
    log.info("│  user query   : %s", (user_text[:140] + "…") if len(user_text) > 140 else user_text)
    log.info("│  risk profile : %s", risk_profile)
    log.info("│  prior turns  : %d", len(recent_turns))
    log.info("│  prev brief   : %s", "yes" if prev_brief else "no")
    log.info("│  memory hints : %d", len(memory_hints))
    log.info("│  uploaded docs: %d", len(uploaded_documents))
    log.info("│  snapshot     : %d holdings", user_snapshot.get("holdings_count", 0))

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
            "user_snapshot": user_snapshot,
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

    payload = _format_strategist_context(
        recent_turns, prev_brief, user_text, memory_hints, uploaded_documents,
        user_snapshot=user_snapshot,
    )

    plan: ExecutionPlan
    try:
        plan = _get_strategist_llm().invoke(
            [SystemMessage(content=STRATEGIST_PROMPT), HumanMessage(content=payload)]
        )
    except Exception as exc:
        log.warning("strategist LLM call failed (%s) — using keyword fallback", exc)
        plan = _keyword_fallback_plan(
            user_text,
            has_prior_context=bool(recent_turns or prev_brief),
            has_uploaded_documents=bool(uploaded_documents),
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
        "user_snapshot": user_snapshot,
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
