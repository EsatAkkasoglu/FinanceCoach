"""Portfolio tools — read AND write the current user's holdings and transactions.

`user_id` comes from the request-scoped ContextVar.

Write tools (add_holding, add_holding_by_value, set_cash_balance,
remove_holding) let the portfolio agent record buy/sell actions the user
mentions in chat ("SCHD 700 € aldım"). Every write returns a small confirm
dict the agent can echo back so the user sees what was persisted.
"""
from __future__ import annotations

import logging
from datetime import date as date_cls
from typing import Any, Literal

from langchain_core.tools import tool
from sqlalchemy import select

from app.auth import get_current_user_id_or_none
from app.db.models import Holding, Transaction
from app.db.session import SessionLocal

log = logging.getLogger("fincoach.portfolio_tools")

AssetClassLit = Literal["stock", "crypto", "cash", "etf", "bond", "fund"]
_VALID_ASSET_CLASSES = {"stock", "crypto", "cash", "etf", "bond", "fund"}


@tool
def list_holdings() -> list[dict[str, Any]]:
    """List all current holdings for the user."""
    user_id = get_current_user_id_or_none()
    if user_id is None:
        return []
    with SessionLocal() as db:
        rows = db.execute(select(Holding).where(Holding.user_id == user_id)).scalars().all()
        return [
            {
                "ticker": h.ticker,
                "asset_class": h.asset_class,
                "quantity": h.quantity,
                "cost_basis": h.cost_basis,
                "currency": h.currency,
                "acquired_at": h.acquired_at.isoformat() if h.acquired_at else None,
            }
            for h in rows
        ]


def _normalize_ticker(raw: str) -> str:
    return (raw or "").strip().upper()


def _coerce_asset_class(value: str | None) -> str:
    v = (value or "stock").strip().lower()
    return v if v in _VALID_ASSET_CLASSES else "stock"


@tool
def add_holding(
    ticker: str,
    quantity: float,
    cost_basis: float,
    asset_class: AssetClassLit = "stock",
    currency: str = "USD",
) -> dict[str, Any]:
    """Add (or merge into) a holding in the user's portfolio.

    Use this when the user explicitly states quantity and per-unit price
    ("10 shares of SCHD at 80 each"). For value-only buys ("I bought SCHD
    for 700 EUR"), use ``add_holding_by_value`` instead.

    Behavior:
    - If a holding with the same ticker already exists, the new lot is
      MERGED into it: quantity is summed and cost_basis becomes the
      quantity-weighted average per-unit cost. Asset class is preserved.
    - If no prior holding, a new row is created.

    Args:
        ticker: Symbol (e.g. 'SCHD', 'BTC-USD'). Case-insensitive.
        quantity: Number of units acquired. Must be > 0.
        cost_basis: Per-unit cost in the asset's native currency. Must be >= 0.
        asset_class: One of 'stock', 'etf', 'crypto', 'cash', 'bond'.

    Returns:
        {"ok": True, "ticker", "quantity", "cost_basis", "asset_class", "action": "added"|"merged"}
        or {"ok": False, "error": "..."} on validation failure.
    """
    user_id = get_current_user_id_or_none()
    if user_id is None:
        return {"ok": False, "error": "no user in context"}
    if quantity <= 0:
        return {"ok": False, "error": "quantity must be positive"}
    if cost_basis < 0:
        return {"ok": False, "error": "cost_basis cannot be negative"}

    tkr = _normalize_ticker(ticker)
    if not tkr:
        return {"ok": False, "error": "ticker required"}
    ac = _coerce_asset_class(asset_class)
    # Currency snap rules — protect against agents defaulting to USD on
    # instruments that are natively priced in another currency:
    #   • TEFAS funds  → always TRY
    #   • BIST stocks (.IS suffix) → always TRY
    # In both cases we override a missing/USD value but respect an
    # explicit non-USD currency the caller supplied (e.g. EUR for a fund
    # bought via a euro account — unusual but possible).
    raw_ccy = (currency or "").strip().upper()
    if ac == "fund" or tkr.endswith(".IS"):
        ccy = "TRY" if raw_ccy in {"", "USD"} else raw_ccy
    else:
        ccy = raw_ccy or "USD"

    with SessionLocal() as db:
        existing = db.execute(
            select(Holding).where(Holding.user_id == user_id, Holding.ticker == tkr)
        ).scalar_one_or_none()

        if existing is None:
            h = Holding(
                user_id=user_id,
                ticker=tkr,
                asset_class=ac,
                quantity=quantity,
                cost_basis=cost_basis,
                currency=ccy,
                acquired_at=date_cls.today(),
            )
            db.add(h)
            db.commit()
            db.refresh(h)
            return {
                "ok": True,
                "action": "added",
                "ticker": h.ticker,
                "quantity": h.quantity,
                "cost_basis": h.cost_basis,
                "asset_class": h.asset_class,
                "currency": h.currency,
            }

        total_qty = existing.quantity + quantity
        total_cost = (existing.quantity * existing.cost_basis) + (quantity * cost_basis)
        existing.quantity = total_qty
        existing.cost_basis = total_cost / total_qty if total_qty else 0.0
        if ccy and existing.currency != ccy:
            existing.currency = ccy
        db.commit()
        db.refresh(existing)
        return {
            "ok": True,
            "action": "merged",
            "ticker": existing.ticker,
            "quantity": existing.quantity,
            "cost_basis": existing.cost_basis,
            "asset_class": existing.asset_class,
            "currency": existing.currency,
        }


