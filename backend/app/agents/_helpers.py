"""Shared helpers used by every specialist agent.

Exposes:
  • ``extract_tool_calls`` — pull tool invocations from a ReAct agent's message
    history so they can be surfaced as citation chips in the UI.
  • ``normalize_content`` — flatten LangChain content (str or list-of-parts).
  • ``build_findings`` — wrap a specialist's run output into the structured
    ``findings`` entry the advisor and synthesizer consume.
"""
from __future__ import annotations

import json
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


def normalize_content(content: Any) -> str:
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


def _summarize_tool_output(output: Any, max_len: int = 600) -> Any:
    """Best-effort: keep dicts/lists structured; truncate strings."""
    if output is None:
        return None
    inner = getattr(output, "content", None)
    if inner is not None:
        output = inner
    if isinstance(output, (dict, list)):
        try:
            json.dumps(output, default=str)
            return output
        except (TypeError, ValueError):
            return str(output)[:max_len]
    text = str(output).strip()
    return text[:max_len] + ("…" if len(text) > max_len else "")


def collect_tool_results(messages: list) -> list[dict[str, Any]]:
    """Pair each tool_call with its tool result (from following ToolMessage).

    Returns ordered list of ``{"tool", "args", "result"}`` dicts — used by
    the advisor to read what each specialist actually fetched.
    """
    from langchain_core.messages import AIMessage, ToolMessage

    pending: list[dict[str, Any]] = []
    results_by_id: dict[str, Any] = {}
    for msg in messages:
        if isinstance(msg, ToolMessage):
            tcid = getattr(msg, "tool_call_id", None)
            if tcid:
                results_by_id[tcid] = _summarize_tool_output(msg)
        elif isinstance(msg, AIMessage):
            for tc in getattr(msg, "tool_calls", None) or []:
                if isinstance(tc, dict):
                    name = tc.get("name")
                    args = tc.get("args") or {}
                    tcid = tc.get("id")
                else:
                    name = getattr(tc, "name", None)
                    args = getattr(tc, "args", None) or {}
                    tcid = getattr(tc, "id", None)
                if name:
                    pending.append({"tool": name, "args": args, "_id": tcid})

    out: list[dict[str, Any]] = []
    for entry in pending:
        tcid = entry.pop("_id", None)
        entry["result"] = results_by_id.get(tcid) if tcid else None
        out.append(entry)
    return out


def build_findings(
    agent_name: str,
    result_messages: list,
    *,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Produce the canonical findings entry for one specialist.

    Returned shape (stored under ``state["findings"][agent_name]``)::

        {
          "summary":      <final natural-language reply from the agent>,
          "tool_calls":   [{"tool", "args", "result"}, ...],
          "extra":        {<agent-specific structured payload>}  # optional
        }
    """
    final = result_messages[-1] if result_messages else None
    summary = normalize_content(getattr(final, "content", "")).strip() if final else ""
    return {
        "summary": summary,
        "tool_calls": collect_tool_results(result_messages),
        "extra": extra or {},
    }
