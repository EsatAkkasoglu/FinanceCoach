"""Supervisor graph — true conductor / orchestrator pattern.

Flow per user turn:

    START → supervisor ──► agent ──► supervisor ──► agent ──► … ──► END
                  ▲                          │
                  └──────── loops back ──────┘

At every iteration, the supervisor is given:
  • The user's original question
  • Which specialists have already been consulted this turn
  • What each consulted specialist said back

It then makes ONE of two decisions:
  • Call another specialist (when more information is genuinely required)
  • FINISH (the consulted specialists have collectively answered the question)

A hard cap of MAX_AGENT_CALLS prevents infinite loops if the LLM keeps
asking for more data. Each supervisor decision is structured output, with a
keyword fallback used only for the FIRST decision when the LLM call fails.

Why this differs from a one-shot multi-agent dispatch (the previous design):
the loop pattern lets the supervisor *react* to what each specialist
returned. e.g. if portfolio comes back empty, it can skip news_sentiment
and finish early; if market_data flagged volatility, it can pull news.
"""
from __future__ import annotations

import logging
from typing import Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from app.agents.state import AgentState
from app.agents.llm import get_llm
from app.agents import (
    market_data, portfolio, budget_coach, news_sentiment,
    risk_profiler, memory, document_parser, synthesizer,
)
from app.tools.user_tools import get_user_profile

log = logging.getLogger("fincoach.supervisor")


AGENT_NODES = {
    "market_data": market_data.run,
    "portfolio": portfolio.run,
    "budget_coach": budget_coach.run,
    "news_sentiment": news_sentiment.run,
    "risk_profiler": risk_profiler.run,
    "memory": memory.run,
    "document_parser": document_parser.run,
}

AgentName = Literal[
    "market_data",
    "portfolio",
    "budget_coach",
    "news_sentiment",
    "risk_profiler",
    "document_parser",
    "memory",
]

NextAction = Literal[
    "market_data",
    "portfolio",
    "budget_coach",
    "news_sentiment",
    "risk_profiler",
    "document_parser",
    "memory",
    "FINISH",
]

FINISH = "FINISH"
SYNTHESIZER_NODE = "synthesizer"
MAX_AGENT_CALLS = 4   # hard cap on agent calls per turn


class SupervisorDecision(BaseModel):
    """Supervisor's choice at each loop iteration."""
    next_action: NextAction = Field(
        description=(
            "Either a specialist name to call next, or 'FINISH' to end the turn. "
            "Use FINISH the moment the consulted specialists have collectively "
            "answered every part of the user's question."
        )
    )
    reasoning: str = Field(
        description="One short sentence (max 25 words): what's still missing or why we're done."
    )


SUPERVISOR_PROMPT = """\
You are the orchestrator of a multi-agent finance assistant.

At every step you see:
  • The user's original question
  • Which specialists you have already consulted this turn (if any)
  • What each consulted specialist replied

Your job is ONE decision per step:
  • Call ONE more specialist to gather missing information, OR
  • FINISH — every distinct part of the question has been addressed by its DEDICATED specialist.

EACH SPECIALIST OWNS EXACTLY ONE DOMAIN. Their reply is authoritative ONLY for that domain:

  market_data        Real-time prices, technicals, fund performance — any asset.
  portfolio          The user's OWN holdings, positions, P&L, allocation.
  budget_coach       The user's spending, savings rate, cash-flow history.
  news_sentiment     Recent market news, headlines, sentiment, trending tickers.
  risk_profiler      The user's risk score and profile (conservative / balanced / aggressive).
  document_parser    Content from PDFs / bank statements the user uploaded.
  memory             What was said in earlier conversations (rarely needed).

CRITICAL RULE — DOMAIN AUTHORITY:
A specialist's reply COUNTS as an answer only for ITS OWN domain. If a specialist
strays into another domain (e.g. the portfolio agent adds news commentary, or the
news agent comments on portfolio holdings), that off-topic content is NOT a real
answer for the other domain. You MUST still call the dedicated specialist for it.

DECOMPOSE THE USER QUESTION:
First, identify every distinct domain the question touches. Examples:
  "NVDA düştü, portföyümde var mı ve son haberler ne?" →
       part 1: do I own NVDA?         → portfolio
       part 2: latest news on NVDA?   → news_sentiment
       (you must call BOTH — portfolio's casual news mention does NOT cover part 2)
  "BTC fiyatı kaç?" → just market_data (single domain).
  "Risk profilim ne ve portföyüm dengeli mi?" → risk_profiler + portfolio.

DECISION RULES:
  • Walk through every part of the user's question. For each part, has its
    DEDICATED specialist been called? If not, call it next.
  • Never call a specialist already in the "consulted" list.
  • Off-topic commentary from a wrong specialist is IGNORED — does not satisfy any part.
  • FINISH only when every part has been covered by its dedicated specialist
    (or when no more specialists can help).
"""


_decision_llm = None


def _get_decision_llm():
    global _decision_llm
    if _decision_llm is None:
        _decision_llm = get_llm().with_structured_output(SupervisorDecision)
    return _decision_llm


