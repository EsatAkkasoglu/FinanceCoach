"""Supervisor graph wires the 7 specialist agents into a single LangGraph.

Routing strategy (LLM-first with keyword fallback):
1. Try Gemini with structured output to pick the best agent.
2. If that fails (rate limit, API error, parse error), fall back to a
   keyword router. The fallback also catches obvious-intent queries fast
   when the LLM is unavailable.

The single-agent dispatch is intentionally simple for this prototype.
Multi-agent parallel orchestration ("Should I buy NVDA?" → market_data +
portfolio + news in parallel) is a future-step improvement once we have
demo data + an explainability panel to render the merged answer.
"""
from __future__ import annotations

import logging
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from app.agents.state import AgentState
from app.agents.llm import get_llm
from app.agents import (
    market_data, portfolio, budget_coach, news_sentiment,
    risk_profiler, memory, document_parser,
)

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


class RouteDecision(BaseModel):
    agent: AgentName = Field(..., description="The single best specialist for this query")
    reason: str = Field(..., description="One short sentence (max 15 words) explaining the pick")


ROUTER_SYSTEM_PROMPT = """You are the supervisor of a multi-agent finance assistant. Pick EXACTLY ONE specialist to handle the user's message.

Specialists and what they do:

- market_data
    Prices, technicals, 8-dim analysis. Covers US stocks, crypto, ETFs,
    indices, commodities, forex, Treasury yields, AND Turkish TEFAS mutual
    & pension funds. Examples:
      "BTC price", "should I buy NVDA?", "altın fonu fiyatı",
      "S&P 500 nedir", "USD/TRY", "AFA fonunun getirisi",
      "en iyi performans gösteren fonlar", "hisse fonları nedir"

- portfolio
    The user's OWN holdings, performance, sector concentration, drift.
    Triggered by "my portfolio", "my holdings", "what do I own",
    "portföyüm", "elimdeki".

- budget_coach
    Spending, saving rate, categorization, cash-flow projections.
    Examples: "how much did I spend last month", "harcamalarım",
    "tasarruf önerisi".

- news_sentiment
    Headlines, trending tickers (hot scanner), early M&A/insider rumors.
    Examples: "what's trending", "any news on TSLA", "söylentiler".

- risk_profiler
    Risk score / profile read or update, retake the risk quiz.
    Examples: "what's my risk profile", "risk skorum nedir".

- document_parser
    Used only when the user explicitly references a PDF / bank statement
    they want parsed. Almost never the right choice for a chat question.

- memory
    Last resort fallback. Use only when:
      • The user is asking what they previously said or decided
      • The query is genuinely unclear and none of the above fit

ROUTING RULES:
- Match by INTENT, not by language. Turkish, English, or mixed all valid.
- Asset prices/fund queries → market_data (NOT memory).
- "Hangileri var", "neler var", "listele" + asset class → market_data.
- Default to market_data for any market/asset question; default to
  budget_coach for personal cash-flow questions.
- Use memory only when the user references prior conversation."""


_router_llm = None


def _get_router_llm():
    """Lazy structured-output binding so module import doesn't require API key."""
    global _router_llm
    if _router_llm is None:
        _router_llm = get_llm().with_structured_output(RouteDecision)
    return _router_llm


def _llm_route(user_text: str) -> RouteDecision | None:
    """Single LLM call with structured output. Returns None on any failure
    so the caller can fall through to the keyword router."""
    try:
        return _get_router_llm().invoke(
            [SystemMessage(content=ROUTER_SYSTEM_PROMPT), HumanMessage(content=user_text)]
        )
    except Exception as exc:
        log.warning("LLM routing failed: %s — falling back to keywords", exc)
        return None


def _keyword_route(user_text: str) -> str:
    """Heuristic fallback. Order matters — more-specific intents first so
    they don't get swallowed by the broad market_data bucket."""
    text = user_text.lower()

    # Specific intents first
    if any(k in text for k in ("portfolio", "holdings", "diversif", "allocation", "portföy", "elimde", "varlığım")):
        return "portfolio"
    if any(k in text for k in ("spend", "budget", "saving", "expense", "harcama", "bütçe", "tasarruf", "gelir", "gider")):
        return "budget_coach"
    if any(k in text for k in ("news", "trending", "rumor", "headline", "sentiment", "haber", "söylenti", "trend")):
        return "news_sentiment"
    if any(k in text for k in ("risk", "quiz", "profile", "profil")):
        return "risk_profiler"
    if any(k in text for k in ("statement", "pdf", "receipt", "upload", "ekstre", "dekont", "fatura")):
        return "document_parser"
    # Market data — broad set, last specific check (excludes ambiguous "ne kadar")
    market_kw = (
        "price", "buy", "sell", "ticker", "stock", "crypto", "etf", "fund",
        "index", "yield", "fiyat", "fon", "hisse", "kripto", "endeks",
        "altın", "gümüş", "petrol", "dolar", "euro", "nasdaq", "s&p",
        "bist", "borsa",
    )
    if any(k in text for k in market_kw):
        return "market_data"
    # Default to market_data — most app questions are market-related
    return "market_data"


def _supervisor_node(state: AgentState) -> AgentState:
    """Pick the next agent. LLM first, keyword fallback if it fails."""
    last_msg = state.get("messages", [{}])[-1] if state.get("messages") else None
    user_text = (getattr(last_msg, "content", "") or "").strip()
    if not user_text:
        return {"agent": "memory"}

    decision = _llm_route(user_text)
    if decision is not None:
        log.info("supervisor → %s  (%s)", decision.agent, decision.reason)
        return {"agent": decision.agent}

    fallback = _keyword_route(user_text)
    log.info("supervisor → %s  (keyword fallback)", fallback)
    return {"agent": fallback}


def _route(state: AgentState) -> str:
    return state.get("agent", "market_data")


def build_supervisor(checkpointer=None):
    """Build and compile the LangGraph supervisor.

    Pass a checkpointer instance (e.g. AsyncSqliteSaver) to enable persistent
    conversation memory. If None, the graph runs stateless (history lost on restart).
    """
    graph = StateGraph(AgentState)

    graph.add_node("supervisor", _supervisor_node)
    for name, fn in AGENT_NODES.items():
        graph.add_node(name, fn)

    graph.add_edge(START, "supervisor")
    graph.add_conditional_edges("supervisor", _route, {name: name for name in AGENT_NODES})
    for name in AGENT_NODES:
        graph.add_edge(name, END)

    return graph.compile(checkpointer=checkpointer)
