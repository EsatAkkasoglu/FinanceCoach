"""ContextVar so tools running inside the LangGraph supervisor can read the
current user_id without threading it through every tool signature."""
from __future__ import annotations

from contextvars import ContextVar

current_user_id_var: ContextVar[int | None] = ContextVar("current_user_id", default=None)


def get_current_user_id_or_none() -> int | None:
    return current_user_id_var.get()
