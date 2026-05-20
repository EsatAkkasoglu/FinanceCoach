"""Embedding-based storage for extracted document text.

Chunks the extracted text, embeds with Google text-embedding-004,
and upserts into the project's ChromaDB collection so passages can
be retrieved later by the memory agent.
"""
from __future__ import annotations

import hashlib
import logging
import time

import chromadb

from app.settings import settings

log = logging.getLogger("fincoach.doc_embeddings")

COLLECTION_NAME = "document_chunks"
EMBEDDING_MODEL = "text-embedding-004"
CHUNK_SIZE = 800
CHUNK_OVERLAP = 100


def _chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    chunks: list[str] = []
    start = 0
    while start < len(text):
        chunks.append(text[start : start + size])
        start += size - overlap
    return [c for c in chunks if c.strip()]


class ChromaEmbeddingStorage:
    """Embeds extracted document text and stores chunks in ChromaDB."""

    def __init__(self, user_id: int = 1) -> None:
        self._user_id = user_id
        self._client = chromadb.PersistentClient(path=settings.chroma_path)
        self._collection = self._client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )

    def store(
        self,
        filename: str,
        extracted_text: str,
        conv_id: str | None = None,
    ) -> int:
        """Chunk, embed, and upsert. Returns the number of chunks stored."""
        from google import genai

        if not extracted_text.strip():
            return 0

        chunks = _chunk_text(extracted_text)
        if not chunks:
            return 0

        client = genai.Client(api_key=settings.gemini_api_key)
        try:
            result = client.models.embed_content(
                model=EMBEDDING_MODEL,
                contents=chunks,
            )
        except Exception:
            log.warning("embedding call failed for %s", filename, exc_info=True)
            return 0

        embeddings = [e.values for e in result.embeddings]
        now = int(time.time())
        ids: list[str] = []
        metadatas: list[dict] = []

        for i, chunk in enumerate(chunks):
            # Stable ID so re-uploading the same file overwrites instead of duplicating.
            chunk_id = hashlib.sha256(
                f"{self._user_id}:{filename}:{i}".encode()
            ).hexdigest()[:32]
            ids.append(chunk_id)
            meta: dict[str, str | int] = {
                "user_id": self._user_id,
                "filename": filename,
                "chunk_index": i,
                "created_at": now,
            }
            if conv_id:
                meta["conv_id"] = conv_id
            metadatas.append(meta)

        self._collection.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=chunks,
            metadatas=metadatas,
        )
        log.info("stored %d chunk(s) for '%s' (user=%s)", len(chunks), filename, self._user_id)
        return len(chunks)
