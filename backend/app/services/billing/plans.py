"""Paid-plan catalog. Prices come from settings so they're env-configurable."""
from __future__ import annotations

from dataclasses import dataclass

from app.settings import settings


@dataclass(frozen=True)
class Plan:
    code: str          # "pro"
    price: float
    currency: str
    period: str        # "monthly"


def get_plan(code: str) -> Plan | None:
    if code == "pro":
        return Plan(
            code="pro",
            price=settings.pro_plan_price,
            currency=settings.pro_plan_currency,
            period="monthly",
        )
    return None


def list_plans() -> list[Plan]:
    pro = get_plan("pro")
    return [pro] if pro else []
