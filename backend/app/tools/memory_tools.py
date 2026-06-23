"""Memory tools — semantic search and write into ChromaDB.

ChromaDB is local + persistent. Each memory entry is a chunk of past
conversation or a transaction summary. The Memory agent and the supervisor
use these to surface relevant context for any new query."""
from __future__ import annotations

import logging
from datetime import datetime
from functools import lru_cache
from typing import Any

import chromadb
from langchain_core.tools import tool

from app.auth import get_current_user_id_or_none
from app.settings import settings

log = logging.getLogger("fincoach.tools.memory")


@lru_cache(maxsize=1)
def _client() -> chromadb.PersistentClient:
    return chromadb.PersistentClient(path=settings.chroma_path)


def _collection():
    """Per-user collection so memories never leak across accounts."""
    user_id = get_current_user_id_or_none()
    suffix = f"u{user_id}" if user_id is not None else "anon"
    return _client().get_or_create_collection(name=f"fincoach_memory_{suffix}")


@tool
def query_memory(text: str, k: int = 5) -> list[dict[str, Any]]:
    """Search the user's memory (past chats, decisions, transactions) for
    semantically similar items. Returns up to k most relevant chunks with
    their metadata (date, kind, source)."""
    col = _collection()
    if col.count() == 0:
        return []
    res = col.query(query_texts=[text], n_results=k)
    docs = res.get("documents", [[]])[0]
    metas = res.get("metadatas", [[]])[0]
    return [{"text": d, "metadata": m} for d, m in zip(docs, metas, strict=False)]


@tool
def upsert_memory(text: str, kind: str = "chat", source_id: str | None = None) -> dict[str, Any]:
    """Write a chunk of text into the user's memory. ``kind`` is one of
    'chat', 'transaction', 'decision'. ``source_id`` lets us avoid
    duplicates by overwriting prior entries for the same source."""
    col = _collection()
    mid = source_id or f"{kind}:{col.count() + 1}"
    col.upsert(ids=[mid], documents=[text], metadatas=[{"kind": kind}])
    return {"id": mid, "stored": True}


def upsert_chat_turn(user_msg: str, assistant_msg: str, agent: str | None = None) -> str | None:
    """Persist a completed user→assistant exchange into ChromaDB so the
    Memory agent can recall it later.

    Called from the /chat endpoint after streaming finishes. Errors are
    swallowed (memory is best-effort, must never break a chat reply).
    """
    user_msg = (user_msg or "").strip()
    assistant_msg = (assistant_msg or "").strip()
    if not user_msg or not assistant_msg:
        return None
    try:
        col = _collection()
        now = datetime.utcnow()
        date_iso = now.strftime("%Y-%m-%d")
        text = (
            f"[{date_iso}] User: {user_msg}\n"
            f"Assistant ({agent or 'fincoach'}): {assistant_msg}"
        )
        mid = f"chat:{int(now.timestamp() * 1000)}"
        col.upsert(
            ids=[mid],
            documents=[text],
            metadatas=[{
                "kind": "chat",
                "agent": agent or "",
                "date": date_iso,
            }],
        )
        return mid
    except Exception as exc:  # noqa: BLE001
        log.warning("upsert_chat_turn failed: %s", exc)
        return None
