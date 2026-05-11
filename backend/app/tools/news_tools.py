"""News tools — NewsAPI + Google News RSS, with caching."""
from __future__ import annotations

import logging
from typing import Any

import feedparser
import requests
from urllib.parse import quote
from joblib import Memory
from langchain_core.tools import tool

from app.settings import settings

log = logging.getLogger("fincoach.tools.news")
_cache = Memory(location=".joblib_cache", verbose=0)


@_cache.cache
def _fetch_newsapi(q: str, page_size: int = 10) -> list[dict[str, Any]]:
    if not settings.news_api_key:
        return []
    resp = requests.get(
        "https://newsapi.org/v2/everything",
        params={"q": q, "pageSize": page_size, "language": "en", "sortBy": "publishedAt"},
        headers={"X-Api-Key": settings.news_api_key},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json().get("articles", [])


@tool
def search_news(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Search recent finance news. Returns title, source, published_at, url, snippet."""
    try:
        articles = _fetch_newsapi(query, page_size=limit)
    except Exception as exc:
        log.warning("NewsAPI failed (%s); falling back to Google News RSS", exc)
        feed = feedparser.parse(f"https://news.google.com/rss/search?q={quote(query)}")
        return [
            {
                "title": e.title,
                "source": e.get("source", {}).get("title", "Google News"),
                "published_at": e.get("published"),
                "url": e.link,
                "snippet": e.get("summary", "")[:240],
            }
            for e in feed.entries[:limit]
        ]
    return [
        {
            "title": a["title"],
            "source": a["source"]["name"],
            "published_at": a["publishedAt"],
            "url": a["url"],
            "snippet": (a.get("description") or "")[:240],
        }
        for a in articles
    ]
