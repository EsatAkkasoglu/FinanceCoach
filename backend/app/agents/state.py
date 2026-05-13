"""Shared TypedDict state passed between LangGraph nodes."""
from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langgraph.graph.message import add_messages


class AgentState(TypedDict, total=False):
    """State carried through the supervisor graph.

    Fields:
        messages         — running list of LangChain messages (auto-merged by add_messages)
        user_id          — current user (single-user prototype: always 1)
        risk_profile     — user's risk profile (conservative/balanced/aggressive)
        next_action      — supervisor's last decision (agent name, or 'FINISH')
        agents_consulted — agents already called this turn, in order
        scratchpad       — free-form working memory between nodes
        citations        — tool calls the worker made (surfaced as chips in the UI)
        error            — structured error from the last worker (None on success)
    """
    messages: Annotated[list, add_messages]
    user_id: int
    risk_profile: str
    next_action: str
    agents_consulted: list[str]
    scratchpad: dict[str, Any]
    citations: list[dict[str, Any]]
    error: dict[str, Any] | None
