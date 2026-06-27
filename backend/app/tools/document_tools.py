"""Document retrieval tools — semantic search over uploaded document chunks.

The PDF/image upload pipeline stores extracted text chunks in the ChromaDB
collection ``document_chunks`` (see ``services/document_processor/chroma_storage.py``).
Each chunk carries metadata ``{user_id, filename, chunk_index, created_at, conv_id?}``.

This module exposes a single ``@tool`` the document_parser agent calls to
retrieve passages relevant to the user's current question. The collection is
shared across users but filtered by ``user_id`` at query time so passages
never leak across accounts.

Design notes
------------
* The same embedding model used at write-time (``gemini-embedding-2``) is used
  at query-time to keep the vector space consistent.
* We embed the query through ``google-genai`` directly rather than going via
  Chroma's default sentence-transformers embedder, because the stored vectors
  were produced by gemini-embedding-2 and mixing embedders breaks recall.
* Results are returned ranked by cosine distance (lower = closer). We expose
  a similarity score in [0, 1] (``1 - distance``) so the agent can decide when
  retrieval is too weak to answer.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

import chromadb
from langchain_core.tools import tool

from app.agents._injection_guard import defang_untrusted
from app.auth import get_current_user_id_or_none
from app.settings import settings

log = logging.getLogger("fincoach.tools.documents")

COLLECTION_NAME = "document_chunks"
EMBEDDING_MODEL = "gemini-embedding-2"

# Floor below which we treat retrieval as "no relevant passage found".
# Calibrated against gemini-embedding-2 cosine distances on Turkish/English
# trading notes; can be loosened if recall is too aggressive.
MIN_SIMILARITY = 0.35


@lru_cache(maxsize=1)
def _client() -> chromadb.PersistentClient:
    return chromadb.PersistentClient(path=settings.chroma_path)


def _collection():
    return _client().get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


def _embed_query(text: str) -> list[float] | None:
    """Embed a single query string with the same model used at ingestion.

    Returns ``None`` on failure so the caller can fall back to a text-based
    query (Chroma's default embedder) — strictly worse recall, but better
    than crashing the chat turn.
    """
    try:
        from google import genai
        client = genai.Client(api_key=settings.gemini_api_key)
        result = client.models.embed_content(model=EMBEDDING_MODEL, contents=text)
        return list(result.embeddings[0].values)
    except Exception as exc:  # noqa: BLE001
        log.warning("query embedding failed (%s) — degrading to text query", exc)
        return None


@tool
def search_documents(query: str, k: int = 5) -> list[dict[str, Any]]:
    """Semantic search over the user's uploaded documents (PDFs, images).

    Use this whenever the user asks about content that may live in an
    uploaded document — trade setups, price levels (entry/TP/SL), broker
    statements, invoices, anything attached during the conversation.

    Args:
        query: Natural-language question to search for. Pass the user's
            current question verbatim plus any disambiguating ticker /
            asset name. Example: "SOL entry TP SL levels".
        k: Number of passages to return. Default 5; raise to 8-10 if the
            first result is ambiguous.

    Returns:
        List of ``{text, filename, chunk_index, similarity}`` dicts ordered
        by similarity (highest first). Returns ``[]`` when no passage meets
        the minimum-similarity threshold — answer accordingly.
    """
    user_id = get_current_user_id_or_none()
    if user_id is None:
        return []

    col = _collection()
    if col.count() == 0:
        return []

    where = {"user_id": user_id}
    embedding = _embed_query(query)

    try:
        if embedding is not None:
            res = col.query(
                query_embeddings=[embedding],
                n_results=max(1, min(k, 20)),
                where=where,
                include=["documents", "metadatas", "distances"],
            )
        else:
            res = col.query(
                query_texts=[query],
                n_results=max(1, min(k, 20)),
                where=where,
                include=["documents", "metadatas", "distances"],
            )
    except Exception as exc:  # noqa: BLE001
        log.warning("document search failed: %s", exc)
        return []

    docs = (res.get("documents") or [[]])[0]
    metas = (res.get("metadatas") or [[]])[0]
    dists = (res.get("distances") or [[]])[0]

    hits: list[dict[str, Any]] = []
    for text, meta, dist in zip(docs, metas, dists, strict=False):
        if not text:
            continue
        # Chroma returns cosine distance; convert to similarity in [0, 1].
        similarity = max(0.0, 1.0 - float(dist))
        if similarity < MIN_SIMILARITY:
            continue
        hits.append({
            # Uploaded-document text is untrusted: defang any injection control
            # phrases before it enters the agent's context (OWASP LLM01).
            "text": defang_untrusted(text),
            "filename": (meta or {}).get("filename"),
            "chunk_index": (meta or {}).get("chunk_index"),
            "similarity": round(similarity, 3),
        })
    log.info(
        "search_documents | user=%s | q=%r | returned=%d / scanned=%d",
        user_id, query[:80], len(hits), len(docs),
    )
    return hits


@tool
def list_uploaded_documents() -> list[dict[str, Any]]:
    """List every document currently indexed for the user.

    Useful when the user asks "what files have I uploaded" or the agent
    needs to disambiguate between multiple attached documents. Returns
    one entry per unique filename with its chunk count.
    """
    user_id = get_current_user_id_or_none()
    if user_id is None:
        return []

    col = _collection()
    if col.count() == 0:
        return []
    try:
        res = col.get(where={"user_id": user_id}, include=["metadatas"])
    except Exception as exc:  # noqa: BLE001
        log.warning("list_uploaded_documents failed: %s", exc)
        return []

    by_file: dict[str, int] = {}
    for meta in res.get("metadatas") or []:
        name = (meta or {}).get("filename") or "(unknown)"
        by_file[name] = by_file.get(name, 0) + 1

    return [{"filename": name, "chunks": n} for name, n in sorted(by_file.items())]
