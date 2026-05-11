"""FastAPI router exposing /documents/parse — does NOT persist by default."""
from __future__ import annotations

import logging

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.services.document_processor.base import (
    DocumentSource,
    NoOpStorage,
    ProcessorError,
    SUPPORTED_MIME_TYPES,
)
from app.services.document_processor.gemini_processor import GeminiDocumentProcessor
from app.services.document_processor.schemas import ProfileExtraction

log = logging.getLogger("fincoach.documents")

router = APIRouter(prefix="/documents", tags=["documents"])

MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # File-API path covers anything larger via streaming, but keep a hard cap.


@router.post("/parse", response_model=ProfileExtraction)
async def parse_document(file: UploadFile = File(...)) -> ProfileExtraction:
    """Run a one-shot Gemini extraction on the uploaded document.

    The file is held in memory only; nothing is written to disk or DB.
    Swap `NoOpStorage()` for a persistent backend later without touching this handler.
    """
    mime = (file.content_type or "").lower()
    if mime not in SUPPORTED_MIME_TYPES:
        raise HTTPException(status_code=415, detail=f"unsupported content type: {mime or 'unknown'}")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="empty upload")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="file exceeds 50 MB limit")

    try:
        source = DocumentSource(
            filename=file.filename or "upload",
            mime_type=mime,
            data=data,
        )
    except ProcessorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    processor = GeminiDocumentProcessor(storage=NoOpStorage())
    try:
        return processor.extract_profile(source)
    except ProcessorError as exc:
        log.warning("document parse failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