@tool
def add_holding_by_value(
    ticker: str,
    value: float,
    asset_class: AssetClassLit = "stock",
    currency: str = "USD",
) -> dict[str, Any]:
    """Add a holding when the user specified a TOTAL value (not quantity).

    Use when the user says things like 'SCHD 700 € aldım' / 'I put 1000
    USD into BTC'. This tool fetches the current market price for the
    ticker, computes quantity = value / price, and records the buy with
    cost_basis = current price.

    Args:
        ticker: Symbol (e.g. 'SCHD', 'BTC-USD'). Case-insensitive.
        value: Total amount spent in the asset's native quote currency
               (NOT the user's home currency unless they're the same).
               Must be > 0.
        asset_class: One of 'stock', 'etf', 'crypto', 'cash', 'bond'.
        currency: Informational — the currency the user reported. Stored
                  only in the returned confirmation; the cost_basis itself
                  is in the asset's yfinance-reported quote currency.

    Returns:
        {"ok": True, "ticker", "quantity", "cost_basis", "price_used",
         "currency", "action": "added"|"merged"}
        or {"ok": False, "error": "..."} if the quote fetch fails.
    """
    user_id = get_current_user_id_or_none()
    if user_id is None:
        return {"ok": False, "error": "no user in context"}
    if value <= 0:
        return {"ok": False, "error": "value must be positive"}

    tkr = _normalize_ticker(ticker)
    if not tkr:
        return {"ok": False, "error": "ticker required"}

    ac = _coerce_asset_class(asset_class)

    # TEFAS Turkish funds: 3-letter ALL-CAPS codes priced in TRY, NAV via TEFAS
    # (yfinance returns no data). Route them through get_fund_quote.
    quote: dict[str, Any] | None = None
    if ac == "fund":
        from app.tools.fund_tools import get_fund_quote

        quote = get_fund_quote.invoke({"code": tkr})
        if not isinstance(quote, dict) or not quote.get("ok") or not quote.get("price"):
            err = quote.get("error") if isinstance(quote, dict) else "no quote"
            return {"ok": False, "error": f"could not fetch TEFAS NAV for {tkr}: {err}"}
        # TEFAS NAV is always TRY; override caller-supplied currency for safety.
        quote_ccy = "TRY"
    else:
        from app.tools.market_tools import get_quote

        quote = get_quote.invoke({"ticker": tkr})
        if not isinstance(quote, dict) or quote.get("error") or not quote.get("price"):
            return {
                "ok": False,
                "error": f"could not fetch price for {tkr}: {quote.get('error') if isinstance(quote, dict) else 'no quote'}",
            }
        quote_ccy = (quote.get("currency") or currency or "USD").upper()

    price = float(quote["price"])
    if price <= 0:
        return {"ok": False, "error": f"invalid price for {tkr}: {price}"}

    final_ccy = (currency or "").upper() or quote_ccy
    qty = value / price
    result = add_holding.invoke(
        {
            "ticker": tkr,
            "quantity": qty,
            "cost_basis": price,
            "asset_class": ac,
            "currency": final_ccy,
        }
    )
    if isinstance(result, dict) and result.get("ok"):
        result["price_used"] = price
        result["value_spent"] = value
        result["currency"] = final_ccy
    return result


