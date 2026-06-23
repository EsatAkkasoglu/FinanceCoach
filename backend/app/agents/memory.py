"""Memory agent — RAG over the user's chat history and transactions.

Used as the supervisor's *fallback* node when intent is unclear, and also
to enrich other agents with relevant past context."""
from __future__ import annotations

from langgraph.prebuilt import create_react_agent

from app.agents._helpers import build_findings, extract_tool_calls, latest_human_turn
from app.agents.llm import get_llm
from app.agents.state import AgentState
from app.tools.memory_tools import query_memory

SYSTEM_PROMPT = """You are the Memory agent for FinCoach.

Tool:
- query_memory(text, k)  — semantic search over past chats and transactions

Strategy:
1. Call query_memory with the user's last message.
2. If results are found, quote the most relevant snippet verbatim with date.
3. If nothing is found, say so plainly and suggest the user be more specific.

Never fabricate memories. Two short paragraphs max."""


_agent = None


def _build_agent():
    return create_react_agent(get_llm(), tools=[query_memory], prompt=SYSTEM_PROMPT)


async def run(state: AgentState) -> AgentState:
    global _agent
    if _agent is None:
        _agent = _build_agent()
    result = await _agent.ainvoke({"messages": latest_human_turn(state.get("messages", []))})
    msgs = result["messages"]
    return {
        "messages": msgs[-1:],
        "citations": extract_tool_calls(msgs),
        "findings": {"memory": build_findings("memory", msgs)},
        "agents_consulted": ["memory"],
    }
