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


def _extract_pdf_text(data: bytes) -> str:
    """Cheap text extraction via pdfplumber (no API call). Returns empty string on failure."""
    try:
        import io
        import pdfplumber
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            return "\n".join(p.extract_text() or "" for p in pdf.pages).strip()
    except Exception:  # noqa: BLE001
        return ""

T = TypeVar("T", bound=BaseModel)


VISION_DUMP_PROMPT = """You are reading a financial / trading document that may include chart screenshots.

Your ONLY job: produce a faithful, verbatim text dump of everything visible in the document,
INCLUDING numbers and labels printed inside chart images, AND the SEMANTIC ROLE of each number
(entry / take-profit / stop-loss / current price / support / resistance / leverage / etc.).

How to assign roles on trade-setup charts (this is the critical part — most users care about
"what is the entry / TP / SL" not just the raw numbers):
- GREEN / TEAL filled rectangle = take-profit zone (long setup) OR entry zone for a short.
  The TOP edge of a green box is usually the TP target; the BOTTOM edge is the entry.
- RED / MAROON filled rectangle (placed below green) = stop-loss zone for a long. The number
  inside or labelling the bottom edge is the SL.
- For SHORT setups the colors invert (red box above price = TP zone going down, green/entry above).
  Decide long vs short from arrows, the author's note, and which color sits above current price.
- Arrows (cyan/blue) show the expected price path — follow them to confirm long vs short.
- Labels like "2X", "3X", "Halit Pozu" = leverage / position name, not price levels.
- Yellow horizontal lines = key support/resistance, not entry/TP/SL unless the box uses them.
- The price tag attached to the current candle (right-axis highlight) = current price.

Output format per asset (one block per chart):
<TICKER>: <author's note from the bullet, verbatim>.
  Direction: long | short | unclear
  Entry: <num or "n/a">
  TP: <num or "n/a">  (if multiple, list all: TP1, TP2…)
  SL: <num or "n/a">
  Leverage: <e.g. 2X, 3X, or "n/a">
  Other levels: <remaining numbers with a brief label each, e.g. "support 74,500", "resistance 200.14B">

Rules:
- Read actual pixels — do not paraphrase, do not skip numbers, do not round.
- Preserve the document's original language (Turkish, English, etc.) for the author's note.
- If a role is genuinely ambiguous, write "unclear" rather than guessing.
- If a number is partially cut off or illegible, write it followed by "(?)".
- Do not add interpretation, recommendations, or content not present in the document.

Example (SOL long setup, green box 82.94→88.62 above, red box 82.94→79.88 below, cyan arrow up):
SOL: bu poza daha girmedi, aşağı gidip yukarı çıkarken girişe gelince girmek için.
  Direction: long
  Entry: 82.94
  TP: 88.62
  SL: 79.88
  Leverage: n/a
  Other levels: n/a

Output the dump only — no preamble, no closing remarks.
"""


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
8. Extract ALL readable content into `extracted_text`:
   - Written text (headings, bullet points, labels)
   - For chart images: read every visible ticker symbol, price level, and annotation
     (e.g. "BTC: short bölgesindeyiz. Key levels: 81,358 / 78,773 / 77,734 / 74,500")
   - For market analysis PDFs: list each asset with its notes and key price levels
   This field is critical — it is what the chat agent reads to answer user questions.

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
        vision_model: str | None = None,
        extract_model: str | None = None,
        storage: DocumentStorage | None = None,
    ) -> None:
        self._api_key = api_key or settings.gemini_api_key
        # `model` stays as the legacy default (used by `_extract`, single-shot multimodal+schema).
        # `vision_model` and `extract_model` let callers split the two-pass PDF pipeline so the
        # cheapest model is used per role. Each falls back to `model`, then to settings.
        self._model = model or settings.gemini_model
        self._vision_model = vision_model or settings.vision_model or self._model
        self._extract_model = extract_model or settings.extract_model or self._model
        self._storage = storage or NoOpStorage()
        if not self._api_key:
            raise ProcessorError("GEMINI_API_KEY is not configured")
        log.info(
            "document_processor models | default=%s | vision=%s | extract=%s",
            self._model, self._vision_model, self._extract_model,
        )

    def extract_profile(self, source: DocumentSource) -> ProfileExtraction:
        """Parse a profile-relevant document. Storage hook fires before the LLM call.

        Strategy:
        - Text-rich PDFs (banka ekstresi vb.): pdfplumber → text-only call (cheap, 1 call).
        - Image-heavy PDFs (chart screenshots): two-pass —
            (1) vision dump call (no schema, focused on reading numbers off charts)
            (2) structured extraction from the dumped text (cheap text-only call).
          This gives much better numeric accuracy than a single multimodal+schema call.
        - Other (images, docx): single multimodal+schema call (current behavior).
        """
        if source.mime_type == "application/pdf":
            pre_text = _extract_pdf_text(source.data)
            pages_estimate = max(1, source.size_bytes // (100 * 1024))
            if len(pre_text) > pages_estimate * 200:
                log.info("PDF is text-rich (%d chars); skipping multimodal call", len(pre_text))
                prompt_with_text = PROFILE_PROMPT + f"\n\nDocument text:\n{pre_text}"
                result = self._extract_text_only(prompt_with_text)
                if not result.extracted_text:
                    result = result.model_copy(update={"extracted_text": pre_text})
                return result

            log.info("PDF is image-heavy (%d chars extracted); two-pass vision+schema", len(pre_text))
            vision_dump = self._vision_dump(source)
            prompt_with_text = (
                PROFILE_PROMPT
                + "\n\nDocument text (already extracted from the file, INCLUDING chart numbers):\n"
                + vision_dump
            )
            result = self._extract_text_only(prompt_with_text)
            # Always overwrite extracted_text with the high-fidelity vision dump.
            return result.model_copy(update={"extracted_text": vision_dump})

        return self._extract(source, ProfileExtraction, PROFILE_PROMPT)

    def _vision_dump(self, source: DocumentSource) -> str:
        """First-pass: ask Gemini to dump every visible label/number — no schema constraint."""
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=self._api_key)
        if source.needs_file_api:
            uploaded = client.files.upload(
                file=source.data,
                config={"mime_type": source.mime_type, "display_name": source.filename},
            )
            doc_part = types.Part.from_uri(file_uri=uploaded.uri, mime_type=source.mime_type)
        else:
            doc_part = types.Part.from_bytes(data=source.data, mime_type=source.mime_type)

        try:
            response = client.models.generate_content(
                model=self._vision_model,
                contents=[doc_part, VISION_DUMP_PROMPT],
                config=types.GenerateContentConfig(temperature=0.0),
            )
        except Exception as exc:  # noqa: BLE001
            raise ProcessorError(f"Gemini vision dump failed: {exc}") from exc

        text = (getattr(response, "text", "") or "").strip()
        if not text:
            raise ProcessorError("Gemini vision dump returned empty text")
        return text

    def _extract_text_only(self, prompt: str) -> ProfileExtraction:
        """Send a plain-text prompt to Gemini (no file bytes). Much cheaper for text-rich PDFs."""
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=self._api_key)
        try:
            response = client.models.generate_content(
                model=self._extract_model,
                contents=[prompt],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=ProfileExtraction,
                    temperature=0.0,
                ),
            )
        except Exception as exc:  # noqa: BLE001
            raise ProcessorError(f"Gemini text-only generation failed: {exc}") from exc

        parsed = getattr(response, "parsed", None)
        if isinstance(parsed, ProfileExtraction):
            return parsed
        raw = getattr(response, "text", "") or ""
        if not raw.strip():
            raise ProcessorError("Gemini returned an empty response")
        try:
            return ProfileExtraction.model_validate_json(raw)
        except Exception as exc:  # noqa: BLE001
            raise ProcessorError(f"document did not match expected schema: {exc}") from exc

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
