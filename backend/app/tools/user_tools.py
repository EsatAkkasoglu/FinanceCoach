"""User profile tools — read/write the single-user profile.

Used by the Risk Profiler agent (and indirectly by Budget Coach for roast_mode)."""
from __future__ import annotations

from typing import Any

from langchain_core.tools import tool
from sqlalchemy import select

from app.db.models import User
from app.db.session import SessionLocal
from app.agents.risk_profiler import score_to_profile


@tool
def get_user_profile(user_id: int = 1) -> dict[str, Any]:
    """Get the user's profile: name, monthly income, risk score and label,
    roast_mode flag."""
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
def update_risk_score(score: int, user_id: int = 1) -> dict[str, Any]:
    """Update the user's risk score (0-125). Recomputes the profile label
    (conservative / balanced / aggressive) automatically."""
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
