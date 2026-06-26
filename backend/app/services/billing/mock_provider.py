"""In-process mock payment provider for local dev + tests.

No network, no keys. ``start_checkout`` mints a ref and points the browser
straight back at our own callback (with ``mock=1``); ``finalize`` always
reports paid. This lets the entire flow — button → checkout → callback →
tier upgrade — run end-to-end without a real gateway.
"""
from __future__ import annotations

import uuid

from app.services.billing.plans import Plan
from app.services.billing.provider import Buyer, CheckoutSession, PaymentResult


class MockProvider:
    name = "mock"

    def start_checkout(
        self, *, buyer: Buyer, plan: Plan, callback_url: str
    ) -> CheckoutSession:
        ref = f"mock_{uuid.uuid4().hex}"
        sep = "&" if "?" in callback_url else "?"
        return CheckoutSession(
            ref=ref,
            redirect_url=f"{callback_url}{sep}ref={ref}&mock=1",
            raw={"mock": True, "plan": plan.code},
        )

    def finalize(self, *, ref: str, params: dict) -> PaymentResult:
        # A mock checkout is "paid" unless the caller explicitly simulates failure.
        paid = params.get("simulate") != "fail"
        return PaymentResult(paid=paid, ref=ref, raw={"mock": True})