def _normalize_content(content) -> str:
    """Flatten LangChain content (str or list-of-parts) into plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for p in content:
            if isinstance(p, str):
                parts.append(p)
            elif isinstance(p, dict) and isinstance(p.get("text"), str):
                parts.append(p["text"])
        return "".join(parts)
    return str(content) if content is not None else ""


def _collect_this_turn(messages: list, consulted: list[str]) -> tuple[str, list[tuple[str, str]]]:
    """Return (user_query, [(agent_name, agent_reply), ...]) for the CURRENT turn.

    "Current turn" = everything after the most recent HumanMessage.
    Agent replies are matched to `consulted` positionally — i-th reply was produced
    by consulted[i] (since each agent's run() returns exactly one final AIMessage).
    """
    # Find the last HumanMessage
    last_human_idx = -1
    for i in range(len(messages) - 1, -1, -1):
        if isinstance(messages[i], HumanMessage):
            last_human_idx = i
            break

    user_query = ""
    if last_human_idx >= 0:
        user_query = _normalize_content(getattr(messages[last_human_idx], "content", ""))

    # Build a positional reply list keyed off `consulted`. If an agent ran
    # but produced empty content (e.g. tool errored, API key missing), record
    # "(no reply)" so the supervisor still knows the agent was tried and
    # doesn't pick it again.
    replies: list[tuple[str, str]] = []
    if last_human_idx >= 0:
        ai_after = [m for m in messages[last_human_idx + 1:] if isinstance(m, AIMessage)]
        for i, agent_name in enumerate(consulted):
            text = ""
            if i < len(ai_after):
                text = _normalize_content(getattr(ai_after[i], "content", "")).strip()
            replies.append((agent_name, text or "(no reply produced)"))

    return user_query.strip(), replies


def _format_supervisor_input(user_query: str, replies: list[tuple[str, str]]) -> str:
    """Build the human-message payload the supervisor LLM sees."""
    lines: list[str] = [f"USER QUESTION:\n{user_query}", ""]

    if not replies:
        lines.append("CONSULTED SPECIALISTS: (none yet — this is the first decision)")
    else:
        lines.append(f"CONSULTED SPECIALISTS ({len(replies)}):")
        for name, reply in replies:
            snippet = reply[:1200] + ("…" if len(reply) > 1200 else "")
            lines.append(f"\n── [{name}] replied ──\n{snippet}")

    lines.append("\nDecide: call ONE more specialist, or FINISH.")
    return "\n".join(lines)


def _decide(user_query: str, replies: list[tuple[str, str]]) -> SupervisorDecision | None:
    """One supervisor LLM call. Returns None on failure (caller handles fallback)."""
    try:
        payload = _format_supervisor_input(user_query, replies)
        return _get_decision_llm().invoke(
            [SystemMessage(content=SUPERVISOR_PROMPT), HumanMessage(content=payload)]
        )
    except Exception as exc:
        log.warning("supervisor LLM call failed: %s — caller will fall back", exc)
        return None


def _keyword_first_pick(user_text: str) -> str:
    """Heuristic for the very first decision when the LLM call fails."""
    text = user_text.lower()
    if any(k in text for k in ("portfolio", "holdings", "portföy", "elimde", "varlığım")):
        return "portfolio"
    if any(k in text for k in ("spend", "budget", "saving", "harcama", "bütçe", "tasarruf")):
        return "budget_coach"
    if any(k in text for k in ("news", "haber", "söylenti", "trend", "sentiment")):
        return "news_sentiment"
    if any(k in text for k in ("risk", "profil", "quiz")):
        return "risk_profiler"
    if any(k in text for k in ("pdf", "ekstre", "dekont", "statement", "fatura")):
        return "document_parser"
    return "market_data"


def _supervisor_node(state: AgentState) -> AgentState:
    """One iteration of the orchestrator loop."""
    messages = state.get("messages") or []
    last_msg = messages[-1] if messages else None
    is_new_turn = isinstance(last_msg, HumanMessage)

    # Reset per-turn state on a fresh user message.
    if is_new_turn:
        consulted: list[str] = []
    else:
        consulted = list(state.get("agents_consulted") or [])

    # Cache risk profile once per turn so downstream agents see it.
    risk_profile = state.get("risk_profile")
    if not risk_profile:
        try:
            # user_id is read from the request-scoped ContextVar inside the tool.
            profile_data = get_user_profile.invoke({})
            risk_profile = profile_data.get("risk_profile", "balanced")
        except Exception as exc:
            log.warning("supervisor: failed to fetch risk_profile: %s", exc)
            risk_profile = "balanced"

    user_query, replies = _collect_this_turn(messages, consulted)
    iteration = len(consulted) + 1

    log.info("")
    log.info("┌── SUPERVISOR iteration #%d ─────────────────────────────", iteration)
    log.info("│  user query : %s", (user_query[:140] + "…") if len(user_query) > 140 else user_query)
    log.info("│  consulted  : %s", consulted or "(none)")
    log.info("│  replies    : %d collected", len(replies))
    for name, reply in replies:
        snippet = reply[:100].replace("\n", " ")
        log.info("│    └─ [%s] %s…", name, snippet)

    # Empty query → memory fallback (matches prior behavior).
    if not user_query:
        log.info("│  decision   : memory (empty query fallback)")
        log.info("└────────────────────────────────────────────────────────")
        return {
            "next_action": "memory",
            "agents_consulted": consulted + ["memory"],
            "risk_profile": risk_profile,
        }

    # Hard cap on agent calls per turn.
    if len(consulted) >= MAX_AGENT_CALLS:
        log.info("│  decision   : FINISH (hit MAX_AGENT_CALLS=%d)", MAX_AGENT_CALLS)
        log.info("└────────────────────────────────────────────────────────")
        return {"next_action": FINISH, "agents_consulted": consulted, "risk_profile": risk_profile}

    decision = _decide(user_query, replies)

    # LLM failed: keyword fallback (only meaningful for the first iteration).
    if decision is None:
        if not consulted:
            picked = _keyword_first_pick(user_query)
            log.info("│  decision   : %s (keyword fallback, LLM unavailable)", picked)
            log.info("└────────────────────────────────────────────────────────")
            return {
                "next_action": picked,
                "agents_consulted": consulted + [picked],
                "risk_profile": risk_profile,
            }
        log.info("│  decision   : FINISH (LLM unavailable mid-loop)")
        log.info("└────────────────────────────────────────────────────────")
        return {"next_action": FINISH, "agents_consulted": consulted, "risk_profile": risk_profile}

    # Guard against the LLM picking an already-consulted agent.
    chosen = decision.next_action
    if chosen != FINISH and chosen in consulted:
        log.warning("│  LLM picked %s but it's already consulted → forcing FINISH", chosen)
        log.info("└────────────────────────────────────────────────────────")
        return {"next_action": FINISH, "agents_consulted": consulted, "risk_profile": risk_profile}

    log.info("│  decision   : %s", chosen)
    log.info("│  reasoning  : %s", decision.reasoning)
    log.info("└────────────────────────────────────────────────────────")

    if chosen == FINISH:
        return {"next_action": FINISH, "agents_consulted": consulted, "risk_profile": risk_profile}

    return {
        "next_action": chosen,
        "agents_consulted": consulted + [chosen],
        "risk_profile": risk_profile,
    }


def _route_from_supervisor(state: AgentState) -> str:
    """Conditional edge: 'FINISH' → synthesizer, else → that worker."""
    action = state.get("next_action") or FINISH
    if action == FINISH:
        return SYNTHESIZER_NODE
    return action if action in AGENT_NODES else SYNTHESIZER_NODE


def _strip_current_turn_replies(messages: list) -> list:
    """Keep prior conversation history but drop anything emitted by other
    workers in the CURRENT turn (everything after the last HumanMessage).
    Without this, the second specialist sees the first one's full answer
    and the model short-circuits — returning empty content with no tool
    calls because it thinks the question is already answered.
    """
    if not messages:
        return messages
    for i in range(len(messages) - 1, -1, -1):
        if isinstance(messages[i], HumanMessage):
            return messages[: i + 1]
    return messages


def _wrap_agent_for_errors(name: str, fn, *, isolate_turn: bool = True):
    """Catch exceptions inside an agent node and surface them as structured
    state instead of crashing the supervisor stream. Stack trace is logged
    server-side; the SSE layer turns the returned `error` dict into an
    `agent_error` event the UI can render.

    If ``isolate_turn`` is True (default — used for specialist workers), the
    wrapped function sees only history up to the current user question.
    The synthesizer needs every worker's reply, so it opts out.
    """
    async def wrapped(state: AgentState) -> AgentState:
        if isolate_turn:
            isolated = dict(state)
            isolated["messages"] = _strip_current_turn_replies(state.get("messages") or [])
            state = isolated
        try:
            return await fn(state)
        except Exception as exc:  # noqa: BLE001
            log.exception("agent %s raised — surfacing as agent_error", name)
            return {
                "error": {
                    "agent": name,
                    "type": type(exc).__name__,
                    "message": str(exc),
                }
            }
    return wrapped


def build_supervisor(checkpointer=None):
    """Compile the loop-pattern supervisor graph.

    Edges:
        START → supervisor
        supervisor → {each agent | END}   (conditional, by next_action)
        each agent → supervisor           (always loops back)
    """
    graph = StateGraph(AgentState)

    graph.add_node("supervisor", _supervisor_node)
    for name, fn in AGENT_NODES.items():
        graph.add_node(name, _wrap_agent_for_errors(name, fn))
    graph.add_node(
        SYNTHESIZER_NODE,
        _wrap_agent_for_errors(SYNTHESIZER_NODE, synthesizer.run, isolate_turn=False),
    )

    graph.add_edge(START, "supervisor")
    graph.add_conditional_edges(
        "supervisor",
        _route_from_supervisor,
        {**{name: name for name in AGENT_NODES}, SYNTHESIZER_NODE: SYNTHESIZER_NODE},
    )
    for name in AGENT_NODES:
        graph.add_edge(name, "supervisor")
    graph.add_edge(SYNTHESIZER_NODE, END)

    return graph.compile(checkpointer=checkpointer)
