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
EMBEDDING_MODEL = "gemini-embedding-2"
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
        embeddings: list[list[float]] = []
        try:
            for chunk in chunks:
                result = client.models.embed_content(
                    model=EMBEDDING_MODEL,
                    contents=chunk,
                )
                embeddings.append(result.embeddings[0].values)
        except Exception:
            log.warning("embedding call failed for %s", filename, exc_info=True)
            return 0
        now = int(time.time())
        ids: list[str] = []
        metadatas: list[dict] = []

        for i in range(len(chunks)):
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

    def list_documents(self) -> list[dict]:
        """Return one entry per unique filename for this user, sorted newest-first.

        We query only chunk_index=0 documents so each file appears exactly once.
        Returns dicts with: filename, created_at (unix ts), chunk_count.
        """
        try:
            # Get all chunk_index=0 entries for this user — one per file.
            result = self._collection.get(
                where={"$and": [{"user_id": self._user_id}, {"chunk_index": 0}]},
                include=["metadatas"],
            )
        except Exception:
            log.warning("list_documents query failed for user=%s", self._user_id, exc_info=True)
            return []

        metadatas = result.get("metadatas") or []
        docs: list[dict] = []
        seen: set[str] = set()
        for meta in metadatas:
            fname = meta.get("filename", "")
            if not fname or fname in seen:
                continue
            seen.add(fname)
            docs.append({
                "filename": fname,
                "created_at": meta.get("created_at", 0),
                "chunk_count": self._count_chunks(fname),
            })

        docs.sort(key=lambda d: d["created_at"], reverse=True)
        return docs

    def _count_chunks(self, filename: str) -> int:
        """Count how many chunks are stored for a given filename."""
        try:
            result = self._collection.get(
                where={"$and": [{"user_id": self._user_id}, {"filename": filename}]},
                include=[],
            )
            return len(result.get("ids") or [])
        except Exception:
            return 0

    def delete_document(self, filename: str) -> int:
        """Delete all chunks for a given filename. Returns number of chunks removed."""
        try:
            result = self._collection.get(
                where={"$and": [{"user_id": self._user_id}, {"filename": filename}]},
                include=[],
            )
            ids = result.get("ids") or []
            if ids:
                self._collection.delete(ids=ids)
            log.info("deleted %d chunk(s) for '%s' (user=%s)", len(ids), filename, self._user_id)
            return len(ids)
        except Exception:
            log.warning("delete_document failed for '%s' user=%s", filename, self._user_id, exc_info=True)
            return 0
