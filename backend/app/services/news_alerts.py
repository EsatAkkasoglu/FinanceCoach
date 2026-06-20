"""Proactive news-alert matching.

Runs at the tail of every ``news_collector.poll_all_feeds`` cycle: each freshly
collected (and enriched) article is checked against the user's watchlist and a
global importance threshold. A match writes a ``NewsAlert`` row the frontend
surfaces in its notification center + toast so the user can react.

Split in two so the decision logic is unit-testable without a DB:
  • ``match_article`` — pure: (article fields, watchlist, thresholds) → reason/priority.
  • ``generate_alerts`` — loads the watchlist, loops, persists, dedups per (user, article).

Single-user prototype: watchlist + alerts are scoped to ``user_id`` (default 1).
"""
from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.models import NewsAlert, NewsArticle, WatchKind, Watchlist
from app.settings import settings

log = logging.getLogger("fincoach.news_alerts")

# Priorities (mirrored in the frontend for sort/styling).
PRIORITY_WATCHLIST = 2
PRIORITY_IMPORTANCE = 1


def _ticker_set(tickers: str | None) -> set[str]:
    """'AAPL,ASELS.IS' → {'AAPL', 'ASELS.IS'} (upper-cased, blanks dropped)."""
    if not tickers:
        return set()
    return {t.strip().upper() for t in tickers.split(",") if t.strip()}


def match_article(
    *,
    tickers: str | None,
    title: str,
    snippet: str | None,
    category: str | None,
    sentiment_score: float | None,
    symbols: set[str],
    keywords: list[str],
    important_categories: set[str],
    score_threshold: float,
) -> tuple[str, int] | None:
    """Decide whether an article is alert-worthy. Pure — no DB / network.

    Returns ``(reason, priority)`` for the strongest match, or ``None``. A
    watchlist hit (symbol or keyword) outranks a generic importance hit.
    """
    # 1) Watchlist symbols — exact membership in extracted tickers, or a
    #    whole-word mention in the title (covers articles enrichment didn't tag).
    if symbols:
        present = _ticker_set(tickers)
        title_upper = (title or "").upper()
        for sym in symbols:
            if sym in present or re.search(rf"\b{re.escape(sym)}\b", title_upper):
                return f"watchlist:{sym}", PRIORITY_WATCHLIST

    # 2) Watchlist keywords — substring match across title + snippet.
    if keywords:
        haystack = f"{title or ''} {snippet or ''}".lower()
        for kw in keywords:
            if kw and kw in haystack:
                return f"watchlist:{kw}", PRIORITY_WATCHLIST

    # 3) Global importance — market-moving category or a strong sentiment swing.
    cat = (category or "").strip().lower()
    if cat and cat in important_categories:
        return f"category:{cat}", PRIORITY_IMPORTANCE
    if sentiment_score is not None and abs(sentiment_score) >= score_threshold:
        return "sentiment", PRIORITY_IMPORTANCE

    return None


def _load_watchlist(db, user_id: int) -> tuple[set[str], list[str]]:
    """Return (symbol set upper-cased, keyword list lower-cased) for a user."""
    rows = db.execute(select(Watchlist).where(Watchlist.user_id == user_id)).scalars().all()
    symbols: set[str] = set()
    keywords: list[str] = []
    for r in rows:
        val = (r.value or "").strip()
        if not val:
            continue
        if r.kind == WatchKind.KEYWORD.value:
            keywords.append(val.lower())
        else:
            symbols.add(val.upper())
    return symbols, keywords


def generate_alerts(db, articles: list[NewsArticle], *, user_id: int = 1) -> int:
    """Raise NewsAlert rows for matching articles. Returns the number created.

    Best-effort and idempotent: the ``(user_id, article_id)`` unique constraint
    means re-running over the same articles never double-alerts. Never raises —
    a matching failure must not break the poll cycle.
    """
    if not settings.news_alert_enabled or not articles:
        return 0
    try:
        symbols, keywords = _load_watchlist(db, user_id)
        important = settings.news_alert_category_set
        threshold = settings.news_alert_score_threshold
        # With no watchlist, only fire when the importance threshold can match
        # (category/sentiment) — otherwise every article would alert.
        created = 0
        for art in articles:
            if art.id is None:
                continue
            hit = match_article(
                tickers=art.tickers,
                title=art.title,
                snippet=art.snippet,
                category=art.category,
                sentiment_score=art.sentiment_score,
                symbols=symbols,
                keywords=keywords,
                important_categories=important,
                score_threshold=threshold,
            )
            if hit is None:
                continue
            reason, priority = hit
            db.add(NewsAlert(user_id=user_id, article_id=art.id, reason=reason, priority=priority))
            try:
                db.commit()
                created += 1
            except IntegrityError:
                db.rollback()  # already alerted for this (user, article) — skip
        return created
    except Exception:  # noqa: BLE001 — alert generation must not break the poll
        log.exception("news alert generation failed")
        return 0


def alert_payload(alert: NewsAlert, article: NewsArticle | None = None) -> dict[str, Any]:
    """Serialize an alert + its article for the notification center."""
    a = article if article is not None else alert.article
    return {
        "id": alert.id,
        "reason": alert.reason,
        "priority": alert.priority,
        "created_at": alert.created_at.isoformat() if alert.created_at else None,
        "read": alert.read_at is not None,
        "article": {
            "id": a.id,
            "title": a.title,
            "url": a.url,
            "source": a.source,
            "summary": a.summary,
            "snippet": a.snippet,
            "lang": a.lang,
            "category": a.category,
            "sentiment": a.sentiment,
            "sentiment_score": a.sentiment_score,
            "tickers": a.tickers,
            "published_at": a.published_at.isoformat() if a.published_at else None,
        }
        if a is not None
        else None,
    }
