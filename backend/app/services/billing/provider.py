"""Provider-agnostic payment interface.

A ``PaymentProvider`` turns a plan into a hosted-checkout the user is sent to,
then later confirms whether that checkout was paid. Concrete providers (mock,
iyzico, …) implement this; the rest of the app never imports a gateway SDK
directly, so adding a provider is an adapter, not a rewrite.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from app.services.billing.plans import Plan


@dataclass
class Buyer:
    """Minimal buyer info a gateway needs. Kept tiny + JSON-safe."""

    user_id: int
    name: str
    email: str


@dataclass
class CheckoutSession:
    """What the frontend needs to send the user into payment."""

    ref: str                 # provider handle (token / conversationId) we persist
    redirect_url: str        # where the browser goes to pay
    raw: dict = field(default_factory=dict)


@dataclass
class PaymentResult:
    paid: bool
    ref: str
    raw: dict = field(default_factory=dict)


@runtime_checkable
class PaymentProvider(Protocol):
    name: str

    def start_checkout(
        self, *, buyer: Buyer, plan: Plan, callback_url: str
    ) -> CheckoutSession:
        """Create a hosted checkout and return where to send the user."""
        ...

    def finalize(self, *, ref: str, params: dict) -> PaymentResult:
        """Confirm a checkout (called from the return/callback) → paid or not."""
        ...
