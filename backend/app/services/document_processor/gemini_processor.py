"""GeminiDocumentProcessor — native google-genai pipeline.

One round-trip: PDF/image/docx bytes → Gemini multimodal → structured JSON
matching a Pydantic schema. We deliberately bypass the LangChain wrapper
here because:
  - LangChain's `with_structured_output` is looser than Gemini's native
    response_schema (which enforces JSON Schema server-side).
  - The File API (>18 MB or persistent reuse) is first-class only in the
    native SDK.
  - This is a one-shot call; no tool/agent orchestration to gain from.

Chat / multi-agent flow keeps using LangChain — see app/agents/.
"""
from __future__ import annotations

import logging
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.services.document_processor.base import (
    DocumentSource,
    DocumentStorage,
    NoOpStorage,
    ProcessorError,
)
from app.services.document_processor.schemas import ProfileExtraction
from app.settings import settings

log = logging.getLogger("fincoach.document_processor")

T = TypeVar("T", bound=BaseModel)


PROFILE_PROMPT = """You are FinCoach's document analyst. The user uploaded a financial document or
provided a plain-text description to help bootstrap their portfolio and profile.

Tasks:
1. Identify the document type (bank statement, broker statement, portfolio screenshot,
   invoice, receipt, salary slip, ID, other, text_description).
2. Extract holdings (ticker, quantity, cost basis if visible, asset class).
3. Extract transactions (date, amount, currency, category, description):
   - From documents: extract from bank/broker statements.
   - From text: parse descriptions like "monthly 300 EUR YouTube subscription" → extract
     as a transaction with category="subscription", description="YouTube subscription income".
4. Pull profile hints (full name, monthly income, currency, risk signals).
5. Note any field that was illegible, cropped, or ambiguous in `missing_or_unclear`.
6. If the document is the wrong kind for portfolio bootstrapping (e.g. shopping receipt),
   set `needs_better_document` to one short sentence telling the user what to upload instead
   (e.g. "Upload a brokerage statement listing positions and quantities.").
7. Suggest 1-3 short follow-up questions the assistant should ask to fill remaining gaps.

Income Category Rules:
- "salary", "wage", "paycheck", "employment" → category: "salary"
- "freelance", "consulting", "contract work" → category: "freelance"
- "subscription", "youtube", "patreon", "twitch", "affiliate" → category: "subscription"
- "rent", "rental", "lease income" → category: "rental"
- Other income sources → category: "other"

Rules:
- NEVER invent values. If a number is unreadable, leave the field null and add a note.
- Confidence is your honest self-assessment, not optimism. <0.7 means "user must verify".
- Currency codes use ISO-4217 (USD, EUR, TRY...). Quantities are numbers, not strings.
- `summary` is one neutral sentence, no advice.
- For text descriptions: prefer extracting as detailed transactions over generic monthly_income.
  Example: "300 EUR YouTube sub" → suggested_transactions with type="income",
  category="subscription", description="YouTube subscription income", amount=300, currency="EUR"
"""


class GeminiDocumentProcessor:
    """Stateless wrapper around google-genai for one-shot document parsing."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        storage: DocumentStorage | None = None,
    ) -> None:
        self._api_key = api_key or settings.gemini_api_key
        self._model = model or settings.gemini_model
        self._storage = storage or NoOpStorage()
        if not self._api_key:
            raise ProcessorError("GEMINI_API_KEY is not configured")

    def extract_profile(self, source: DocumentSource) -> ProfileExtraction:
        """Parse a profile-relevant document. Storage hook fires before the LLM call."""
        return self._extract(source, ProfileExtraction, PROFILE_PROMPT)

    def _extract(self, source: DocumentSource, schema: type[T], prompt: str) -> T:
        # Run the storage hook first so future audit trails capture every parse attempt
        # even when the LLM call fails.
        try:
            self._storage.persist(source)
        except Exception:  # noqa: BLE001
            log.warning("storage hook failed; continuing", exc_info=True)

        # Lazy-import: keeps cold-start fast and the dep optional during tests.
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=self._api_key)

        if source.needs_file_api:
            log.info("uploading %s (%d bytes) via File API", source.filename, source.size_bytes)
            uploaded = client.files.upload(
                file=source.data,
                config={"mime_type": source.mime_type, "display_name": source.filename},
            )
            doc_part = types.Part.from_uri(file_uri=uploaded.uri, mime_type=source.mime_type)
        else:
            doc_part = types.Part.from_bytes(data=source.data, mime_type=source.mime_type)

        try:
            response = client.models.generate_content(
                model=self._model,
                contents=[doc_part, prompt],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=schema,
                    temperature=0.0,
                ),
            )
        except Exception as exc:  # noqa: BLE001
            raise ProcessorError(f"Gemini generation failed: {exc}") from exc

        parsed = getattr(response, "parsed", None)
        if isinstance(parsed, schema):
            return parsed

        raw = getattr(response, "text", "") or ""
        if not raw.strip():
            raise ProcessorError("Gemini returned an empty response")

        try:
            return schema.model_validate_json(raw)
        except ValidationError as exc:
            log.error("schema validation failed; raw=%s", raw[:500])
            raise ProcessorError(f"document did not match expected schema: {exc}") from exc
