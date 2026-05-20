"""FastAPI router exposing /documents/parse — processes inline, embeds into ChromaDB."""
from __future__ import annotations

import logging

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.services.document_processor.base import (
    DocumentSource,
    NoOpStorage,
    ProcessorError,
    SUPPORTED_MIME_TYPES,
)
from app.services.document_processor.chroma_storage import ChromaEmbeddingStorage
from app.services.document_processor.gemini_processor import GeminiDocumentProcessor
from app.services.document_processor.schemas import ProfileExtraction

log = logging.getLogger("fincoach.documents")

router = APIRouter(prefix="/documents", tags=["documents"])

# Hard cap — files above this are rejected so we never fall through to the File API.
MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB


@router.post("/parse", response_model=ProfileExtraction)
async def parse_document(
    file: UploadFile = File(...),
    conv_id: str | None = Form(default=None),
) -> ProfileExtraction:
    """Run a one-shot Gemini extraction on the uploaded document.

    The raw bytes are never written to disk.  Extracted text is chunked and
    embedded with text-embedding-004, then stored in ChromaDB for later retrieval.
    """
    mime = (file.content_type or "").lower()
    if mime not in SUPPORTED_MIME_TYPES:
        raise HTTPException(status_code=415, detail=f"unsupported content type: {mime or 'unknown'}")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="empty upload")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="file exceeds 20 MB limit")

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
        result = processor.extract_profile(source)
    except ProcessorError as exc:
        log.warning("document parse failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    # Embed extracted text into ChromaDB so the memory agent can retrieve it later.
    if result.extracted_text:
        try:
            storage = ChromaEmbeddingStorage(user_id=1)
            chunks_stored = storage.store(
                filename=source.filename,
                extracted_text=result.extracted_text,
                conv_id=conv_id,
            )
            log.info("embedded %d chunk(s) from '%s'", chunks_stored, source.filename)
        except Exception:
            log.warning("embedding storage failed; continuing", exc_info=True)

    return result
