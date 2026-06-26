"""Billing: provider-agnostic checkout + tier upgrade.

The registry picks the real provider (iyzico) when its keys are configured and
otherwise falls back to the in-process mock, so local dev and tests run the
full flow without a gateway. ``start_checkout`` / ``finalize`` orchestrate the
``BillingCheckout`` row and the user's tier transition.
"""
from __future__ import annotations

import logging
from datetime import datetime

from app.db.models import BillingCheckout, User
from app.services.billing.mock_provider import MockProvider
from app.services.billing.plans import Plan, get_plan, list_plans
from app.services.billing.provider import Buyer, PaymentProvider
from app.settings import settings

log = logging.getLogger("fincoach.billing")

__all__ = ["get_provider", "start_checkout", "finalize_checkout", "get_plan", "list_plans", "Plan"]


def get_provider() -> PaymentProvider:
    """The active provider — real iyzico when configured, else the mock."""
    if settings.iyzico_configured:
        from app.services.billing.iyzico_provider import IyzicoProvider

        return IyzicoProvider()
    return MockProvider()


def start_checkout(db, user: User, plan: Plan, callback_url: str) -> dict:
    """Create a checkout row + provider session. Returns redirect info."""
    provider = get_provider()
    buyer = Buyer(user_id=user.id, name=user.name or user.username, email=_email_for(user))
    session = provider.start_checkout(buyer=buyer, plan=plan, callback_url=callback_url)

    row = BillingCheckout(
        user_id=user.id,
        provider=provider.name,
        plan=plan.code,
        amount=plan.price,
        currency=plan.currency,
        provider_ref=session.ref,
        status="pending",
    )
    db.add(row)
    db.commit()
    return {"ref": session.ref, "redirect_url": session.redirect_url, "provider": provider.name}


def finalize_checkout(db, ref: str, params: dict, *, user_id: int | None = None) -> dict:
    """Confirm a checkout by ref; on success upgrade the user's tier.

    Idempotent: a checkout already marked paid returns its state unchanged.
    When ``user_id`` is given, the checkout must belong to that user (the
    browser hitting the return page is authenticated as its owner).
    """
    row = (
        db.query(BillingCheckout)
        .filter(BillingCheckout.provider_ref == ref)
        .order_by(BillingCheckout.id.desc())
        .first()
    )
    if row is None:
        return {"status": "not_found"}
    if user_id is not None and row.user_id != user_id:
        return {"status": "forbidden"}
    if row.status == "paid":
        return {"status": "paid", "tier": "pro", "already": True}

    provider = get_provider()
    result = provider.finalize(ref=ref, params=params)

    if not result.paid:
        row.status = "failed"
        db.commit()
        return {"status": "failed"}

    row.status = "paid"
    row.paid_at = datetime.utcnow()
    user = db.get(User, row.user_id)
    if user is not None:
        user.tier = "pro"
    db.commit()
    log.info("billing: user %s upgraded to pro via %s", row.user_id, row.provider)
    return {"status": "paid", "tier": "pro"}


def _email_for(user: User) -> str:
    # The username is the email in the Firebase flow; fall back gracefully.
    return user.username if "@" in (user.username or "") else f"{user.username}@fincoach.app"
