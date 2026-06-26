"""iyzico Checkout Form adapter.

⚠️ UNVERIFIED: this implements iyzico's documented Checkout-Form flow but has
NOT yet been run against the iyzico sandbox. It is only selected when the
IYZICO_* keys are configured (otherwise the registry uses the mock provider).
Once real sandbox credentials are available, run a live checkout and reconcile
field names / response parsing against the actual API before trusting it.

Flow:
  start_checkout → CheckoutFormInitialize.create(...) → {token, paymentPageUrl}
  finalize       → CheckoutForm.retrieve(token) → paymentStatus == "SUCCESS"

The ``iyzipay`` SDK is imported lazily so the package is only required when
iyzico is actually configured.
"""
from __future__ import annotations

import json
import logging

from app.services.billing.plans import Plan
from app.services.billing.provider import Buyer, CheckoutSession, PaymentResult
from app.settings import settings

log = logging.getLogger("fincoach.billing.iyzico")


class IyzicoProvider:
    name = "iyzico"

    def _options(self) -> dict:
        return {
            "api_key": settings.iyzico_api_key,
            "secret_key": settings.iyzico_secret_key,
            "base_url": settings.iyzico_base_url,
        }

    def start_checkout(
        self, *, buyer: Buyer, plan: Plan, callback_url: str
    ) -> CheckoutSession:
        import iyzipay  # lazy: only needed when iyzico is configured

        price = f"{plan.price:.2f}"
        conversation_id = f"u{buyer.user_id}-{plan.code}"
        request = {
            "locale": "tr",
            "conversationId": conversation_id,
            "price": price,
            "paidPrice": price,
            "currency": plan.currency,
            "basketId": f"{plan.code}-{buyer.user_id}",
            "paymentGroup": "SUBSCRIPTION",
            "callbackUrl": callback_url,
            "buyer": {
                "id": str(buyer.user_id),
                "name": buyer.name or "FinCoach",
                "surname": "User",
                "email": buyer.email or "user@fincoach.app",
                "identityNumber": "11111111111",  # iyzico requires a value
                "registrationAddress": "N/A",
                "city": "Istanbul",
                "country": "Turkey",
                "ip": "0.0.0.0",
            },
            "billingAddress": {
                "contactName": buyer.name or "FinCoach User",
                "city": "Istanbul",
                "country": "Turkey",
                "address": "N/A",
            },
            "basketItems": [
                {
                    "id": plan.code,
                    "name": f"FinCoach {plan.code.title()}",
                    "category1": "Subscription",
                    "itemType": "VIRTUAL",
                    "price": price,
                }
            ],
        }
        resp = iyzipay.CheckoutFormInitialize().create(request, self._options())
        data = json.loads(resp.read().decode("utf-8"))
        if data.get("status") != "success":
            raise RuntimeError(f"iyzico init failed: {data.get('errorMessage') or data}")
        return CheckoutSession(
            ref=data["token"],
            redirect_url=data["paymentPageUrl"],
            raw=data,
        )

    def finalize(self, *, ref: str, params: dict) -> PaymentResult:
        import iyzipay

        request = {"locale": "tr", "conversationId": params.get("conversationId", ""), "token": ref}
        resp = iyzipay.CheckoutForm().retrieve(request, self._options())
        data = json.loads(resp.read().decode("utf-8"))
        paid = data.get("status") == "success" and data.get("paymentStatus") == "SUCCESS"
        if not paid:
            log.info("iyzico checkout %s not paid: %s", ref, data.get("paymentStatus"))
        return PaymentResult(paid=paid, ref=ref, raw=data)
