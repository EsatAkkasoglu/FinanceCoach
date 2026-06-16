"""News tools — NewsAPI + RSS (Yahoo Finance, CoinDesk, Google News), cached.

Routing by asset class so a ticker like ``BTC-USD`` or a 3-letter TEFAS fund
code resolves to a *name* before searching — NewsAPI/Google News return junk
for raw tickers. Resolution sources mirror the rest of the system:
  • crypto  → CoinDesk symbol→name map (services.coindesk)
  • fund    → TEFAS universe title (tools.fund_tools)

RSS is the backbone for crypto and Turkish assets (no API key, broad coverage);
NewsAPI stays the primary path for English/global stocks.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import quote

import feedparser
import requests
from joblib import Memory
from langchain_core.tools import tool
from sqlalchemy import or_, select

from app.db.models import NewsArticle
from app.db.session import SessionLocal
from app.settings import settings

log = logging.getLogger("fincoach.tools.news")

# How far back the DB-first path looks before falling through to live feeds.
_DB_NEWS_WINDOW_HOURS = 48
_cache = Memory(location=".joblib_cache", verbose=0)

# A ticker that looks like a TEFAS fund code: 2-6 ASCII letters, no digits.
# Digits would make it a US/forex symbol; funds are letters only (AFA, IIH…).
_FUND_CODE_RE = re.compile(r"^[A-Z]{2,6}$")


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


def _is_crypto_ticker(query: str) -> bool:
    """Crypto holdings arrive as 'BTC-USD', 'SOL-USD', … or a bare known symbol."""
    from app.services.coindesk import _SYMBOL_TO_ID  # noqa: PLC0415

    q = query.strip().upper()
    if q.endswith("-USD") or q.endswith("-USDT"):
        return True
    return q in _SYMBOL_TO_ID


def _resolve_crypto_name(query: str) -> str:
    """'BTC-USD' / 'BTC' → 'Bitcoin'. Falls back to the bare symbol."""
    from app.services import coindesk as cg  # noqa: PLC0415

    base = query.strip().upper().split("-")[0]
    try:
        for hit in cg.search_coins(base):
            if (hit.get("symbol") or "").upper() == base and hit.get("name"):
                return str(hit["name"])
    except cg.CoinDeskError as exc:
        log.warning("crypto name resolve failed for %s: %s", base, exc)
    return base


def _resolve_fund_title(code: str) -> str | None:
    """3-letter TEFAS code → fund title (for a meaningful news query)."""
    from datetime import date as date_cls  # noqa: PLC0415

    from app.tools.fund_tools import _fold_tr, _universe_cached  # noqa: PLC0415

    target = _fold_tr(code)
    try:
        universe = _universe_cached("YAT", today_iso=date_cls.today().isoformat())
    except Exception as exc:  # noqa: BLE001
        log.warning("fund universe lookup failed for %s: %s", code, exc)
        return None
    for f in universe:
        if _fold_tr(f.get("code") or "") == target:
            return (f.get("title") or "").strip() or None
    return None


def _normalize_rss(feed: Any, *, limit: int, default_source: str) -> list[dict[str, Any]]:
    return [
        {
            "title": e.title,
            "source": e.get("source", {}).get("title", default_source),
            "published_at": e.get("published"),
            "url": e.link,
            "snippet": e.get("summary", "")[:240],
            # Live feeds aren't enriched — keep the key set uniform with the
            # DB-first path so callers see a stable shape.
            "sentiment": None,
            "category": None,
        }
        for e in feed.entries[:limit]
    ]


def _fetch_rss(url: str, *, limit: int, default_source: str) -> list[dict[str, Any]]:
    """Generic RSS pull via feedparser, normalised to the news item shape."""
    try:
        feed = feedparser.parse(url)
    except Exception as exc:  # noqa: BLE001
        log.warning("RSS fetch failed (%s): %s", default_source, exc)
        return []
    return _normalize_rss(feed, limit=limit, default_source=default_source)


def _fetch_google_news_rss(query: str, *, turkish: bool, limit: int) -> list[dict[str, Any]]:
    base = "https://news.google.com/rss/search"
    locale = "?hl=tr&gl=TR&ceid=TR:tr" if turkish else "?hl=en-US&gl=US&ceid=US:en"
    url = f"{base}{locale}&q={quote(query)}"
    return _fetch_rss(url, limit=limit, default_source="Google News")


def _fetch_yahoo_headline_rss(symbol: str, *, limit: int) -> list[dict[str, Any]]:
    """Yahoo Finance per-symbol headline RSS — works for stocks, ETFs, crypto."""
    url = (
        "https://feeds.finance.yahoo.com/rss/2.0/headline"
        f"?s={quote(symbol)}&region=US&lang=en-US"
    )
    return _fetch_rss(url, limit=limit, default_source="Yahoo Finance")


# Always-on crypto RSS feeds (no key, broad market coverage).
_CRYPTO_RSS = [
    ("https://www.coindesk.com/arc/outboundfeeds/rss/", "CoinDesk"),
    ("https://cointelegraph.com/rss", "Cointelegraph"),
]


def _dedupe(items: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for it in items:
        key = (it.get("title") or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(it)
        if len(out) >= limit:
            break
    return out


def _crypto_news(query: str, limit: int) -> list[dict[str, Any]]:
    """Resolve the coin name, then blend Yahoo per-symbol + name-based Google News."""
    name = _resolve_crypto_name(query)
    symbol = query.strip().upper()
    if not symbol.endswith("-USD") and not symbol.endswith("-USDT"):
        symbol = f"{symbol.split('-')[0]}-USD"

    items: list[dict[str, Any]] = []
    items += _fetch_yahoo_headline_rss(symbol, limit=limit)
    items += _fetch_google_news_rss(f"{name} crypto", turkish=False, limit=limit)
    if len(items) < limit:
        for url, label in _CRYPTO_RSS:
            items += _fetch_rss(url, limit=limit, default_source=label)
    return _dedupe(items, limit=limit)


def _fund_news(code: str, limit: int) -> list[dict[str, Any]]:
    """Resolve the TEFAS code to a fund title, then search Turkish news."""
    title = _resolve_fund_title(code)
    if not title:
        return []
    return _fetch_google_news_rss(f"{title} fon", turkish=True, limit=limit)


# ── DB-first path (background collector's news_article table) ─────────────────


def _db_search_terms(raw: str, ac: str) -> list[str]:
    """Candidate text terms for matching the query against stored headlines.

    Mirrors the live-path resolution (ticker → name) so a 'BTC-USD' query also
    matches 'Bitcoin' headlines; always falls back to the raw query so free-text
    topics still match.
    """
    if not raw or len(raw) < 2:
        return []
    up = raw.upper()
    if ac == "crypto" or _is_crypto_ticker(raw):
        terms = [_resolve_crypto_name(raw), up.split("-")[0]]
    elif ac == "fund":
        # Only resolve fund titles on an explicit hint — the bare _FUND_CODE_RE
        # also matches common all-caps words ("FED", "IT"), and resolving them
        # would fire a TEFAS lookup on every such free-text query. Unhinted fund
        # codes still resolve correctly on the live fallback path below.
        title = _resolve_fund_title(raw)
        terms = [title] if title else [raw]
    elif _is_turkish_ticker(raw):
        terms = [up.removesuffix(".IS").removesuffix(".E")]
    else:
        terms = [raw]

    out: list[str] = []
    seen: set[str] = set()
    for t in terms:
        t = (t or "").strip()
        if len(t) < 2 or t.lower() in seen:
            continue
        seen.add(t.lower())
        out.append(t)
    return out


def _db_article_to_item(a: NewsArticle) -> dict[str, Any]:
    return {
        "title": a.title,
        "source": a.source,
        "published_at": a.published_at.isoformat() if a.published_at else None,
        "url": a.url,
        "snippet": a.snippet or a.summary or "",
        # Bonus pre-computed enrichment the agent may use (or ignore).
        "sentiment": a.sentiment,
        "category": a.category,
    }


def _db_news_lookup(raw: str, ac: str, limit: int) -> list[dict[str, Any]]:
    """Serve recent stored headlines matching the query. Empty list = fall through."""
    terms = _db_search_terms(raw, ac)
    if not terms:
        return []
    cutoff = datetime.utcnow() - timedelta(hours=_DB_NEWS_WINDOW_HOURS)
    try:
        with SessionLocal() as db:
            conds = []
            for t in terms:
                like = f"%{t}%"
                conds.append(NewsArticle.title.ilike(like))
                conds.append(NewsArticle.snippet.ilike(like))
            stmt = (
                select(NewsArticle)
                .where(NewsArticle.fetched_at >= cutoff, or_(*conds))
                .order_by(
                    NewsArticle.published_at.desc().nullslast(),
                    NewsArticle.fetched_at.desc(),
                )
                .limit(limit)
            )
            rows = db.execute(stmt).scalars().all()
    except Exception as exc:  # noqa: BLE001 — DB-first is best-effort; live path is the fallback
        log.warning("DB-first news lookup failed (%s); falling back to live feeds", exc)
        return []
    return [_db_article_to_item(a) for a in rows]


@tool
def search_news(query: str, limit: int = 5, asset_class: str = "") -> list[dict[str, Any]]:
    """Search recent finance news.

    Returns a list of items with a uniform shape: title, source, published_at,
    url, snippet, sentiment, category. DB-served results (from the background
    collector) carry pre-computed sentiment (positive/neutral/negative) and
    category; live-feed results return null for both.

    Args:
        query: ticker, fund code, or free-text topic. Raw tickers like
            'BTC-USD' or a 3-letter TEFAS code are auto-resolved to a name
            before searching.
        limit: max items.
        asset_class: optional hint ('crypto', 'fund', 'stock', 'etf', …) so
            the right resolver/feed is used. Pass it whenever you know the
            asset class — it makes crypto and Turkish-fund news far more
            relevant than a raw-ticker search.
    """
    raw = (query or "").strip()
    ac = (asset_class or "").strip().lower()

    # DB-first: the background collector pre-fetches + enriches headlines into
    # the news_article table. Serve fresh matches from there (ms-level); fall
    # through to the live RSS/NewsAPI paths below when there's no coverage (e.g.
    # a US ticker outside the polled feeds, or the collector hasn't run yet).
    cached = _db_news_lookup(raw, ac, limit)
    if cached:
        return cached

    # Crypto — resolve symbol → name, blend Yahoo + Google News + crypto RSS.
    if ac == "crypto" or _is_crypto_ticker(raw):
        items = _crypto_news(raw, limit)
        if items:
            return items
        return _fetch_google_news_rss(raw, turkish=False, limit=limit)

    # TEFAS fund — resolve code → title, search Turkish news.
    if ac == "fund" or _FUND_CODE_RE.match(raw.upper()):
        items = _fund_news(raw, limit)
        if items:
            return items
        # Not a real fund code (or no news) — fall through to generic paths.

    # BIST tickers (ASELS.IS, THYAO.IS …) → Turkish Google News with bare
    # ticker + "hisse" keyword. NewsAPI's English-only stream misses these.
    if _is_turkish_ticker(raw):
        bare = raw.upper().removesuffix(".IS").removesuffix(".E")
        return _fetch_google_news_rss(f"{bare} hisse", turkish=True, limit=limit)

    try:
        articles = _fetch_newsapi(raw, page_size=limit)
    except Exception as exc:
        log.warning("NewsAPI failed (%s); falling back to Google News RSS", exc)
        return _fetch_google_news_rss(raw, turkish=False, limit=limit)

    if not articles:
        # NewsAPI returned nothing (free tier coverage gaps, rate limit, etc.)
        # — try Google News so the UI isn't blank.
        return _fetch_google_news_rss(raw, turkish=False, limit=limit)

    return [
        {
            "title": a["title"],
            "source": a["source"]["name"],
            "published_at": a["publishedAt"],
            "url": a["url"],
            "snippet": (a.get("description") or "")[:240],
            "sentiment": None,
            "category": None,
        }
        for a in articles
    ]
