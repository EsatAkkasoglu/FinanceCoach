"""Shared helpers used by every specialist agent.

Currently exposes ``extract_tool_calls`` — pulls the list of tools an agent
invoked during its run so the chat endpoint can surface them as citation
chips in the UI.
"""
from __future__ import annotations

from typing import Any


def extract_tool_calls(messages: list) -> list[dict[str, Any]]:
    """Walk the message history a ReAct agent produced and pull every
    ``tool_call`` it issued. Each entry is a small JSON-friendly dict the
    frontend renders as a citation chip.

    LangChain stores tool calls on AIMessage in two slightly different
    shapes depending on provider; we handle both.
    """
    out: list[dict[str, Any]] = []
    for msg in messages:
        # New LangChain format: AIMessage.tool_calls is a list[dict]
        tool_calls = getattr(msg, "tool_calls", None) or []
        for tc in tool_calls:
            if isinstance(tc, dict):
                name = tc.get("name") or tc.get("function", {}).get("name")
                args = tc.get("args") or tc.get("arguments") or {}
            else:
                name = getattr(tc, "name", None)
                args = getattr(tc, "args", None) or {}
            if name:
                out.append({"tool": name, "args": args})
    return out
