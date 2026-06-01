"""Standard result envelope + locale-aware formatting for deterministic calc tools.

Every ``calc_*`` tool returns through :func:`ok` / :func:`err` so the contract is
identical across the whole layer:

    success → {ok, raw_value, formatted_value, formula, explanation, ui_type, data, ...}
    failure → {ok: False, error, inputs_received}

Why this shape (see the three design notes it bakes in):
  • graceful degradation — tools never raise into the graph; they return ``err``
    so the agent can read the message and re-call with corrected params.
  • formatting authority — numbers are turned into display strings HERE, in
    Python, so the LLM never re-formats (and never mis-rounds) them. The prose
    layer is told to quote ``formatted_value`` verbatim.
  • UI hint — ``ui_type`` + ``data`` let the frontend pick a dataviz component
    with a plain switch/case instead of sniffing JSON keys.

Number formatting mirrors ``src/lib/format.ts`` (Intl.NumberFormat per currency)
so a value shown in chat prose matches the value shown on a card.
"""
from __future__ import annotations

from typing import Any, Literal

from app.auth import get_display_currency, get_ui_language

UiType = Literal["metric", "donut", "diverging_bar", "bars", "table", "none"]

# Currency → (thousands_sep, decimal_sep, symbol, symbol_prefix?) — mirrors the
# locales used in src/lib/format.ts (USD→en-US, TRY→tr-TR, EUR→de-DE, GBP→en-GB).
_CCY_FMT: dict[str, tuple[str, str, str, bool]] = {
    "USD": (",", ".", "$", True),
    "GBP": (",", ".", "£", True),
    "EUR": (".", ",", "€", False),
    "TRY": (".", ",", "₺", False),
}


def _group(amount: float, decimals: int, thousands: str, decimal: str) -> str:
    """Group thousands and place the decimal separator for a locale."""
    # Build with the canonical "1,234,567.89" then swap separators in one pass
    # via a placeholder so a "," target doesn't collide with the source ".".
    base = f"{amount:,.{decimals}f}"
    return base.replace(",", "\0").replace(".", decimal).replace("\0", thousands)


def format_money(amount: float | int | None, currency: str | None = None) -> str:
    """Format a monetary amount like the app does (locale + currency symbol).

    Mirrors ``formatCurrency`` in src/lib/format.ts: 0 decimals once the
    magnitude is >= 100, else 2 decimals.
    """
    if amount is None:
        return ""
    ccy = (currency or get_display_currency() or "USD").upper()
    thousands, decimal, symbol, prefix = _CCY_FMT.get(ccy, (",", ".", "", True))
    decimals = 0 if abs(amount) >= 100 else 2
    body = _group(float(amount), decimals, thousands, decimal)
    if not symbol:  # unknown currency → append the ISO code
        return f"{body} {ccy}"
    return f"{symbol}{body}" if prefix else f"{body} {symbol}"


def format_pct(value: float | int | None, digits: int = 1) -> str:
    """Format a percentage with an explicit sign, like ``formatPercent``."""
    if value is None:
        return ""
    sign = "+" if value > 0 else ""
    return f"{sign}{float(value):.{digits}f}%"


def format_number(value: float | int | None, decimals: int = 2) -> str:
    """Locale-grouped plain number (no currency) using the UI language."""
    if value is None:
        return ""
    thousands, decimal = (".", ",") if (get_ui_language() or "en") == "tr" else (",", ".")
    return _group(float(value), decimals, thousands, decimal)


def ok(
    *,
    raw_value: Any = None,
    formatted_value: str | None = None,
    formula: str | None = None,
    explanation: str | None = None,
    ui_type: UiType = "none",
    data: dict[str, Any] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Build a successful calc-tool result in the standard envelope."""
    out: dict[str, Any] = {
        "ok": True,
        "raw_value": raw_value,
        "formatted_value": formatted_value,
        "formula": formula,
        "explanation": explanation,
        "ui_type": ui_type,
        "data": data or {},
    }
    out.update(extra)
    return out


def err(message: str, **inputs_received: Any) -> dict[str, Any]:
    """Build a failed calc-tool result. Never raise into the graph — return this.

    ``inputs_received`` echoes the offending args so the agent can see what it
    sent and retry with corrected values.
    """
    return {"ok": False, "error": message, "inputs_received": inputs_received}
