"""Pydantic schemas Gemini fills in via response_schema.

These map 1:1 to what the frontend review modal renders. Keep field names
lowercase_snake — Gemini's structured-output mode is sensitive to schema
shape but tolerant of natural names.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

DocType = Literal[
    "bank_statement",
    "broker_statement",
    "portfolio_screenshot",
    "invoice",
    "receipt",
    "id_document",
    "salary_slip",
    "other",
]

AssetClass = Literal["stock", "etf", "crypto", "bond", "cash"]


class HoldingSuggestion(BaseModel):
    ticker: str = Field(description="Symbol exactly as printed (uppercase if known).")
    asset_class: AssetClass = "stock"
    quantity: float | None = None
    cost_basis: float | None = Field(default=None, description="Per-unit average cost in document currency.")
    currency: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    source_text: str | None = Field(default=None, description="Quoted snippet supporting this row.")


class TransactionSuggestion(BaseModel):
    occurred_on: str | None = Field(default=None, description="ISO date.")
    amount: float | None = None
    currency: str | None = None
    type: Literal["income", "expense", "transfer", "unknown"] = "unknown"
    category: str | None = None
    description: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)


class ProfileSuggestion(BaseModel):
    name: str | None = None
    monthly_income: float | None = None
    currency: str | None = None
    risk_signals: list[str] = Field(
        default_factory=list,
        description="Text snippets hinting at risk tolerance (e.g. 'leveraged', 'long-term').",
    )
    confidence: float = Field(ge=0.0, le=1.0)


class ProfileExtraction(BaseModel):
    """Top-level result returned to the frontend for review."""

    doc_type: DocType
    doc_type_confidence: float = Field(ge=0.0, le=1.0)
    summary: str = Field(description="One-sentence plain-language description of the document.")
    suggested_holdings: list[HoldingSuggestion] = Field(default_factory=list)
    suggested_transactions: list[TransactionSuggestion] = Field(default_factory=list)
    suggested_profile: ProfileSuggestion | None = None
    missing_or_unclear: list[str] = Field(
        default_factory=list,
        description="Fields the model couldn't read with confidence. Show as warnings.",
    )
    follow_up_questions: list[str] = Field(
        default_factory=list,
        description="Questions the AI assistant should ask the user next.",
    )
    needs_better_document: str | None = Field(
        default=None,
        description="If the document is wrong type or unreadable, what should the user upload instead.",
    )
