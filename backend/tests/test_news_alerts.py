"""Tests for proactive news-alert matching + the alerts/watchlist endpoints.

The matcher (``match_article``) is pure and covered without a DB. The endpoints
and end-to-end alert generation run against the temp-SQLite ``client`` fixture.
"""
from __future__ import annotations

from app.services.news_alerts import (
    PRIORITY_IMPORTANCE,
    PRIORITY_WATCHLIST,
    match_article,
)

# ── Pure matcher ─────────────────────────────────────────────────────────────

_DEFAULTS = dict(
    important_categories={"regulation", "ma", "earnings"},
    score_threshold=0.6,
)


def _match(**over):
    base = dict(
        tickers=None, title="", snippet=None, category=None, sentiment_score=None,
        symbols=set(), keywords=[], **_DEFAULTS,
    )
    base.update(over)
    return match_article(**base)


def test_symbol_matches_extracted_tickers():
    hit = _match(tickers="AAPL,MSFT", title="Apple ships chips", symbols={"AAPL"})
    assert hit == ("watchlist:AAPL", PRIORITY_WATCHLIST)


def test_symbol_matches_whole_word_in_title_when_untagged():
    hit = _match(tickers=None, title="THYAO.IS soars on traffic", symbols={"THYAO.IS"})
    assert hit == ("watchlist:THYAO.IS", PRIORITY_WATCHLIST)


def test_symbol_does_not_match_substring():
    # 'BT' must not match 'BTC'.
    assert _match(title="BTC up 5%", symbols={"BT"}) is None


def test_keyword_matches_title_or_snippet():
    hit = _match(title="Fed signals", snippet="interest rate hike likely", keywords=["interest rate"])
    assert hit == ("watchlist:interest rate", PRIORITY_WATCHLIST)


def test_important_category_fires_without_watchlist():
    hit = _match(title="Regulator fines bank", category="regulation")
    assert hit == ("category:regulation", PRIORITY_IMPORTANCE)


def test_strong_sentiment_fires():
    hit = _match(title="Market crashes", category="market", sentiment_score=-0.85)
    assert hit == ("sentiment", PRIORITY_IMPORTANCE)


def test_weak_sentiment_and_dull_category_no_match():
    assert _match(title="Mild update", category="market", sentiment_score=0.2) is None


def test_watchlist_outranks_importance():
    # Article is both a watchlist symbol AND an important category — watchlist wins.
    hit = _match(
        tickers="AAPL", title="AAPL earnings beat", symbols={"AAPL"}, category="earnings",
    )
    assert hit == ("watchlist:AAPL", PRIORITY_WATCHLIST)


# ── Endpoints + end-to-end generation ────────────────────────────────────────


def test_watchlist_crud_and_normalization(client):
    # symbols upper-cased, dedup on (kind, value)
    r = client.post("/news/watchlist", json={"kind": "symbol", "value": "aapl"})
    assert r.status_code == 201, r.text
    assert r.json()["value"] == "AAPL"

    dup = client.post("/news/watchlist", json={"kind": "symbol", "value": "AAPL"})
    assert dup.json()["value"] == "AAPL"

    listing = client.get("/news/watchlist").json()["items"]
    assert [w["value"] for w in listing] == ["AAPL"]

    item_id = listing[0]["id"]
    assert client.delete(f"/news/watchlist/{item_id}").status_code == 200
    assert client.get("/news/watchlist").json()["items"] == []


def test_invalid_watchlist_kind_rejected(client):
    r = client.post("/news/watchlist", json={"kind": "bogus", "value": "x"})
    assert r.status_code == 422


def test_end_to_end_alert_generation(client):
    from app.db.models import NewsArticle
    from app.db.session import SessionLocal
    from app.services.news_alerts import generate_alerts

    client.post("/news/watchlist", json={"kind": "symbol", "value": "AAPL"})

    with SessionLocal() as db:
        art = NewsArticle(
            canonical_url="https://x.com/aapl", url="https://x.com/aapl",
            title="AAPL beats earnings", source="X", tickers="AAPL",
            category="earnings", sentiment="positive", sentiment_score=0.8,
            content_hash="h1", enriched=1,
        )
        db.add(art)
        db.commit()
        db.refresh(art)
        created = generate_alerts(db, [art], user_id=1)
        # Re-running is idempotent (unique on user+article).
        again = generate_alerts(db, [art], user_id=1)
    assert created == 1
    assert again == 0

    feed = client.get("/news/alerts").json()
    assert feed["unread_count"] == 1
    assert feed["items"][0]["reason"] == "watchlist:AAPL"
    assert feed["items"][0]["article"]["title"] == "AAPL beats earnings"

    alert_id = feed["items"][0]["id"]
    marked = client.post("/news/alerts/read", json={"ids": [alert_id]}).json()
    assert marked["updated"] == 1
    assert client.get("/news/alerts").json()["unread_count"] == 0
