"""Background news collector.

Polls a set of standing RSS feeds on an interval, deduplicates, enriches each
new headline with Gemini (sentiment / category / 1-line summary), and writes the
result to the ``news_article`` table. ``tools.news_tools.search_news`` and
``GET /news/feed`` then read pre-computed rows in milliseconds instead of
hitting feeds on every request.

Design notes (see docs/BACKEND_IMPROVEMENT_GUIDE.md and the review that scoped
this):
  • Sync end-to-end. Runs in an APScheduler ``BackgroundScheduler`` worker
    thread (matching the existing TEFAS prewarm thread), so synchronous
    ``feedparser`` / ``SessionLocal`` / LangChain ``.invoke()`` never touch the
    asyncio event loop that serves ``/chat`` SSE.
  • ``poll_all_feeds()`` is the single entrypoint — driven both by the in-process
    scheduler (desktop / always-on) and by ``POST /news/poll`` (Cloud Scheduler →
    Cloud Run, where the in-process scheduler can't fire while the instance is
    frozen at min-instances=0).
  • Dedup is hash-based (canonical URL + normalized-title SHA1). Embedding-based
    near-duplicate collapse is left as a marked hook in ``_find_duplicates``.
"""
from __future__ import annotations

import hashlib
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import feedparser
import requests
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.db.models import FeedState, NewsArticle
from app.db.session import SessionLocal
from app.services.news_alerts import generate_alerts
from app.settings import settings

log = logging.getLogger("fincoach.news_collector")

_USER_AGENT = "FinCoach/0.1 (+https://github.com/; news collector)"

# Tracking params stripped during URL canonicalization (dedup across re-syndication).
_TRACKING_PREFIXES = ("utm_",)
_TRACKING_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid", "igshid", "ref", "ref_src"}

# Turkish-specific letters → cheap language heuristic for headlines.
_TR_CHARS = set("ğşıİçöüĞŞÇÖÜ")


# ── Pure helpers (no network / DB — unit-testable) ───────────────────────────


def canonical_url(url: str) -> str:
    """Strip tracking params + fragment and normalize, for dedup keying."""
    if not url:
        return ""
    parts = urlsplit(url.strip())
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=False)
        if not k.lower().startswith(_TRACKING_PREFIXES) and k.lower() not in _TRACKING_KEYS
    ]
    path = parts.path.rstrip("/") or parts.path
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), ""))


def title_hash(title: str) -> str:
    """SHA1 of a normalized title — collapses same-story reposts across sources."""
    norm = re.sub(r"[^\w\s]", "", (title or "").lower(), flags=re.UNICODE)
    norm = re.sub(r"\s+", " ", norm).strip()
    return hashlib.sha1(norm.encode("utf-8")).hexdigest() if norm else ""


def detect_lang(title: str, feed_url: str = "") -> str:
    """'tr' if the headline or feed host is clearly Turkish, else 'en'."""
    host = urlsplit(feed_url).netloc.lower()
    if host.endswith(".tr") or "/tr" in feed_url or ".com.tr" in host:
        return "tr"
    if any(ch in _TR_CHARS for ch in (title or "")):
        return "tr"
    return "en"


def _parse_published(entry: Any) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        ts = entry.get(key)
        if ts:
            try:
                return datetime(*ts[:6])
            except (TypeError, ValueError):
                continue
    return None


def parse_entries(parsed: Any, *, feed_url: str) -> list[dict[str, Any]]:
    """feedparser result → normalized article dicts (with dedup keys attached)."""
    source = ""
    feed_meta = getattr(parsed, "feed", {}) or {}
    if isinstance(feed_meta, dict):
        source = (feed_meta.get("title") or "").strip()
    if not source:
        source = urlsplit(feed_url).netloc.removeprefix("www.")

    out: list[dict[str, Any]] = []
    for e in getattr(parsed, "entries", []) or []:
        title = (e.get("title") or "").strip()
        link = (e.get("link") or "").strip()
        if not title or not link:
            continue
        out.append(
            {
                "title": title[:512],
                "url": link[:1024],
                "canonical_url": canonical_url(link)[:1024],
                "content_hash": title_hash(title),
                "source": source[:128],
                "published_at": _parse_published(e),
                "snippet": (e.get("summary") or "")[:240] or None,
                "lang": detect_lang(title, feed_url),
            }
        )
    return out


