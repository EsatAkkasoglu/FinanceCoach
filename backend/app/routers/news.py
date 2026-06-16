"""News feed routes.

  GET  /news/feed   — read pre-collected, enriched headlines (DB, ms-level).
  POST /news/poll   — trigger one collection cycle. Admin-gated; intended for an
                      external scheduler (Cloud Scheduler → Cloud Run) where the
                      in-process BackgroundScheduler can't run at min-instances=0.

The feed is global (news isn't user-scoped) but still requires a valid bearer
token, matching the rest of the API.
"""
from __future__ import annotations

import asyncio
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select

from app.auth import get_current_user_id
from app.db.models import NewsArticle, User
from app.db.session import SessionLocal
from app.routers.admin import require_admin
from app.services.news_collector import poll_all_feeds

router = APIRouter(prefix="/news", tags=["news"])


def _article_dict(a: NewsArticle) -> dict:
    return {
        "id": a.id,
        "title": a.title,
        "url": a.url,
        "source": a.source,
        "published_at": a.published_at.isoformat() if a.published_at else None,
        "snippet": a.snippet,
        "summary": a.summary,
        "lang": a.lang,
        "category": a.category,
        "sentiment": a.sentiment,
        "sentiment_score": a.sentiment_score,
        "fetched_at": a.fetched_at.isoformat() if a.fetched_at else None,
    }


@router.get("/feed")
def news_feed(
    q: str | None = Query(default=None, description="Free-text match on title/snippet"),
    category: str | None = None,
    lang: str | None = None,
    since: datetime | None = Query(default=None, description="ISO datetime lower bound"),
    limit: int = Query(default=30, ge=1, le=100),
    _user_id: int = Depends(get_current_user_id),
):
    """Return recent enriched headlines, newest first."""
    with SessionLocal() as db:
        stmt = select(NewsArticle)
        if q:
            like = f"%{q.strip()}%"
            stmt = stmt.where(
                or_(NewsArticle.title.ilike(like), NewsArticle.snippet.ilike(like))
            )
        if category:
            stmt = stmt.where(NewsArticle.category == category.strip().lower())
        if lang:
            stmt = stmt.where(NewsArticle.lang == lang.strip().lower())
        if since:
            stmt = stmt.where(NewsArticle.published_at >= since)
        stmt = stmt.order_by(
            NewsArticle.published_at.desc().nullslast(),
            NewsArticle.fetched_at.desc(),
        ).limit(limit)
        rows = db.execute(stmt).scalars().all()
        return {"items": [_article_dict(a) for a in rows], "count": len(rows)}


@router.post("/poll")
async def trigger_poll(_: User = Depends(require_admin)):
    """Run one collection cycle now. For external schedulers on Cloud Run.

    ``poll_all_feeds`` is self-contained — it catches all internal errors and
    returns a summary — so there is no raw-exception path here that could leak a
    provider API key. It is run in a worker thread so the event loop is not
    blocked by the synchronous fetch/enrich/DB work.
    """
    summary = await asyncio.to_thread(poll_all_feeds)
    return {"ok": True, **summary}
