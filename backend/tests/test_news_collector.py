"""Unit tests for the news collector's pure functions.

No network / DB — covers URL canonicalization, title hashing, language
heuristic, feedparser-result normalization, and intra-batch dedup. The live
fetch/poll path is exercised separately under the ``network`` marker.
"""
from __future__ import annotations

import threading
import time
from types import SimpleNamespace

from app.services import news_collector as nc


def test_canonical_url_strips_tracking_and_fragment():
    a = nc.canonical_url("https://Example.com/Story/?utm_source=x&id=5&fbclid=abc#frag")
    b = nc.canonical_url("https://example.com/Story?id=5")
    assert a == b
    assert "utm_source" not in a and "fbclid" not in a and "#" not in a


def test_canonical_url_trailing_slash_and_case():
    assert nc.canonical_url("HTTPS://News.com/a/") == nc.canonical_url("https://news.com/a")


def test_title_hash_normalizes_punctuation_and_case():
    assert nc.title_hash("Fed cuts rates!") == nc.title_hash("fed   cuts rates")
    assert nc.title_hash("") == ""
    assert nc.title_hash("BTC up 5%") != nc.title_hash("ETH up 5%")


def test_detect_lang():
    assert nc.detect_lang("Borsa İstanbul yükseldi") == "tr"
    assert nc.detect_lang("Markets rally", "https://tr.investing.com/rss/news.rss") == "tr"
    assert nc.detect_lang("Apple beats earnings", "https://www.coindesk.com/rss") == "en"


def _fake_feed():
    return SimpleNamespace(
        feed={"title": "CoinDesk"},
        entries=[
            {
                "title": "Bitcoin hits new high",
                "link": "https://coindesk.com/a?utm_campaign=z",
                "summary": "BTC rallied today " * 50,
                "published_parsed": time.struct_time((2026, 6, 1, 12, 0, 0, 0, 0, 0)),
            },
            {"title": "", "link": "https://coindesk.com/empty"},  # dropped (no title)
            {"title": "No link here", "link": ""},                  # dropped (no link)
        ],
    )


def test_parse_entries_maps_and_filters():
    items = nc.parse_entries(_fake_feed(), feed_url="https://coindesk.com/rss")
    assert len(items) == 1
    it = items[0]
    assert it["title"] == "Bitcoin hits new high"
    assert it["source"] == "CoinDesk"
    assert "utm_campaign" not in it["canonical_url"]
    assert it["content_hash"] == nc.title_hash("Bitcoin hits new high")
    assert len(it["snippet"]) <= 240
    assert it["published_at"].year == 2026


def test_parse_entries_source_falls_back_to_host():
    feed = SimpleNamespace(feed={}, entries=[{"title": "x", "link": "https://www.ntv.com.tr/a"}])
    items = nc.parse_entries(feed, feed_url="https://www.ntv.com.tr/ekonomi.rss")
    assert items[0]["source"] == "ntv.com.tr"


def test_dedupe_within_by_url_and_hash():
    items = [
        {"canonical_url": "https://x.com/1", "content_hash": "h1"},
        {"canonical_url": "https://x.com/1", "content_hash": "h2"},  # dup URL
        {"canonical_url": "https://x.com/2", "content_hash": "h1"},  # dup hash
        {"canonical_url": "https://x.com/3", "content_hash": "h3"},  # kept
    ]
    out = nc.dedupe_within(items)
    assert [o["canonical_url"] for o in out] == ["https://x.com/1", "https://x.com/3"]


def test_enrich_batch_noop_when_disabled(monkeypatch):
    monkeypatch.setattr(nc.settings, "news_enrich_enabled", False)
    arts = [{"title": "Apple beats earnings", "enriched": 0}]
    nc.enrich_batch(arts)
    assert arts[0].get("enriched") == 0
    assert "sentiment" not in arts[0]


def test_enrich_batch_empty_is_safe():
    nc.enrich_batch([])  # must not raise


