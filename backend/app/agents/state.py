"""Shared TypedDict state passed between LangGraph nodes."""
from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langgraph.graph.message import add_messages

RESET_SENTINEL = "__reset__"


def merge_findings(left: dict | None, right: dict | None) -> dict:
    """Reducer for the ``findings`` field.

    Specialists run in parallel and each returns ``{"findings": {<name>: {...}}}``.
    LangGraph merges parallel branches by calling this reducer once per branch
    with (accumulated, new). We do a shallow dict union — later writes from the
    same agent (rare) overwrite earlier ones.

    Reset semantics: passing ``{"__reset__": True}`` (or ``None``) replaces the
    accumulated value with an empty dict. Used by the strategist at the start
    of every turn so stale findings from prior turns don't leak forward.
    """
    if right is None or (isinstance(right, dict) and right.get(RESET_SENTINEL)):
        return {}
    if not left:
        return dict(right or {})
    if not right:
        return dict(left)
    out = dict(left)
    out.update(right)
    return out


def append_list(left: list | None, right: list | None) -> list:
    """Reducer that concatenates lists across parallel branches.

    Reset semantics: passing ``None`` clears the accumulated list.
    """
    if right is None:
        return []
    if not left:
        return list(right or [])
    if not right:
        return list(left)
    return [*left, *right]


def last_write_wins(left: Any, right: Any) -> Any:
    """Reducer that takes the latest non-None value.

    Used for scalar state fields that multiple parallel branches may write to
    (e.g. ``error``). The last branch to execute wins; None is treated as
    'no update' so a successful branch doesn't clear a prior error.
    """
    return right if right is not None else left


class AgentState(TypedDict, total=False):
    """State carried through the supervisor graph.

    Fields:
        messages         — running list of LangChain messages (auto-merged by add_messages)
        user_id          — current user (set per-request from the bearer token)
        risk_profile     — user's risk profile (conservative/balanced/aggressive)
        user_snapshot    — compact who-is-this-user snapshot (summary holdings +
                           goal aggregates + risk) built once per turn by the
                           strategist; no live prices, no transaction history
        plan             — strategist's execution plan for this turn
        memory_hints     — top-k semantic snippets from past turns, fetched
                           BEFORE planning to enrich the strategist's context
        findings         — per-agent structured output, merged across parallel branches
        advisor_brief    — advisor's allocation/plan framework (None if not needed)
        next_action      — kept for legacy SSE handler (no longer drives routing)
        agents_consulted — agents called this turn, in dispatch order
        scratchpad       — free-form working memory between nodes
        citations        — tool calls every worker made (merged for the UI)
        suggestions      — follow-up prompts the synthesizer crafted for this turn
        error            — structured error from the last worker (None on success)
    """
    messages: Annotated[list, add_messages]
    user_id: int
    risk_profile: Annotated[str, last_write_wins]
    user_snapshot: Annotated[dict[str, Any], last_write_wins]
    plan: Annotated[dict[str, Any], last_write_wins]
    memory_hints: Annotated[list[dict[str, Any]], last_write_wins]
    findings: Annotated[dict[str, Any], merge_findings]
    advisor_brief: Annotated[dict[str, Any] | None, last_write_wins]
    next_action: Annotated[str, last_write_wins]
    agents_consulted: Annotated[list[str], append_list]
    scratchpad: Annotated[dict[str, Any], last_write_wins]
    citations: Annotated[list[dict[str, Any]], append_list]
    suggestions: Annotated[list[str], last_write_wins]
    error: Annotated[dict[str, Any] | None, last_write_wins]
