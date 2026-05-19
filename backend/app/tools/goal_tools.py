"""Goal tools — read/update the current user's savings goals.

The agents previously had ZERO visibility into the Goals table, so when a
user asked "ev hedefime ulaşmak için aylık ne kadar biriktirmeliyim?" the
LLM had no choice but to ask back for amount + target date — even though
both were already in the DB. These tools fix that.

`user_id` is resolved from the request-scoped ContextVar set by `/chat`,
so the LLM never has to pass it.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from langchain_core.tools import tool
from sqlalchemy import select

from app.auth import get_current_user_id_or_none, get_display_currency
from app.db.models import Goal
from app.db.session import SessionLocal


def _goal_dict(g: Goal) -> dict[str, Any]:
    target = float(g.target_amount or 0.0)
    current = float(g.current_amount or 0.0)
    remaining = max(0.0, target - current)
    pct = round((current / target) * 100, 1) if target > 0 else 0.0
    days_left: int | None = None
    months_left: float | None = None
    monthly_needed: float | None = None
    if g.target_date is not None:
        today = date.today()
        days_left = (g.target_date - today).days
        months_left = days_left / 30.44 if days_left is not None else None
        if months_left and months_left > 0 and remaining > 0:
            monthly_needed = round(remaining / months_left, 2)
    return {
        "id": g.id,
        "title": g.title,
        "icon": g.icon,
        "target_amount": target,
        "current_amount": current,
        "remaining_amount": remaining,
        "progress_pct": pct,
        "target_date": g.target_date.isoformat() if g.target_date else None,
        "days_left": days_left,
        "months_left": round(months_left, 1) if months_left is not None else None,
        "monthly_savings_needed": monthly_needed,
        "completed": current >= target if target > 0 else False,
    }


@tool
def list_user_goals() -> dict[str, Any]:
    """Return the current user's savings goals with progress and the monthly
    savings needed to hit each goal by its target date.

    Use this BEFORE asking the user about goal amount, target date, or
    progress — those values are already in the database. Always call this
    when the user mentions a goal ("ev hedefim", "acil fon", "tatil",
    "biriktirmek", "savings goal") or asks "am I on track".

    Returns a dict with `goals` (list) and `summary` (aggregates).
    """
    user_id = get_current_user_id_or_none()
    if user_id is None:
        return {"error": "no authenticated user in context", "goals": [], "summary": {}}
    with SessionLocal() as db:
        rows = (
            db.execute(select(Goal).where(Goal.user_id == user_id).order_by(Goal.id))
            .scalars()
            .all()
        )
    goals = [_goal_dict(g) for g in rows]
    ccy = get_display_currency()
    for g in goals:
        g["currency"] = ccy
    total_target = sum(g["target_amount"] for g in goals)
    total_saved = sum(g["current_amount"] for g in goals)
    total_monthly_needed = sum(
        g["monthly_savings_needed"] or 0.0 for g in goals if not g["completed"]
    )
    summary = {
        "count": len(goals),
        "completed_count": sum(1 for g in goals if g["completed"]),
        "total_target": round(total_target, 2),
        "total_saved": round(total_saved, 2),
        "total_remaining": round(max(0.0, total_target - total_saved), 2),
        "overall_progress_pct": round((total_saved / total_target) * 100, 1) if total_target > 0 else 0.0,
        "combined_monthly_savings_needed": round(total_monthly_needed, 2),
    }
    summary["currency"] = ccy
    return {"goals": goals, "summary": summary, "currency": ccy}


@tool
def create_user_goal(
    title: str,
    target_amount: float,
    target_date: str | None = None,
    current_amount: float = 0.0,
    icon: str = "target",
    currency: str = "TRY",
) -> dict[str, Any]:
    """Create a new savings goal for the current user and persist it to the DB.

    Call this when the user explicitly asks to create / set / save a goal
    ("acil durum fonu hedefi oluştur", "ev için hedef ekle", "create a goal"),
    or confirms a proposed goal you offered. Do NOT call this speculatively —
    only after the user has confirmed amount and (optionally) target date.

    Args:
      title: short human-readable name (e.g. "Acil durum fonu", "Ev peşinatı").
      target_amount: positive number, in `currency`.
      target_date: ISO 8601 date (YYYY-MM-DD), or None for open-ended goals.
        If the user says "12 ayda", compute today + that many months and pass
        the resulting YYYY-MM-DD.
      current_amount: already-saved amount, defaults to 0.
      icon: lucide-style icon slug (default "target").
      currency: ISO currency code, defaults to "TRY".

    Returns the created goal dict (with id) on success.
    """
    user_id = get_current_user_id_or_none()
    if user_id is None:
        return {"error": "no authenticated user in context"}
    if not title or not title.strip():
        return {"error": "title is required"}
    if target_amount is None or float(target_amount) <= 0:
        return {"error": "target_amount must be > 0"}
    parsed_date: date | None = None
    if target_date:
        try:
            parsed_date = datetime.strptime(target_date, "%Y-%m-%d").date()
        except ValueError:
            return {"error": f"target_date must be YYYY-MM-DD, got {target_date!r}"}
    with SessionLocal() as db:
        g = Goal(
            user_id=user_id,
            title=title.strip(),
            target_amount=float(target_amount),
            current_amount=max(0.0, float(current_amount or 0.0)),
            target_date=parsed_date,
            icon=icon or "target",
            currency=currency or "TRY",
        )
        db.add(g)
        db.commit()
        db.refresh(g)
        return {"ok": True, "action": "created", "goal": _goal_dict(g)}


@tool
def update_goal_progress(goal_id: int, delta_amount: float) -> dict[str, Any]:
    """Add `delta_amount` (can be negative) to the current_amount of goal `goal_id`.
    Use this when the user reports a contribution ("ev hedefime 5000 TL ekledim"
    or "acil fondan 200 TL çektim"). Returns the updated goal.
    """
    user_id = get_current_user_id_or_none()
    if user_id is None:
        return {"error": "no authenticated user in context"}
    with SessionLocal() as db:
        g = db.execute(
            select(Goal).where(Goal.id == goal_id, Goal.user_id == user_id)
        ).scalar_one_or_none()
        if g is None:
            return {"error": f"goal {goal_id} not found for this user"}
        g.current_amount = max(0.0, float(g.current_amount or 0.0) + float(delta_amount))
        db.commit()
        db.refresh(g)
        return {"ok": True, "action": "set", "goal": _goal_dict(g)}