def dedupe_within(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop intra-batch duplicates by canonical_url then content_hash."""
    seen_url: set[str] = set()
    seen_hash: set[str] = set()
    out: list[dict[str, Any]] = []
    for it in items:
        cu = it.get("canonical_url") or ""
        ch = it.get("content_hash") or ""
        if not cu or cu in seen_url or (ch and ch in seen_hash):
            continue
        seen_url.add(cu)
        if ch:
            seen_hash.add(ch)
        out.append(it)
    return out


# ── Enrichment (Gemini batch structured output) ──────────────────────────────


class HeadlineEnrichment(BaseModel):
    index: int = Field(description="Index of the headline in the provided list")
    sentiment: str = Field(description="positive | neutral | negative")
    score: float = Field(description="Sentiment from -1.0 (very negative) to 1.0 (very positive)")
    category: str = Field(
        description="One of: earnings, macro, regulation, ma, crypto, market, tech, other"
    )
    summary: str = Field(description="One short sentence summarizing the headline")
    tickers: list[str] = Field(
        default_factory=list,
        description=(
            "Stock/crypto/fund symbols explicitly named in the headline (BIST → '.IS' "
            "suffix, e.g. ASELS.IS; crypto bare, e.g. BTC). Empty list if none."
        ),
    )


class BatchEnrichment(BaseModel):
    items: list[HeadlineEnrichment]


_VALID_SENTIMENT = {"positive", "neutral", "negative"}
_VALID_CATEGORY = {"earnings", "macro", "regulation", "ma", "crypto", "market", "tech", "other"}

_enrich_llm = None


def _get_enrich_llm():
    global _enrich_llm
    if _enrich_llm is None:
        # Lazy import keeps the API-key requirement out of pure-function tests.
        from app.agents.llm import get_llm  # noqa: PLC0415

        _enrich_llm = get_llm(settings.gemini_structured_temperature).with_structured_output(
            BatchEnrichment
        )
    return _enrich_llm


_ENRICH_PROMPT = """You are a financial news classifier. For each numbered headline below,
return its sentiment (positive/neutral/negative) for an investor, a sentiment score in
[-1, 1], a single category, a one-sentence summary, and any explicitly-named tradable
symbols. Headlines may be English or Turkish.

Categories: earnings, macro, regulation, ma (mergers & acquisitions), crypto, market, tech, other.

Tickers: list only symbols clearly named in the headline. Use the canonical form —
BIST stocks get a '.IS' suffix (e.g. ASELS.IS, THYAO.IS), crypto stays bare (e.g. BTC, ETH),
US equities as-is (e.g. AAPL). Return an empty list when no symbol is named.

Return one item per headline, preserving the given index.

Headlines:
{headlines}"""


def _apply_enrichment(result: BatchEnrichment, chunk: list[dict[str, Any]]) -> None:
    """Copy a model's batch result back onto the article dicts (validated)."""
    for item in result.items:
        if not 0 <= item.index < len(chunk):
            continue
        sentiment = item.sentiment.strip().lower()
        category = item.category.strip().lower()
        art = chunk[item.index]
        art["sentiment"] = sentiment if sentiment in _VALID_SENTIMENT else "neutral"
        art["sentiment_score"] = max(-1.0, min(1.0, float(item.score)))
        art["category"] = category if category in _VALID_CATEGORY else "other"
        art["summary"] = (item.summary or "").strip()[:280] or None
        tickers = ",".join(t.strip().upper() for t in (item.tickers or []) if t and t.strip())
        art["tickers"] = tickers[:256] or None
        art["enriched"] = 1


def _enrich_chunk(chunk: list[dict[str, Any]]) -> None:
    """Enrich one chunk in place, splitting on failure so one bad headline can't
    sink the whole batch.

    A single malformed structured-output item makes the *entire* ``.invoke``
    parse raise — previously that dropped enrichment for all 40 articles in the
    batch. Instead, on failure we bisect and retry each half, narrowing the blast
    radius down to the single offending headline (which is then stored raw).
    """
    if not chunk:
        return
    listing = "\n".join(f"{i}. {a['title']}" for i, a in enumerate(chunk))
    try:
        result: BatchEnrichment = _get_enrich_llm().invoke(
            _ENRICH_PROMPT.format(headlines=listing)
        )
    except Exception:  # noqa: BLE001 — never let enrichment break collection
        if len(chunk) == 1:
            log.warning("news enrichment failed for 1 headline; stored raw", exc_info=True)
            return
        mid = len(chunk) // 2
        _enrich_chunk(chunk[:mid])
        _enrich_chunk(chunk[mid:])
        return
    _apply_enrichment(result, chunk)


def enrich_batch(articles: list[dict[str, Any]]) -> None:
    """Mutate ``articles`` in place, filling sentiment/score/category/summary.

    Best-effort: on any failure the affected articles are left unenriched (stored
    raw) and a warning is logged — the collector never crashes on enrichment.
    """
    if not articles or not settings.news_enrich_enabled:
        return
    if not settings.gemini_api_key:
        return

    batch_size = max(1, settings.news_enrich_batch_size)
    for start in range(0, len(articles), batch_size):
        _enrich_chunk(articles[start : start + batch_size])


# ── Fetch (conditional GET via feedparser) ───────────────────────────────────


def _bozo_result(exc: Exception) -> Any:
    """A parsed-feed stand-in marking a fetch failure (so the loop counts it errored)."""
    parsed = feedparser.parse(b"")
    parsed["bozo"] = 1
    parsed["bozo_exception"] = exc
    parsed["status"] = None
    return parsed


def _fetch_one(url: str, etag: str | None, modified: str | None) -> tuple[str, Any]:
    """Fetch+parse a single feed with conditional GET and a hard timeout.

    ``feedparser.parse(url)`` has no timeout knob, so a hung feed server could
    block the whole poll indefinitely. We fetch with ``requests`` (bounded by
    ``news_fetch_timeout``) and hand the bytes to feedparser, preserving the
    304/etag/last-modified conditional-GET behavior the loop relies on.
    """
    headers = {"User-Agent": _USER_AGENT}
    if etag:
        headers["If-None-Match"] = etag
    if modified:
        headers["If-Modified-Since"] = modified
    try:
        resp = requests.get(url, headers=headers, timeout=settings.news_fetch_timeout)
    except requests.RequestException as exc:
        return url, _bozo_result(exc)

    if resp.status_code == 304:
        parsed = feedparser.parse(b"")
        parsed["status"] = 304
        return url, parsed

    parsed = feedparser.parse(resp.content)
    parsed["status"] = resp.status_code
    # Surface caching validators the loop persists for the next conditional GET.
    if resp.headers.get("ETag"):
        parsed["etag"] = resp.headers["ETag"]
    if resp.headers.get("Last-Modified"):
        parsed["modified"] = resp.headers["Last-Modified"]
        parsed["headers"] = {"last-modified": resp.headers["Last-Modified"]}
    return url, parsed


# ── DB-touching orchestration ────────────────────────────────────────────────


def _find_duplicates(db, candidates: list[dict[str, Any]]) -> set[str]:
    """Return canonical_urls already present (by URL or by content_hash).

    Embedding-based near-duplicate detection (paraphrases across sources) would
    slot in here: embed each candidate title with ``gemini-embedding-2`` (the
    project's standard model — see services/document_processor/chroma_storage.py),
    query a news Chroma collection, and add canonical_urls whose nearest
    neighbour is below a tuned cosine threshold. Deferred for v1.
    """
    urls = [c["canonical_url"] for c in candidates if c.get("canonical_url")]
    hashes = [c["content_hash"] for c in candidates if c.get("content_hash")]
    dupes: set[str] = set()
    if urls:
        existing_urls = set(
            db.execute(
                select(NewsArticle.canonical_url).where(NewsArticle.canonical_url.in_(urls))
            ).scalars()
        )
        dupes |= {c["canonical_url"] for c in candidates if c["canonical_url"] in existing_urls}
    if hashes:
        existing_hashes = set(
            db.execute(
                select(NewsArticle.content_hash).where(NewsArticle.content_hash.in_(hashes))
            ).scalars()
        )
        dupes |= {
            c["canonical_url"]
            for c in candidates
            if c.get("content_hash") and c["content_hash"] in existing_hashes
        }
    return dupes


def _persist(db, articles: list[dict[str, Any]]) -> int:
    """Insert article rows. Bulk first; on a unique-constraint race, per-row."""
    rows = [NewsArticle(**_row_kwargs(a)) for a in articles]
    try:
        db.add_all(rows)
        db.commit()
        return len(rows)
    except IntegrityError:
        db.rollback()
    # Fallback: insert individually, skipping rows that collide.
    inserted = 0
    for a in articles:
        try:
            db.add(NewsArticle(**_row_kwargs(a)))
            db.commit()
            inserted += 1
        except IntegrityError:
            db.rollback()
    return inserted


def _row_kwargs(a: dict[str, Any]) -> dict[str, Any]:
    return {
        "canonical_url": a["canonical_url"],
        "url": a["url"],
        "title": a["title"],
        "source": a.get("source") or "",
        "published_at": a.get("published_at"),
        "snippet": a.get("snippet"),
        "lang": a.get("lang") or "en",
        "tickers": a.get("tickers"),
        "category": a.get("category"),
        "sentiment": a.get("sentiment"),
        "sentiment_score": a.get("sentiment_score"),
        "summary": a.get("summary"),
        "content_hash": a.get("content_hash") or "",
        "enriched": a.get("enriched", 0),
    }


# Guards against overlapping runs — the interval scheduler and a manual
# POST /news/poll (Cloud Scheduler) can otherwise fire concurrently, doubling
# every feed fetch and Gemini enrichment call for the same cycle.
_poll_lock = threading.Lock()


def poll_all_feeds() -> dict[str, Any]:
    """Run one poll cycle, unless one is already in progress (then skip).

    The actual work is in ``_poll_all_feeds``; this wrapper enforces a single
    in-flight poll so a manual trigger can't pile on top of the scheduled one.
    """
    if not _poll_lock.acquire(blocking=False):
        log.info("news poll already running — skipping this trigger")
        return {
            "skipped": True, "feeds_polled": 0, "feeds_unchanged": 0, "feeds_errored": 0,
            "fetched": 0, "new": 0, "enriched": 0, "alerts": 0, "pruned": 0,
        }
    try:
        return _poll_all_feeds()
    finally:
        _poll_lock.release()


def _poll_all_feeds() -> dict[str, Any]:
    """Fetch every configured feed, dedup, enrich new items, persist. Sync.

    Returns a small summary dict; never raises (logs and returns partial counts)
    so the scheduler keeps running.
    """
    started = time.monotonic()
    feeds = settings.news_feed_urls
    summary: dict[str, Any] = {
        "feeds_polled": 0,
        "feeds_unchanged": 0,
        "feeds_errored": 0,
        "fetched": 0,
        "new": 0,
        "enriched": 0,
        "alerts": 0,
        "pruned": 0,
    }
    if not feeds:
        log.info("news poll skipped — no feeds configured")
        return summary

    try:
        with SessionLocal() as db:
            states = {
                s.url: s
                for s in db.execute(select(FeedState).where(FeedState.url.in_(feeds))).scalars()
            }

            workers = min(len(feeds), 8)
            with ThreadPoolExecutor(max_workers=workers) as pool:
                results = list(
                    pool.map(
                        lambda u: _fetch_one(
                            u,
                            states[u].etag if u in states else None,
                            states[u].last_modified if u in states else None,
                        ),
                        feeds,
                    )
                )

            candidates: list[dict[str, Any]] = []
            now = datetime.utcnow()
            for url, parsed in results:
                state = states.get(url)
                if state is None:
                    state = FeedState(url=url)
                    db.add(state)
                status = getattr(parsed, "status", None)
                state.last_polled_at = now
                state.last_status = status
                if getattr(parsed, "bozo", 0) and not getattr(parsed, "entries", None):
                    state.error_count = (state.error_count or 0) + 1
                    summary["feeds_errored"] += 1
                    log.warning("feed parse error %s: %s", url, getattr(parsed, "bozo_exception", ""))
                elif status == 304:
                    summary["feeds_unchanged"] += 1
                else:
                    state.error_count = 0
                    summary["feeds_polled"] += 1
                    new_etag = getattr(parsed, "etag", None)
                    new_mod = getattr(parsed, "modified", None)
                    if not new_mod:
                        headers = getattr(parsed, "headers", {}) or {}
                        new_mod = headers.get("last-modified") or headers.get("Last-Modified")
                    if new_etag:
                        state.etag = new_etag[:512]
                    if new_mod:
                        state.last_modified = str(new_mod)[:256]
                    entries = parse_entries(parsed, feed_url=url)
                    summary["fetched"] += len(entries)
                    candidates.extend(entries)
                # `state` is either session-tracked (loaded above) or freshly
                # added — its mutations flush automatically on commit.
            db.commit()

            # Dedup: within-batch, then against the DB.
            candidates = dedupe_within(candidates)
            if candidates:
                dupes = _find_duplicates(db, candidates)
                fresh = [c for c in candidates if c["canonical_url"] not in dupes]
            else:
                fresh = []

            if fresh:
                enrich_batch(fresh)
                summary["enriched"] = sum(1 for a in fresh if a.get("enriched"))
                summary["new"] = _persist(db, fresh)
                # Match the just-stored articles against watchlists / importance
                # and raise proactive alerts. Re-query so we have row ids + the
                # canonical persisted values.
                fresh_urls = [c["canonical_url"] for c in fresh if c.get("canonical_url")]
                if fresh_urls:
                    stored = (
                        db.execute(
                            select(NewsArticle).where(NewsArticle.canonical_url.in_(fresh_urls))
                        )
                        .scalars()
                        .all()
                    )
                    summary["alerts"] = generate_alerts(db, stored)

            # Retention prune.
            cutoff = datetime.utcnow() - timedelta(days=max(1, settings.news_retention_days))
            pruned = db.execute(
                delete(NewsArticle).where(NewsArticle.fetched_at < cutoff)
            ).rowcount
            db.commit()
            summary["pruned"] = pruned or 0
    except Exception:  # noqa: BLE001 — scheduler must survive any failure
        log.exception("news poll failed")
        return summary

    summary["elapsed_ms"] = int((time.monotonic() - started) * 1000)
    log.info(
        "news poll: %d polled / %d unchanged / %d err → %d fetched, %d new, %d enriched, "
        "%d alerts, %d pruned (%dms)",
        summary["feeds_polled"], summary["feeds_unchanged"], summary["feeds_errored"],
        summary["fetched"], summary["new"], summary["enriched"], summary["alerts"],
        summary["pruned"], summary.get("elapsed_ms", 0),
    )
    return summary


# ── Scheduler lifecycle (BackgroundScheduler — thread, not asyncio) ───────────

_scheduler = None


def start_news_scheduler() -> None:
    """Start the in-process poll loop if enabled. Idempotent."""
    global _scheduler
    if not settings.news_collector_enabled:
        log.info("news collector disabled (FINCOACH_NEWS_COLLECTOR_ENABLED=false)")
        return
    if _scheduler is not None:
        return
    if settings.is_cloud_run:
        # The instance freezes when idle at min-instances=0, so the interval
        # timer would silently never fire. Don't start it (it's misleading);
        # polling must be driven by Cloud Scheduler → POST /news/poll.
        log.info(
            "news collector: Cloud Run detected — in-process scheduler NOT started; "
            "drive polling via Cloud Scheduler → POST /news/poll"
        )
        return

    from apscheduler.schedulers.background import BackgroundScheduler  # noqa: PLC0415

    sched = BackgroundScheduler(daemon=True)
    sched.add_job(
        poll_all_feeds,
        "interval",
        minutes=max(1, settings.news_poll_minutes),
        max_instances=1,
        coalesce=True,
        # First run shortly after boot so the feed isn't empty on a cold start,
        # but after TEFAS prewarm / startup settle. Timezone-aware so APScheduler
        # honors the exact instant regardless of its configured/local timezone.
        next_run_time=datetime.now(UTC) + timedelta(seconds=15),
        id="news_poll",
    )
    sched.start()
    _scheduler = sched
    log.info("news collector scheduler started (every %d min)", settings.news_poll_minutes)


def shutdown_news_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        log.info("news collector scheduler stopped")
