"""Smoke tests for the legacy stock-analysis bridge.

These hit the live yfinance API (no mocks). Network-dependent — skip when
running offline. Goal: confirm the legacy scripts copied cleanly and the
runner exposes the data we expect.
"""
from __future__ import annotations

import pytest


def test_legacy_imports():
    """Legacy package + runner are importable, nothing blew up at import time."""
    from app.legacy import analyze_ticker, analyze_dividends, scan_hot_trends, scan_rumors

    for fn in (analyze_ticker, analyze_dividends, scan_hot_trends, scan_rumors):
        assert callable(fn)


@pytest.mark.network
def test_get_quote_aapl():
    """Tool: get_quote returns a price for AAPL."""
    from app.tools.market_tools import get_quote

    result = get_quote.invoke({"ticker": "AAPL"})
    assert result["ticker"] == "AAPL"
    assert "error" not in result
    assert result["price"] > 0
    assert result["source"] == "yfinance"


@pytest.mark.network
@pytest.mark.slow
def test_analyze_ticker_8dim_fast():
    """Runner: 8-dim analysis returns a signal dict in fast mode."""
    from app.legacy import analyze_ticker

    result = analyze_ticker("MSFT", fast=True)
    assert result["ticker"] == "MSFT"
    if "error" in result:
        pytest.skip(f"upstream failure: {result['error']}")
    # synthesize_signal builds a Signal dataclass; expect score-like fields
    assert "recommendation" in result or "signal" in result or "verdict" in result


@pytest.mark.network
def test_dividend_metrics_jnj():
    """Tool: dividend metrics work for a known dividend payer."""
    from app.tools.market_tools import get_dividend_metrics

    result = get_dividend_metrics.invoke({"ticker": "JNJ"})
    assert result is not None
    if "error" in result:
        pytest.skip(f"upstream failure: {result['error']}")
    assert result["ticker"] == "JNJ"
