"""Tests for the GeminiDocumentProcessor + /documents/parse route.

Two layers:
  - Pure unit tests on `DocumentSource` / schemas — no API calls.
  - `@pytest.mark.network` round-trips that hit Gemini with the real PDF
    fixtures the user provided. They are skipped automatically when
    GEMINI_API_KEY is not set, so CI without secrets stays green.
"""
from __future__ import annotations

import pytest

from app.settings import settings

from app.services.document_processor import (
    DocumentSource,
    NoOpStorage,
    ProcessorError,
    ProfileExtraction,
)
from app.services.document_processor.base import INLINE_LIMIT_BYTES


# ── Pure unit tests ────────────────────────────────────────────────────────


def test_document_source_rejects_empty_bytes():
    with pytest.raises(ProcessorError):
        DocumentSource(filename="x.pdf", mime_type="application/pdf", data=b"")


def test_document_source_rejects_unknown_mime():
    with pytest.raises(ProcessorError):
        DocumentSource(filename="x.exe", mime_type="application/x-msdownload", data=b"abc")


def test_document_source_routes_large_files_to_file_api():
    big = DocumentSource(
        filename="big.pdf",
        mime_type="application/pdf",
        data=b"\0" * (INLINE_LIMIT_BYTES + 1),
    )
    small = DocumentSource(filename="s.pdf", mime_type="application/pdf", data=b"%PDF-1.4")
    assert big.needs_file_api is True
    assert small.needs_file_api is False


def test_noop_storage_returns_none():
    src = DocumentSource(filename="x.pdf", mime_type="application/pdf", data=b"%PDF-1.4")
    assert NoOpStorage().persist(src) is None


def test_profile_extraction_schema_validates_minimal_payload():
    """Making sure Gemini's structured-output target is permissive enough."""
    payload = {
        "doc_type": "bank_statement",
        "doc_type_confidence": 0.9,
        "summary": "Bank statement for May 2026.",
    }
    parsed = ProfileExtraction.model_validate(payload)
    assert parsed.suggested_holdings == []
    assert parsed.suggested_profile is None


# ── Endpoint contract (no Gemini call) ────────────────────────────────────


def test_parse_route_rejects_unsupported_mime(client):
    r = client.post(
        "/documents/parse",
        files={"file": ("evil.exe", b"MZ\x90\x00", "application/x-msdownload")},
    )
    assert r.status_code == 415


def test_parse_route_rejects_empty_upload(client):
    r = client.post(
        "/documents/parse",
        files={"file": ("empty.pdf", b"", "application/pdf")},
    )
    assert r.status_code == 400


# ── Real Gemini round-trip ─────────────────────────────────────────────────

NEED_KEY = pytest.mark.skipif(
    not settings.gemini_api_key,
    reason="GEMINI_API_KEY not configured (.env or env var)",
)


@pytest.mark.network
@NEED_KEY
@pytest.mark.parametrize("filename", ["hesap_ozeti.pdf", "hesap_hareketleri.pdf"])
def test_extract_profile_on_real_pdf(fixtures_dir, filename):
    """Round-trip a real Turkish bank PDF through Gemini and validate the
    structured-output contract. We don't assert on specific numbers (the LLM
    can read them differently each run); we assert the response is shape-valid
    and that Gemini classified the document as a bank/broker artefact."""
    from app.services.document_processor import GeminiDocumentProcessor

    pdf_bytes = (fixtures_dir / filename).read_bytes()
    src = DocumentSource(filename=filename, mime_type="application/pdf", data=pdf_bytes)

    processor = GeminiDocumentProcessor()
    result = processor.extract_profile(src)

    assert isinstance(result, ProfileExtraction)
    assert result.summary  # non-empty
    assert 0.0 <= result.doc_type_confidence <= 1.0
    # These are bank statements; the model should not classify them as receipts/IDs.
    assert result.doc_type in {"bank_statement", "broker_statement", "other"}


@pytest.mark.network
@NEED_KEY
def test_parse_route_with_real_pdf(client, fixtures_dir):
    """Full HTTP round-trip via TestClient → Gemini → JSON response."""
    pdf_bytes = (fixtures_dir / "hesap_ozeti.pdf").read_bytes()
    r = client.post(
        "/documents/parse",
        files={"file": ("hesap_ozeti.pdf", pdf_bytes, "application/pdf")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "doc_type" in body
    assert "summary" in body
    assert isinstance(body.get("suggested_holdings"), list)
    assert isinstance(body.get("missing_or_unclear"), list)
