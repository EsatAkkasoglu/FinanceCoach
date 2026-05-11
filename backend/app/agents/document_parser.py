"""Document Parser agent — Gemini multimodal pipeline for bank statements,
receipts, invoices.

Input: PDF or image bytes (uploaded via /documents/upload).
Output: list[dict] of structured transactions { date, amount, currency,
    description, category, confidence }.
"""
from __future__ import annotations

from langchain_core.messages import AIMessage

from app.agents.state import AgentState

SYSTEM_PROMPT = """You are the Document Parser agent for FinCoach.
You read bank statements, receipts, and invoices and extract structured
transactions. For each transaction emit:
    date (ISO), amount, currency, description, category, confidence (0-1)
Use these categories only: groceries, dining, transport, utilities, rent,
entertainment, health, shopping, travel, salary, transfer, other.
If confidence < 0.7, mark category as 'uncategorized' and let the user
review."""


async def run(state: AgentState) -> AgentState:
    # TODO(impl): pull document_id from state, fetch bytes, call Gemini multimodal,
    # parse JSON response, write to Transaction table with document_id reference
    reply = AIMessage(content="[document_parser agent stub] PDF parse not yet wired.",
                      name="document_parser")
    return {"messages": [reply]}
