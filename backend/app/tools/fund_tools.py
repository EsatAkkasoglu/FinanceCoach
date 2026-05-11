"""Turkish mutual fund (TEFAS) tools.

TEFAS = Türkiye Elektronik Fon Alım Satım Platformu — single venue for all
Turkish mutual + pension funds. NAVs publish once per business day.

We use the ``tefas-crawler`` package (https://pypi.org/project/tefas-crawler/)
which scrapes tefas.gov.tr. The API exposes one method, ``Crawler.fetch``,
that pulls a date range for one fund (when ``name`` is set) or a slice of
all funds for a category (``kind="YAT"`` for mutual, ``"EMK"`` for pension).

Caching strategy:
- Per-fund recent history: 12-hour TTL (NAVs only update once a day)
- Universe snapshot (for search): 24-hour TTL
- Both keyed by today's date so cache rolls over automatically.
"""
from __future__ import annotations

import logging
import unicodedata
from datetime import date as date_cls
from datetime import timedelta
from functools import lru_cache
from typing import Any, Literal

from langchain_core.tools import tool

log = logging.getLogger("fincoach.tools.funds")


# Turkish letters that don't fold the same way as English under .lower():
# - "I" → "i" by default Python, but in Turkish "I" is the uppercase of "ı"
# - "İ" → "i̇" with a combining dot, breaks substring match
# This map collapses both Turkish and English forms to a single ASCII form
# so search is forgiving regardless of the user's keyboard layout.
_TR_FOLD = str.maketrans({
    "İ": "i", "I": "i", "ı": "i", "i": "i",
    "Ş": "s", "ş": "s",
    "Ç": "c", "ç": "c",
    "Ğ": "g", "ğ": "g",
    "Ü": "u", "ü": "u",
    "Ö": "o", "ö": "o",
})


def _fold_tr(s: str) -> str:
    """Lowercase + Turkish-aware ASCII fold for search matching."""
    if not s:
        return ""
    return unicodedata.normalize("NFKC", s).translate(_TR_FOLD).lower()


def _crawler():
    """Lazy import — tefas-crawler hits the network on init in some versions.

    Note on ``fund_limit``: the new tefas.gov.tr API no longer supports a
    bulk-by-date request. ``fetch(kind=...)`` without ``name`` fans out one
    HTTP request per fund. Each costs ~50-200ms, so a limit of 1500 → 60s+
    first call. We cap at 300 for the universe snapshot — covers the most-
    liquid retail funds (Ak/Garanti/İş/QNB/Ziraat majors) while keeping
    first-search latency under ~10s.
    """
    from tefas import Crawler
    c = Crawler()
    c.fund_limit = 300
    return c


def prewarm_universe() -> None:
    """Background task: kick the universe cache so the first ``search_fund``
    call in production doesn't block. Safe to call from a thread; lru_cache
    is thread-safe."""
    try:
        _universe_cached("YAT", today_iso=date_cls.today().isoformat())
    except Exception as exc:
        log.warning("TEFAS pre-warm failed: %s", exc)


@lru_cache(maxsize=256)
def _history_cached(code: str, days: int, today_iso: str) -> tuple[dict, ...]:
    """Cached per (code, days, today). Returns immutable tuple of records."""
    end = date_cls.fromisoformat(today_iso)
    start = end - timedelta(days=days)
    try:
        df = _crawler().fetch(start=start.isoformat(), end=end.isoformat(), name=code)
    except Exception as exc:
        log.warning("TEFAS fetch failed for %s: %s", code, exc)
        return ()
    if df is None or df.empty:
        return ()
    return tuple(
        {
            "date": r.get("date").isoformat() if hasattr(r.get("date"), "isoformat") else r.get("date"),
            "code": r.get("code"),
            "title": r.get("title"),
            "price": float(r.get("price") or 0),
            "category_rank": r.get("category_rank"),
            "category_total": r.get("category_total"),
        }
        for r in df.to_dict("records")
    )


