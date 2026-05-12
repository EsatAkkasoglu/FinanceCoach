"""Shared TypedDict state passed between LangGraph nodes."""
from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langgraph.graph.message import add_messages


class AgentState(TypedDict, total=False):
    """State carried through the supervisor graph.

    Fields:
        messages    — running list of LangChain messages (auto-merged by add_messages)
        user_id     — current user (single-user prototype: always 1)
        risk_profile — user's risk profile (conservative/balanced/aggressive)
        agent       — which agent should run next (set by supervisor router)
        scratchpad  — free-form working memory between nodes
        citations   — tool calls the worker made (surfaced as chips in the UI).
                      Each entry: {tool, args, agent?}.
    """
    messages: Annotated[list, add_messages]
    user_id: int
    risk_profile: str
    agent: str
    scratchpad: dict[str, Any]
    citations: list[dict[str, Any]]
