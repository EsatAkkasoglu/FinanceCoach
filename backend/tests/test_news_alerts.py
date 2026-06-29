"""Tests for proactive news-alert matching + the alerts/watchlist endpoints.

The matcher (``match_article``) is pure and covered without a DB. The endpoints
and end-to-end alert generation run against the temp-SQLite ``client`` fixture.
"""
from __future__ import annotations

from sqlalchemy import select

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


def test_fan_out_alerts_each_watchlist_user(client):
    """The background poll has no request context, so generate_alerts_for_all
    must raise alerts for *every* user with a watchlist, not just user 1."""
    from app.db.models import NewsArticle, User, Watchlist
    from app.db.session import SessionLocal
    from app.services.news_alerts import generate_alerts_for_all

    # User 1 (the registered client) watches AAPL; create a second user
    # watching THYAO.IS, plus a third user with no watchlist at all.
    client.post("/news/watchlist", json={"kind": "symbol", "value": "AAPL"})

    with SessionLocal() as db:
        u2 = User(username="second", password_hash=None, name="Second")
        u3 = User(username="third", password_hash=None, name="Third")
        db.add_all([u2, u3])
        db.flush()
        db.add(Watchlist(user_id=u2.id, kind="symbol", value="THYAO.IS"))
        # Dull category + weak sentiment so each article matches ONLY via its
        # watchlist symbol (no importance-threshold alert muddying the count).
        art_aapl = NewsArticle(
            canonical_url="https://x.com/a", url="https://x.com/a",
            title="AAPL ships new chips", source="X", tickers="AAPL",
            category="market", sentiment="neutral", sentiment_score=0.2,
            content_hash="fa", enriched=1,
        )
        art_thy = NewsArticle(
            canonical_url="https://x.com/t", url="https://x.com/t",
            title="THYAO.IS adds new route", source="X", tickers="THYAO.IS",
            category="market", sentiment="neutral", sentiment_score=0.3,
            content_hash="ft", enriched=1,
        )
        db.add_all([art_aapl, art_thy])
        db.commit()
        u2_id, u3_id = u2.id, u3.id
        a_id, t_id = art_aapl.id, art_thy.id

        created = generate_alerts_for_all(db, [art_aapl, art_thy])
        # Re-running is idempotent across all users.
        again = generate_alerts_for_all(db, [art_aapl, art_thy])

        from app.db.models import NewsAlert

        rows = db.execute(select(NewsAlert)).scalars().all()
        by_user = {(r.user_id, r.article_id) for r in rows}

    # User 1 alerted on AAPL; user 2 on THYAO.IS; user 3 (no watchlist) on neither.
    assert created == 2
    assert again == 0
    assert (1, a_id) in by_user
    assert (u2_id, t_id) in by_user
    assert not any(uid == u3_id for uid, _ in by_user)
