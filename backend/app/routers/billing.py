"""Billing endpoints: list plans, start checkout, finalize on return.

Provider-agnostic (see app.services.billing). With no iyzico keys the mock
provider drives the whole flow so the upgrade path is testable locally.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth import get_current_user_id
from app.db.models import User
from app.db.session import SessionLocal
from app.services.billing import (
    finalize_checkout,
    get_plan,
    list_plans,
    payments_mode,
    start_checkout,
)

router = APIRouter(prefix="/billing", tags=["billing"])


class CheckoutRequest(BaseModel):
    plan: str = "pro"
    # Where the gateway should send the browser back after payment. The frontend
    # passes its own return page; we only ever redirect within the app shell.
    return_url: str | None = None


class FinalizeRequest(BaseModel):
    ref: str
    params: dict = {}


@router.get("/plans")
def get_plans(user_id: int = Depends(get_current_user_id)):
    with SessionLocal() as db:
        tier = db.get(User, user_id).tier if db.get(User, user_id) else "free"
    mode = payments_mode()
    return {
        "mode": mode,                 # "live" | "mock" | "unavailable"
        "live": mode != "unavailable",
        "tier": tier,
        "plans": [
            {"code": p.code, "price": p.price, "currency": p.currency, "period": p.period}
            for p in list_plans()
        ],
    }


@router.post("/checkout")
def create_checkout(body: CheckoutRequest, user_id: int = Depends(get_current_user_id)):
    plan = get_plan(body.plan)
    if plan is None:
        raise HTTPException(404, "unknown plan")
    # Payments not wired in this deploy yet (no gateway keys) — tell the UI so it
    # routes to the "coming soon" page instead of granting Pro via the mock.
    if payments_mode() == "unavailable":
        return {"status": "unavailable"}
    callback = body.return_url or "/billing/return"
    with SessionLocal() as db:
        user = db.get(User, user_id)
        if user is None:
            raise HTTPException(401, "user not found")
        if user.tier == "pro":
            raise HTTPException(409, "already on pro")
        return start_checkout(db, user, plan, callback)


@router.post("/finalize")
def finalize(body: FinalizeRequest, user_id: int = Depends(get_current_user_id)):
    with SessionLocal() as db:
        result = finalize_checkout(db, body.ref, body.params, user_id=user_id)
    if result.get("status") == "not_found":
        raise HTTPException(404, "checkout not found")
    if result.get("status") == "forbidden":
        raise HTTPException(403, "not your checkout")
    return result
