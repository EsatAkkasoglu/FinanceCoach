"""Clean, importable API around the stock-analysis legacy scripts.

The original ``analyze_stock.main()`` orchestrates a dozen helper functions
and writes to argparse / sys.exit, so we can't call it. Instead we mirror the
orchestration in ``analyze_ticker()`` and return a serializable dict.

The other three (dividends, hot_scanner, rumor_scanner) already exposed
clean entry points — we just adapt their signatures.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict
from typing import Any

from app.legacy import analyze_stock as _stk
from app.legacy import dividends as _div

log = logging.getLogger("fincoach.legacy")


# ---------------------------------------------------------------------------
# 8-dim ticker analysis
# ---------------------------------------------------------------------------

def analyze_ticker(ticker: str, fast: bool = False) -> dict[str, Any]:
    """Run the full 8-dimension analysis on a US stock or crypto ticker.

    Mirrors ``analyze_stock.main()`` for a single ticker, returning the
    Signal dataclass as a dict.

    Args:
        ticker: e.g. "NVDA", "BTC-USD"
        fast: skip insider trading + breaking-news checks (~3-5s instead of 10s)

    Returns:
        Signal dict with score, recommendation, and per-dimension breakdown.
        On failure returns ``{"ticker": ..., "error": "..."}``.
    """
    ticker = ticker.upper()
    skip_insider = fast

    try:
        # Optional global breaking-news scan (skipped in fast mode)
        breaking_news = None if fast else _stk.check_breaking_news(verbose=False)

        data = _stk.fetch_stock_data(ticker, verbose=False)
        if data is None:
            return {"ticker": ticker, "error": "invalid ticker or data unavailable"}

        company_name = data.info.get("longName") or data.info.get("shortName") or ticker
        is_crypto = data.asset_type == "crypto"

        if is_crypto:
            earnings = analysts = historical = earnings_timing = sector = None
            crypto_fund = _stk.analyze_crypto_fundamentals(data, verbose=False)
            fundamentals = (
                _stk.Fundamentals(
                    score=crypto_fund.score,
                    key_metrics={
                        "market_cap": crypto_fund.market_cap,
                        "market_cap_rank": crypto_fund.market_cap_rank,
                        "category": crypto_fund.category,
                        "btc_correlation": crypto_fund.btc_correlation,
                    },
                    explanation=crypto_fund.explanation,
                )
                if crypto_fund
                else None
            )
            sentiment = None
            geopolitical_risk_warning = None
            geopolitical_risk_penalty = 0.0
        else:
            earnings = _stk.analyze_earnings_surprise(data)
            fundamentals = _stk.analyze_fundamentals(data)
            analysts = _stk.analyze_analyst_sentiment(data)
            historical = _stk.analyze_historical_patterns(data)
            earnings_timing = _stk.analyze_earnings_timing(data)
            sector = _stk.analyze_sector_performance(data, verbose=False)
            sentiment = asyncio.run(
                _stk.analyze_sentiment(data, verbose=False, skip_insider=skip_insider)
            )
            geopolitical_risk_warning, geopolitical_risk_penalty = (
                _stk.check_sector_geopolitical_risk(
                    ticker=ticker,
                    sector=data.info.get("sector"),
                    breaking_news=breaking_news,
                    verbose=False,
                )
            )

        market_context = _stk.analyze_market_context(verbose=False)
        momentum = _stk.analyze_momentum(data)

        signal = _stk.synthesize_signal(
            ticker=ticker,
            company_name=company_name,
            earnings=earnings,
            fundamentals=fundamentals,
            analysts=analysts,
            historical=historical,
            market_context=market_context,
            sector=sector,
            earnings_timing=earnings_timing,
            momentum=momentum,
            sentiment=sentiment,
            breaking_news=breaking_news,
            geopolitical_risk_warning=geopolitical_risk_warning,
            geopolitical_risk_penalty=geopolitical_risk_penalty,
        )
        return asdict(signal)
    except Exception as exc:  # broad: legacy code can raise anywhere
        log.exception("analyze_ticker(%s) failed", ticker)
        return {"ticker": ticker, "error": str(exc)}


# ---------------------------------------------------------------------------
# Dividend analysis
# ---------------------------------------------------------------------------

def analyze_dividends(ticker: str) -> dict[str, Any] | None:
    """Yield, payout, growth, safety score, income rating for a ticker."""
    try:
        result = _div.analyze_dividends(ticker.upper(), verbose=False)
        if result is None:
            return None
        return asdict(result)
    except Exception as exc:
        log.exception("analyze_dividends(%s) failed", ticker)
        return {"ticker": ticker.upper(), "error": str(exc)}


# ---------------------------------------------------------------------------
# Hot scanner (trending tickers)
# ---------------------------------------------------------------------------

def scan_hot_trends(no_social: bool = True) -> dict[str, Any]:
    """Find currently trending tickers across CoinGecko, Yahoo Finance, Google News.

    Returns the same summary dict the CLI saves to ``cache/hot_scan_latest.json``.
    """
    from app.legacy.hot_scanner import HotScanner

    try:
        scanner = HotScanner(include_social=not no_social)
        scanner.scan_all()
        return scanner.get_hot_summary()
    except Exception as exc:
        log.exception("scan_hot_trends failed")
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Rumor scanner (early signals)
# ---------------------------------------------------------------------------

def scan_rumors() -> dict[str, Any]:
    """M&A rumors, insider activity, analyst upgrades, Twitter whispers.

    Mirrors the orchestration in ``rumor_scanner.main()`` without printing.
    """
    from app.legacy import rumor_scanner as _rs

    try:
        all_rumors: list[dict] = []
        all_buzz: list[dict] = []

        all_rumors.extend(_rs.search_twitter_rumors())
        all_buzz.extend(_rs.search_twitter_buzz())
        all_rumors.extend(_rs.search_news_rumors())

        for item in all_rumors:
            item["score"] = _rs.calculate_rumor_score(item)
            item["symbols"] = _rs.extract_symbols_from_text(
                (item.get("text") or "") + (item.get("title") or "")
            )
        all_rumors.sort(key=lambda x: x["score"], reverse=True)

        symbol_counts: dict[str, int] = {}
        for item in all_buzz:
            for sym in item.get("symbols", []) or []:
                symbol_counts[sym] = symbol_counts.get(sym, 0) + 1

        return {
            "rumors": all_rumors[:20],
            "buzz": all_buzz[:30],
            "symbol_counts": symbol_counts,
        }
    except Exception as exc:
        log.exception("scan_rumors failed")
        return {"error": str(exc)}
