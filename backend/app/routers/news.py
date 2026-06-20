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

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from app.auth import get_current_user_id
from app.db.models import NewsAlert, NewsArticle, User, WatchKind, Watchlist
from app.db.session import SessionLocal
from app.routers.admin import require_admin
from app.services.news_alerts import alert_payload
from app.services.news_collector import poll_all_feeds, poll_if_stale

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
        "tickers": a.tickers,
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
    # Opportunistic refresh: on Cloud Run an idle-reaped instance has no live
    # scheduler, so a read kicks a background poll when the feed is stale. No-op
    # when fresh or a poll is already running; never blocks this response.
    poll_if_stale()
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


# ── Proactive alerts (notification center) ───────────────────────────────────


@router.get("/alerts")
def list_alerts(
    unread_only: bool = Query(default=False),
    limit: int = Query(default=30, ge=1, le=100),
    user_id: int = Depends(get_current_user_id),
):
    """Proactive news alerts for the current user, newest first, + unread count."""
    with SessionLocal() as db:
        stmt = (
            select(NewsAlert)
            .where(NewsAlert.user_id == user_id)
            .order_by(NewsAlert.priority.desc(), NewsAlert.created_at.desc())
            .limit(limit)
        )
        if unread_only:
            stmt = stmt.where(NewsAlert.read_at.is_(None))
        alerts = db.execute(stmt).scalars().all()
        unread = db.execute(
            select(func.count())
            .select_from(NewsAlert)
            .where(NewsAlert.user_id == user_id, NewsAlert.read_at.is_(None))
        ).scalar_one()
        return {
            "items": [alert_payload(a) for a in alerts],
            "count": len(alerts),
            "unread_count": int(unread or 0),
        }


class MarkReadRequest(BaseModel):
    ids: list[int] | None = Field(default=None, description="Alert ids; omit to mark all read")


@router.post("/alerts/read")
def mark_alerts_read(body: MarkReadRequest, user_id: int = Depends(get_current_user_id)):
    """Mark the given alert ids read, or all of the user's alerts when omitted."""
    with SessionLocal() as db:
        stmt = select(NewsAlert).where(
            NewsAlert.user_id == user_id, NewsAlert.read_at.is_(None)
        )
        if body.ids:
            stmt = stmt.where(NewsAlert.id.in_(body.ids))
        now = datetime.utcnow()
        updated = 0
        for alert in db.execute(stmt).scalars():
            alert.read_at = now
            updated += 1
        db.commit()
        return {"ok": True, "updated": updated}


# ── Watchlist (what to alert on) ─────────────────────────────────────────────


def _watch_dict(w: Watchlist) -> dict:
    return {"id": w.id, "kind": w.kind, "value": w.value}


@router.get("/watchlist")
def list_watchlist(user_id: int = Depends(get_current_user_id)):
    """The user's alert subscriptions (symbols + keywords)."""
    with SessionLocal() as db:
        rows = db.execute(
            select(Watchlist).where(Watchlist.user_id == user_id).order_by(Watchlist.created_at)
        ).scalars().all()
        return {"items": [_watch_dict(w) for w in rows]}


class WatchlistAddRequest(BaseModel):
    kind: str = Field(default=WatchKind.SYMBOL.value, description="symbol | keyword")
    value: str = Field(min_length=1, max_length=128)


@router.post("/watchlist", status_code=201)
def add_watchlist_item(body: WatchlistAddRequest, user_id: int = Depends(get_current_user_id)):
    """Add a symbol or keyword to watch. Idempotent on (kind, value)."""
    kind = body.kind.strip().lower()
    if kind not in (WatchKind.SYMBOL.value, WatchKind.KEYWORD.value):
        raise HTTPException(422, "kind must be 'symbol' or 'keyword'")
    # Normalize: symbols upper-cased, keywords lower-cased (matches the matcher).
    raw = body.value.strip()
    if not raw:
        raise HTTPException(422, "value is required")
    value = raw.upper() if kind == WatchKind.SYMBOL.value else raw.lower()
    with SessionLocal() as db:
        existing = db.execute(
            select(Watchlist).where(
                Watchlist.user_id == user_id, Watchlist.kind == kind, Watchlist.value == value
            )
        ).scalar_one_or_none()
        if existing is not None:
            return _watch_dict(existing)
        row = Watchlist(user_id=user_id, kind=kind, value=value)
        db.add(row)
        db.commit()
        db.refresh(row)
        return _watch_dict(row)


@router.delete("/watchlist/{item_id}")
def remove_watchlist_item(item_id: int, user_id: int = Depends(get_current_user_id)):
    """Remove one watchlist subscription by id."""
    with SessionLocal() as db:
        row = db.execute(
            select(Watchlist).where(Watchlist.id == item_id, Watchlist.user_id == user_id)
        ).scalar_one_or_none()
        if row is None:
            raise HTTPException(404, "watchlist item not found")
        db.delete(row)
        db.commit()
        return {"ok": True}
