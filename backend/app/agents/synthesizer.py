"""Synthesizer — merges specialist outputs into a single coherent reply.

Runs after the supervisor decides every relevant specialist has been consulted.
Receives the user's question and each specialist's reply, then writes ONE
conversational answer in the user's language. The UI shows only this final
reply; specialist outputs stay internal, but their tool calls still surface
as citations under the synthesized message.
"""
from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.agents.llm import get_llm
from app.agents.state import AgentState

log = logging.getLogger("fincoach.synthesizer")


SYNTHESIZER_PROMPT = """\
You are the final response writer for FinCoach, a multi-agent finance assistant.

You receive:
  • The user's original question
  • Replies from one or more specialist agents (portfolio, market_data,
    news_sentiment, budget_coach, risk_profiler, document_parser, memory)
  • Some specialists may have returned an empty reply or an error

Your job: write ONE coherent, conversational answer that addresses every part
of the user's question.

Rules:
  • Reply in the SAME language the user wrote in (Turkish, English, …).
    Detect from the user question, not from specialist replies.
  • Speak with a single voice. DO NOT add section headers like "PORTFOLIO:"
    or "From the news agent:". Weave information together naturally.
  • Preserve key facts from specialist replies verbatim where they matter:
    numbers, tickers, prices, sentiment tags, source titles and URLs.
  • If a specialist returned nothing or errored, mention what couldn't be
    checked in one short clause and continue with what you have.
  • If the specialists fully covered the question, answer directly — no
    apologies, no hedging, no "I will now…".
  • Concise: 2–4 short paragraphs at most. No closing disclaimers about
    "this is not financial advice" — handled elsewhere.
"""


def _normalize_content(content: Any) -> str:
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


async def run(state: AgentState) -> AgentState:
    messages = state.get("messages") or []
    consulted: list[str] = state.get("agents_consulted") or []

    last_human_idx = -1
    for i in range(len(messages) - 1, -1, -1):
        if isinstance(messages[i], HumanMessage):
            last_human_idx = i
            break

    user_query = ""
    specialist_msgs: list[AIMessage] = []
    if last_human_idx >= 0:
        user_query = _normalize_content(messages[last_human_idx].content).strip()
        specialist_msgs = [
            m for m in messages[last_human_idx + 1:] if isinstance(m, AIMessage)
        ]

    sections: list[str] = []
    for i, agent_name in enumerate(consulted):
        reply = ""
        if i < len(specialist_msgs):
            reply = _normalize_content(specialist_msgs[i].content).strip()
        sections.append(
            f"--- [{agent_name}] ---\n{reply if reply else '(returned no reply)'}"
        )

    if not sections:
        sections.append("(no specialist replies — answer from general knowledge)")

    payload = (
        "USER QUESTION:\n" + user_query +
        "\n\nSPECIALIST REPLIES:\n\n" + "\n\n".join(sections)
    )

    response = await get_llm().ainvoke(
        [SystemMessage(content=SYNTHESIZER_PROMPT), HumanMessage(content=payload)]
    )
    return {"messages": [response]}