@lru_cache(maxsize=4)
def _universe_cached(kind: str, today_iso: str) -> tuple[dict, ...]:
    """Snapshot of latest NAVs across the whole fund universe of one kind.

    Used for search and ranked lists. ``kind`` = "YAT" (mutual) | "EMK" (pension).
    Returns one row per fund (the most recent NAV in the window)."""
    end = date_cls.fromisoformat(today_iso)
    start = end - timedelta(days=5)  # ensure we hit a business day
    try:
        df = _crawler().fetch(start=start.isoformat(), end=end.isoformat(), kind=kind)
    except Exception as exc:
        log.warning("TEFAS universe fetch failed (%s): %s", kind, exc)
        return ()
    if df is None or df.empty:
        return ()
    df = df.sort_values("date").drop_duplicates(subset=["code"], keep="last")
    return tuple(
        {
            "code": r.get("code"),
            "title": r.get("title"),
            "price": float(r.get("price") or 0),
            "category_rank": r.get("category_rank"),
            "category_total": r.get("category_total"),
            "date": r.get("date").isoformat() if hasattr(r.get("date"), "isoformat") else r.get("date"),
        }
        for r in df.to_dict("records")
    )


@tool
def get_fund_quote(code: str) -> dict[str, Any]:
    """Get the latest NAV (net asset value, in TL) and 1-day change for a
    Turkish TEFAS fund.

    Args:
        code: 3-letter TEFAS fund code, e.g. 'AFA', 'IIH', 'TI2', 'NVT'.
              If the user gives a fund NAME instead, call search_fund first.

    Returns:
        {code, title, price, change_pct, currency: "TRY", as_of, source}
    """
    code = code.upper().strip()
    rows = _history_cached(code, days=10, today_iso=date_cls.today().isoformat())
    if not rows:
        return {"code": code, "error": "fund not found or TEFAS unavailable"}
    latest = rows[-1]
    prev = rows[-2] if len(rows) > 1 else latest
    price = latest["price"]
    prev_price = prev["price"] or price
    change_pct = ((price - prev_price) / prev_price * 100.0) if prev_price else 0.0
    return {
        "code": code,
        "title": latest["title"],
        "price": round(price, 6),
        "change_pct": round(change_pct, 2),
        "currency": "TRY",
        "category_rank": latest.get("category_rank"),
        "category_total": latest.get("category_total"),
        "as_of": latest["date"],
        "source": "TEFAS",
    }


@tool
def get_fund_history(code: str, days: int = 30) -> list[dict[str, Any]]:
    """Recent NAV history for a TEFAS fund. Useful for return calculations.

    Args:
        code: 3-letter fund code
        days: lookback window (capped at 365)
    """
    code = code.upper().strip()
    days = max(2, min(365, int(days)))
    rows = _history_cached(code, days=days, today_iso=date_cls.today().isoformat())
    return [{"date": r["date"], "price": r["price"]} for r in rows]


@tool
def search_fund(query: str, limit: int = 10, kind: Literal["mutual", "pension"] = "mutual") -> list[dict[str, Any]]:
    """Search Turkish funds by partial name or code.

    Args:
        query: free text — e.g. 'altın', 'hisse', 'iş bankası', 'amerika',
               'kısa vadeli', or a partial code.
        limit: max results (default 10)
        kind:  'mutual' (most retail funds) or 'pension' (BES funds)

    Returns:
        List of {code, title, price, date} sorted by relevance.
    """
    kind_param = "EMK" if kind == "pension" else "YAT"
    universe = _universe_cached(kind_param, today_iso=date_cls.today().isoformat())
    if not universe:
        return []
    q = _fold_tr(query.strip())
    if not q:
        return []
    hits: list[tuple[int, dict]] = []
    for f in universe:
        code_l = _fold_tr(f["code"] or "")
        title_l = _fold_tr(f["title"] or "")
        score = 0
        if code_l == q:
            score = 100
        elif q in code_l:
            score = 60
        if q in title_l:
            score += 40
        if score > 0:
            hits.append((score, f))
    hits.sort(key=lambda x: -x[0])
    return [h[1] for h in hits[:limit]]


@tool
def list_top_funds(
    metric: Literal["best_rank", "worst_rank"] = "best_rank",
    limit: int = 10,
) -> list[dict[str, Any]]:
    """List the top or bottom mutual funds by category rank.

    Rank is *within the fund's own category* (e.g. equity funds), so it
    compares like-for-like rather than absolute return. Lower rank = better
    performance vs peers.

    Args:
        metric: 'best_rank' (top performers) or 'worst_rank' (laggards)
        limit:  max results
    """
    universe = _universe_cached("YAT", today_iso=date_cls.today().isoformat())
    if not universe:
        return []
    rows = [f for f in universe if f.get("category_rank") is not None]
    reverse = metric == "worst_rank"
    rows.sort(key=lambda x: x["category_rank"], reverse=reverse)
    return rows[:limit]
