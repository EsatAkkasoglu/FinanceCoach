"""ContextVar so tools running inside the LangGraph supervisor can read the
current user_id without threading it through every tool signature."""
from __future__ import annotations

from contextvars import ContextVar

current_user_id_var: ContextVar[int | None] = ContextVar("current_user_id", default=None)

# The currency the UI is currently displaying values in (TRY | USD | EUR).
# Goal `target_amount` / `current_amount` are stored as bare numbers and are
# shown to the user in whichever currency they pick in the top bar, so agents
# must interpret them in the SAME currency or they'll produce mismatched units
# ("150.000 TL" when the UI is showing "$150,000").
display_currency_var: ContextVar[str] = ContextVar("display_currency", default="USD")

# UI locale ("en" | "tr" | ...). Synthesizer / agents read this to lock the
# response language to whatever the frontend picker is set to, instead of
# guessing from the latest user message.
ui_language_var: ContextVar[str] = ContextVar("ui_language", default="en")


def get_current_user_id_or_none() -> int | None:
    return current_user_id_var.get()


def get_display_currency() -> str:
    return display_currency_var.get()


def get_ui_language() -> str:
    return ui_language_var.get()
