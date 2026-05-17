"""Memory / conversation search routes.

Lets the sidebar surface semantically similar past chats so the user can
find a thread without remembering its title. Backed by the same per-user
ChromaDB collection used by the Memory agent.

Endpoints:
    GET /memory/search?q=...&k=5
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.auth import get_current_user_id  # noqa: F401  scopes via current-user context var
from app.tools.memory_tools import query_memory

log = logging.getLogger("fincoach.memory")
router = APIRouter(prefix="/memory", tags=["memory"])


class MemoryHit(BaseModel):
    text: str
    metadata: dict


class SearchResponse(BaseModel):
    query: str
    hits: list[MemoryHit]


@router.get("/search", response_model=SearchResponse)
def search(
    q: str = Query(..., min_length=2, max_length=200),
    k: int = Query(5, ge=1, le=20),
    _user_id: int = Depends(get_current_user_id),
):
    raw = query_memory.invoke({"text": q, "k": k})
    hits = [
        MemoryHit(text=h.get("text") or "", metadata=h.get("metadata") or {})
        for h in raw
        if isinstance(h, dict)
    ]
    return SearchResponse(query=q, hits=hits)
