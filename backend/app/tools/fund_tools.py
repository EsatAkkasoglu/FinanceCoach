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
import re
import unicodedata
from datetime import date as date_cls
from datetime import timedelta
from functools import lru_cache
from typing import Any, Literal

from langchain_core.tools import tool

# Pattern for "looks like a TEFAS fund code": 2-6 ASCII letters/digits,
# all-caps once normalized. Used to trigger a direct-code fallback when
# the universe cache doesn't list a fund (TEFAS's returns-based endpoint
# excludes ~500 funds, e.g. money-market ones without long return history).
_FUND_CODE_RE = re.compile(r"^[A-Z0-9]{2,6}$")

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
    """Lazy import — tefas-crawler used only for per-fund history fetches."""
    from tefas import Crawler
    c = Crawler()
    return c


_TEFAS_BULK_URL = "https://www.tefas.gov.tr/api/funds/fonGetiriBazliBilgiGetir"


def _fetch_universe_tefas_bulk(kind: str) -> tuple[dict, ...]:
    """Single-request snapshot of the entire TEFAS fund universe.

    This is the JSON API powering tefas.gov.tr's own "Getiri Bazlı Bilgi"
    page — one POST returns every fund (~1000 mutual, ~400 pension) with
    name, category, risk score, and 1m/3m/6m/YTD/1y/3y/5y returns.

    Note: bulk endpoint does NOT include current NAV price. Price is fetched
    on demand by ``get_fund_quote`` when the user opens a fund detail.
    """
    import requests  # noqa: PLC0415

    payload = {
        "dil": "TR",
        "fonTipi": kind,  # YAT | EMK
        "kurucuKodu": None,
        "sfonTurKod": None,
        "fonTurAciklama": None,
        "islem": 1,
        "fonTurKod": None,
        "fonGrubu": None,
        "donemGetiri1a": "1",
        "donemGetiri3a": "1",
        "donemGetiri6a": "1",
        "donemGetiri1y": "1",
        "donemGetiriyb": "1",
        "donemGetiri3y": "1",
        "donemGetiri5y": "1",
        "basTarih": None,
        "bitTarih": None,
        "calismaTipi": 2,
        "getiriOrani": "1",
    }
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (compatible; FinCoach/1.0)",
        "Referer": "https://www.tefas.gov.tr/",
    }
    r = requests.post(_TEFAS_BULK_URL, json=payload, headers=headers, timeout=20)
    r.raise_for_status()
    rows = (r.json() or {}).get("resultList") or []
    today = date_cls.today().isoformat()
    out: list[dict] = []
    for r_ in rows:
        code = (r_.get("fonKodu") or "").strip()
        if not code:
            continue
        out.append(
            {
                "code": code,
                "title": (r_.get("fonUnvan") or "").strip(),
                "category": (r_.get("fonTurAciklama") or "").strip(),
                "risk": r_.get("riskDegeri"),
                "return_1m": r_.get("getiri1a"),
                "return_3m": r_.get("getiri3a"),
                "return_6m": r_.get("getiri6a"),
                "return_1y": r_.get("getiri1y"),
                "return_ytd": r_.get("getiriyb"),
                "price": None,
                "category_rank": None,
                "category_total": None,
                "date": today,
            }
        )
    return tuple(out)


