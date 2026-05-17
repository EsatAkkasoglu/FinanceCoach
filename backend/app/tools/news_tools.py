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


def _is_turkish_ticker(query: str) -> bool:
    """BIST tickers come through as 'ASELS.IS', 'THYAO.IS', etc."""
    q = query.strip().upper()
    return q.endswith(".IS") or q.endswith(".E")


def _fetch_google_news_rss(query: str, *, turkish: bool, limit: int) -> list[dict[str, Any]]:
    base = "https://news.google.com/rss/search"
    locale = "?hl=tr&gl=TR&ceid=TR:tr" if turkish else "?hl=en-US&gl=US&ceid=US:en"
    url = f"{base}{locale}&q={quote(query)}"
    feed = feedparser.parse(url)
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


@tool
def search_news(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Search recent finance news. Returns title, source, published_at, url, snippet."""
    # BIST tickers (ASELS.IS, THYAO.IS …) → Turkish Google News with bare
    # ticker + "hisse" keyword. NewsAPI's English-only stream misses these.
    if _is_turkish_ticker(query):
        bare = query.strip().upper().removesuffix(".IS").removesuffix(".E")
        return _fetch_google_news_rss(f"{bare} hisse", turkish=True, limit=limit)

    try:
        articles = _fetch_newsapi(query, page_size=limit)
    except Exception as exc:
        log.warning("NewsAPI failed (%s); falling back to Google News RSS", exc)
        return _fetch_google_news_rss(query, turkish=False, limit=limit)

    if not articles:
        # NewsAPI returned nothing (free tier coverage gaps, rate limit, etc.)
        # — try Google News so the UI isn't blank.
        return _fetch_google_news_rss(query, turkish=False, limit=limit)

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