def test_enrich_bisects_on_failure(monkeypatch):
    """One unparseable headline must not sink the whole batch — the chunk is
    bisected until the offending single item is isolated, the rest enriched."""
    monkeypatch.setattr(nc.settings, "news_enrich_enabled", True)
    monkeypatch.setattr(nc.settings, "gemini_api_key", "test-key")
    monkeypatch.setattr(nc.settings, "news_enrich_batch_size", 50)

    class _FakeLLM:
        def invoke(self, prompt: str):
            # Headlines are listed after the "Headlines:" marker, one per line.
            body = prompt.rsplit("Headlines:", 1)[-1]
            count = len([ln for ln in body.splitlines() if ln.strip()])
            if count > 1:
                raise ValueError("simulated structured-output parse failure")
            return nc.BatchEnrichment(
                items=[nc.HeadlineEnrichment(
                    index=0, sentiment="positive", score=0.5, category="crypto",
                    summary="ok", tickers=["BTC"],
                )]
            )

    monkeypatch.setattr(nc, "_get_enrich_llm", lambda: _FakeLLM())
    arts = [{"title": f"Headline {i}", "enriched": 0} for i in range(3)]
    nc.enrich_batch(arts)
    assert all(a.get("enriched") == 1 for a in arts)
    assert all(a.get("sentiment") == "positive" for a in arts)


def test_poll_lock_skips_overlapping_run():
    """A second poll while one is in flight returns immediately as skipped."""
    assert nc._poll_lock.acquire(blocking=False)
    try:
        summary = nc.poll_all_feeds()
        assert summary.get("skipped") is True
        assert summary["new"] == 0
    finally:
        nc._poll_lock.release()


def test_fetch_one_timeout_marks_feed_errored(monkeypatch):
    def _boom(*_a, **_k):
        raise nc.requests.exceptions.Timeout("slow feed")

    monkeypatch.setattr(nc.requests, "get", _boom)
    url, parsed = nc._fetch_one("https://x.com/rss", None, None)
    assert url == "https://x.com/rss"
    assert parsed["bozo"] == 1
    assert parsed["status"] is None
    assert not parsed.get("entries")


def test_fetch_one_304_short_circuits(monkeypatch):
    resp = SimpleNamespace(status_code=304, content=b"", headers={})
    monkeypatch.setattr(nc.requests, "get", lambda *a, **k: resp)
    _url, parsed = nc._fetch_one("https://x.com/rss", "etag-1", None)
    assert parsed["status"] == 304
    assert not parsed.get("entries")


def test_poll_if_stale_launches_background_poll_when_stale(monkeypatch):
    """A stale feed kicks a background poll (the Cloud Run idle-wake refresh)."""
    monkeypatch.setattr(nc.settings, "news_collector_enabled", True)
    monkeypatch.setattr(nc, "_minutes_since_last_poll", lambda: 999.0)
    fired = threading.Event()
    monkeypatch.setattr(nc, "poll_all_feeds", lambda: fired.set())
    assert nc.poll_if_stale() is True
    assert fired.wait(timeout=2.0)


def test_poll_if_stale_skips_when_fresh(monkeypatch):
    monkeypatch.setattr(nc.settings, "news_collector_enabled", True)
    monkeypatch.setattr(nc, "_minutes_since_last_poll", lambda: 0.0)

    def _boom():
        raise AssertionError("poll must not run when fresh")

    monkeypatch.setattr(nc, "poll_all_feeds", _boom)
    assert nc.poll_if_stale() is False


def test_poll_if_stale_skips_when_disabled(monkeypatch):
    monkeypatch.setattr(nc.settings, "news_collector_enabled", False)
    assert nc.poll_if_stale() is False


# ── HTTP layer (real ASGI stack via the TestClient fixture; no network/key) ───


def test_news_feed_endpoint_empty(client):
    r = client.get("/news/feed")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["items"] == []
    assert body["count"] == 0


def test_news_feed_accepts_filters(client):
    r = client.get("/news/feed", params={"limit": 5, "category": "crypto", "q": "bitcoin"})
    assert r.status_code == 200, r.text


def test_news_feed_limit_is_bounded(client):
    # limit > 100 is rejected by the Query(le=100) validator.
    assert client.get("/news/feed", params={"limit": 999}).status_code == 422


def test_news_poll_requires_admin(client):
    # The demo user isn't in FINCOACH_ADMIN_USERNAMES → 403, and poll never runs.
    assert client.post("/news/poll").status_code == 403


# ── DB-first term derivation (no fund resolution for free-text all-caps) ──────


def test_db_search_terms_freetext_not_treated_as_fund():
    from app.tools import news_tools as nt

    # Short all-caps non-fund queries must stay free-text (no TEFAS resolution).
    assert nt._db_search_terms("FED", "") == ["FED"]
    assert nt._db_search_terms("MACRO", "") == ["MACRO"]
    # Turkish BIST ticker still strips its suffix.
    assert nt._db_search_terms("ASELS.IS", "") == ["ASELS"]