def _fetch_universe_isyatirim() -> tuple[dict, ...]:
    """Fallback: İş Yatırım fund list endpoint.

    Currently behind 401 from server-side IPs; kept as a stub so the fallback
    chain remains in place if the policy changes.
    """
    import requests  # noqa: PLC0415

    url = (
        "https://www.isyatirim.com.tr/_layouts/15/IsYatirim.Website/"
        "Common/Data.aspx/FonTumIstatistik"
    )
    params = {"strFundType": "YAT", "strPeriod": "1A", "intIslemSayisi": "0"}
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; FinCoach/1.0)",
        "Referer": "https://www.isyatirim.com.tr/tr-tr/analiz/fon/Sayfalar/default.aspx",
        "Accept": "application/json, text/plain, */*",
    }
    r = requests.get(url, params=params, headers=headers, timeout=15)
    r.raise_for_status()
    rows = (r.json() or {}).get("data") or []
    today = date_cls.today().isoformat()
    out: list[dict] = []
    for r_ in rows:
        code = (r_.get("FONKODU") or "").strip()
        if not code:
            continue
        try:
            price = float(r_.get("SONFIYAT") or 0) or None
        except (TypeError, ValueError):
            price = None
        out.append(
            {
                "code": code,
                "title": (r_.get("FONUNVAN") or "").strip(),
                "category": None,
                "risk": None,
                "return_1m": None,
                "return_3m": None,
                "return_6m": None,
                "return_1y": None,
                "return_ytd": None,
                "price": price,
                "category_rank": None,
                "category_total": None,
                "date": today,
            }
        )
    return tuple(out)


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
    """Full snapshot of the TEFAS fund universe of one kind.

    ``kind`` = "YAT" (mutual) | "EMK" (pension).

    Strategy (each tier covers the whole ~1500-fund universe in one request;
    we fall through on failure):
        1. TEFAS BindComparisonFundReturns — primary, has category rank.
        2. İş Yatırım FonTumIstatistik    — fallback, no rank but full list.
        3. tefas-crawler bulk fetch       — last resort, slow per-fund fan-out.
    """
    try:
        rows = _fetch_universe_tefas_bulk(kind)
        if rows:
            log.info("TEFAS bulk universe ok (%s): %d funds", kind, len(rows))
            return rows
    except Exception as exc:  # noqa: BLE001
        log.warning("TEFAS bulk universe failed (%s): %s", kind, exc)

    if kind == "YAT":
        try:
            rows = _fetch_universe_isyatirim()
            if rows:
                log.info("İş Yatırım universe fallback ok: %d funds", len(rows))
                return rows
        except Exception as exc:  # noqa: BLE001
            log.warning("İş Yatırım universe fallback failed: %s", exc)

    end = date_cls.fromisoformat(today_iso)
    start = end - timedelta(days=5)
    try:
        df = _crawler().fetch(start=start.isoformat(), end=end.isoformat(), kind=kind)
    except Exception as exc:  # noqa: BLE001
        log.warning("tefas-crawler universe fallback failed (%s): %s", kind, exc)
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
    raw = (query or "").strip()
    q = _fold_tr(raw)
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
    if hits:
        return [h[1] for h in hits[:limit]]

    # Fallback: universe is missing ~500 funds (TEFAS's returns-based listing
    # filters out money-market and some others). If the query looks like a
    # fund code, hit tefas-crawler directly — it can resolve any live code.
    code_candidate = raw.upper()
    if _FUND_CODE_RE.match(code_candidate):
        direct = _lookup_by_code(code_candidate)
        if direct is not None:
            return [direct]
    return []


def _lookup_by_code(code: str) -> dict | None:
    """Per-code TEFAS lookup via tefas-crawler. Used to bridge gaps in the
    bulk universe cache. Returns the same shape as universe rows so the
    caller doesn't care which path produced the result."""
    today = date_cls.today()
    start = today - timedelta(days=7)
    try:
        df = _crawler().fetch(start=start.isoformat(), end=today.isoformat(), name=code)
    except Exception as exc:  # noqa: BLE001
        log.warning("TEFAS direct-code lookup failed for %s: %s", code, exc)
        return None
    if df is None or df.empty:
        return None
    row = df.sort_values("date").iloc[-1].to_dict()
    return {
        "code": row.get("code") or code,
        "title": row.get("title") or "",
        "price": float(row.get("price") or 0) or None,
        "category": None,
        "risk": None,
        "return_1m": None,
        "return_3m": None,
        "return_6m": None,
        "return_1y": None,
        "return_ytd": None,
        "category_rank": None,
        "category_total": None,
        "date": row["date"].isoformat() if hasattr(row.get("date"), "isoformat") else row.get("date"),
    }


@tool
def list_top_funds(
    metric: Literal["best_rank", "worst_rank"] = "best_rank",
    limit: int = 10,
) -> list[dict[str, Any]]:
    """List the top or bottom mutual funds by 6-month return.

    The TEFAS bulk endpoint no longer exposes within-category rank, so we
    sort by 6-month return as a proxy. ``best_rank`` = highest returns,
    ``worst_rank`` = laggards.

    Args:
        metric: 'best_rank' (top performers) or 'worst_rank' (laggards)
        limit:  max results
    """
    universe = _universe_cached("YAT", today_iso=date_cls.today().isoformat())
    if not universe:
        return []
    rows = [f for f in universe if f.get("return_6m") is not None]
    descending = metric == "best_rank"
    rows.sort(key=lambda x: x["return_6m"], reverse=descending)
    return rows[:limit]
