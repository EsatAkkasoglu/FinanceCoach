"""User profile tools — read/write the current user's profile.

`user_id` is resolved from the request-scoped ContextVar set by `/chat`,
so the LLM never has to pass it.
"""
from __future__ import annotations

from typing import Any

from langchain_core.tools import tool
from sqlalchemy import select

from app.agents.risk_profiler import score_to_profile
from app.auth import get_current_user_id_or_none
from app.db.models import User
from app.db.session import SessionLocal


@tool
def get_user_profile() -> dict[str, Any]:
    """Get the current user's profile: name, monthly income, risk score and label,
    roast_mode flag."""
    user_id = get_current_user_id_or_none()
    if user_id is None:
        return {"error": "no authenticated user in context"}
    with SessionLocal() as db:
        u = db.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
        if u is None:
            return {"error": "user not found"}
        return {
            "id": u.id,
            "name": u.name,
            "monthly_income": u.monthly_income,
            "risk_score": u.risk_score,
            "risk_profile": u.risk_profile,
            "roast_mode": bool(u.roast_mode),
        }


@tool
def update_risk_score(score: int) -> dict[str, Any]:
    """Update the current user's risk score (0-125). Recomputes the profile label
    (conservative / balanced / aggressive) automatically."""
    user_id = get_current_user_id_or_none()
    if user_id is None:
        return {"error": "no authenticated user in context"}
    score = max(0, min(125, int(score)))
    profile = score_to_profile(score)
    with SessionLocal() as db:
        u = db.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
        if u is None:
            return {"error": "user not found"}
        u.risk_score = score
        u.risk_profile = profile
        db.commit()
        return {"risk_score": score, "risk_profile": profile}