@tool
def set_cash_balance(
    amount: float,
    currency: str = "USD",
) -> dict[str, Any]:
    """Set the user's cash position for a given currency (replaces, not adds).

    Use when the user says 'kalan parayı nakitte tutacağım' or
    'I have 500 EUR in cash'. This replaces any existing cash row with
    the same currency-ticker — it does NOT accumulate.

    Cash holdings are stored with the currency code as the ticker
    (e.g. 'EUR', 'TRY', 'USD'), asset_class='cash', quantity=amount,
    cost_basis=1.0. The portfolio endpoint treats quantity as the value.

    Args:
        amount: Cash amount. Must be >= 0. Zero deletes the cash row.
        currency: Currency code (USD/EUR/TRY/GBP/...). Defaults to USD.

    Returns:
        {"ok": True, "currency", "amount", "action": "set"|"cleared"}
    """
    user_id = get_current_user_id_or_none()
    if user_id is None:
        return {"ok": False, "error": "no user in context"}
    if amount < 0:
        return {"ok": False, "error": "amount cannot be negative"}

    code = (currency or "USD").strip().upper() or "USD"

    with SessionLocal() as db:
        existing = db.execute(
            select(Holding).where(
                Holding.user_id == user_id,
                Holding.ticker == code,
                Holding.asset_class == "cash",
            )
        ).scalar_one_or_none()

        if amount == 0:
            if existing is not None:
                db.delete(existing)
                db.commit()
                return {"ok": True, "action": "cleared", "currency": code, "amount": 0.0}
            return {"ok": True, "action": "noop", "currency": code, "amount": 0.0}

        if existing is None:
            db.add(
                Holding(
                    user_id=user_id,
                    ticker=code,
                    asset_class="cash",
                    quantity=amount,
                    cost_basis=1.0,
                    acquired_at=date_cls.today(),
                )
            )
        else:
            existing.quantity = amount
            existing.cost_basis = 1.0
        db.commit()
        return {"ok": True, "action": "set", "currency": code, "amount": amount}


@tool
def remove_holding(ticker: str) -> dict[str, Any]:
    """Remove a holding from the user's portfolio entirely.

    Use when the user says they sold all of a position ('SCHD'i tamamen
    sattım'). For partial sells, call ``add_holding`` with a NEGATIVE
    quantity is NOT supported — instead delete and re-add with the
    remaining quantity, or update via the /portfolio API.

    Args:
        ticker: Symbol to remove (case-insensitive). For cash, pass the
                currency code (e.g. 'EUR').

    Returns:
        {"ok": True, "ticker", "action": "removed"|"not_found"}
    """
    user_id = get_current_user_id_or_none()
    if user_id is None:
        return {"ok": False, "error": "no user in context"}
    tkr = _normalize_ticker(ticker)
    if not tkr:
        return {"ok": False, "error": "ticker required"}

    with SessionLocal() as db:
        rows = db.execute(
            select(Holding).where(Holding.user_id == user_id, Holding.ticker == tkr)
        ).scalars().all()
        if not rows:
            return {"ok": True, "action": "not_found", "ticker": tkr}
        for h in rows:
            db.delete(h)
        db.commit()
        return {"ok": True, "action": "removed", "ticker": tkr, "rows_removed": len(rows)}


@tool
def list_transactions(limit: int = 100) -> list[dict[str, Any]]:
    """Return the most recent transactions for the user."""
    user_id = get_current_user_id_or_none()
    if user_id is None:
        return []
    with SessionLocal() as db:
        rows = (
            db.execute(
                select(Transaction)
                .where(Transaction.user_id == user_id)
                .order_by(Transaction.occurred_on.desc())
                .limit(limit)
            )
            .scalars()
            .all()
        )
        return [
            {
                "date": t.occurred_on.isoformat(),
                "type": t.type,
                "amount": t.amount,
                "currency": t.currency,
                "category": t.category,
                "description": t.description,
            }
            for t in rows
        ]
