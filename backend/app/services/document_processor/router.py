"""FastAPI router exposing /documents/* — parse, list, delete."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app.auth import get_current_user_id
from app.services.document_processor.base import (
    DocumentSource,
    NoOpStorage,
    ProcessorError,
    SUPPORTED_MIME_TYPES,
)
from app.services.document_processor.chroma_storage import ChromaEmbeddingStorage
from app.services.document_processor.gemini_processor import GeminiDocumentProcessor
from app.services.document_processor.schemas import ProfileExtraction


class DocumentEntry(BaseModel):
    filename: str
    created_at: int       # unix timestamp
    created_at_iso: str   # ISO-8601 for the frontend
    chunk_count: int


class DocumentListResponse(BaseModel):
    documents: list[DocumentEntry]

log = logging.getLogger("fincoach.documents")

router = APIRouter(prefix="/documents", tags=["documents"])

# Hard cap — files above this are rejected so we never fall through to the File API.
MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB


@router.post("/parse", response_model=ProfileExtraction)
async def parse_document(
    file: UploadFile = File(...),
    conv_id: str | None = Form(default=None),
    # Authenticates the request AND binds current_user_id_var so the
    # downstream Chroma write is scoped to the correct user. Without this
    # dependency the contextvar stays None and the document_parser agent
    # (which filters by user_id) can never retrieve the chunks.
    user_id: int = Depends(get_current_user_id),
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

    # Embed extracted text into ChromaDB so the document_parser agent can
    # retrieve it on later turns. MUST scope to the authenticated user so
    # the document_parser's search (which filters by the request's user_id)
    # actually returns these chunks. Hardcoding user_id=1 here was a
    # leftover from the single-user prototype phase — once real auth is in
    # play (multiple registered users) it silently breaks RAG retrieval.
    if result.extracted_text:
        try:
            storage = ChromaEmbeddingStorage(user_id=user_id)
            chunks_stored = storage.store(
                filename=source.filename,
                extracted_text=result.extracted_text,
                conv_id=conv_id,
            )
            log.info(
                "embedded %d chunk(s) from '%s' for user=%s",
                chunks_stored, source.filename, user_id,
            )
        except Exception:
            log.warning("embedding storage failed; continuing", exc_info=True)

    return result


@router.get("", response_model=DocumentListResponse)
def list_documents(user_id: int = Depends(get_current_user_id)) -> DocumentListResponse:
    """List all documents previously uploaded by this user (from ChromaDB metadata)."""
    storage = ChromaEmbeddingStorage(user_id=user_id)
    raw = storage.list_documents()
    entries: list[DocumentEntry] = []
    for d in raw:
        ts = d.get("created_at") or 0
        try:
            iso = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        except (OSError, OverflowError, ValueError):
            iso = ""
        entries.append(DocumentEntry(
            filename=d["filename"],
            created_at=ts,
            created_at_iso=iso,
            chunk_count=d.get("chunk_count", 0),
        ))
    return DocumentListResponse(documents=entries)


@router.delete("/{filename:path}", status_code=204)
def delete_document(
    filename: str,
    user_id: int = Depends(get_current_user_id),
) -> None:
    """Delete all ChromaDB chunks for a given filename."""
    storage = ChromaEmbeddingStorage(user_id=user_id)
    storage.delete_document(filename)
