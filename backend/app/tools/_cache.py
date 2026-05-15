"""Per-request tool result cache.

Specialists fan out in parallel and several of them (portfolio + market_data)
end up calling ``get_quote`` for the same ticker in the same turn. A simple
ContextVar-backed dict, scoped to the /chat request, lets tools dedupe those
calls without changing their signatures.

Pattern mirrors ``app.auth.context.current_user_id_var``: the chat endpoint
sets a fresh dict on the var before dispatching the supervisor; tools call
``cache_get`` / ``cache_set`` to share results within that turn.

Best-effort: if the var is unset (e.g. tool invoked outside a request), the
cache silently no-ops and the tool runs normally.
"""
from __future__ import annotations

from contextvars import ContextVar
from typing import Any

tool_cache_var: ContextVar[dict | None] = ContextVar("tool_cache", default=None)


def cache_get(key: str) -> Any | None:
    cache = tool_cache_var.get()
    if cache is None:
        return None
    return cache.get(key)


def cache_set(key: str, value: Any) -> None:
    cache = tool_cache_var.get()
    if cache is None:
        return
    cache[key] = value


def cache_reset() -> dict:
    """Install a fresh cache dict for the current context and return it."""
    fresh: dict[str, Any] = {}
    tool_cache_var.set(fresh)
    return fresh
