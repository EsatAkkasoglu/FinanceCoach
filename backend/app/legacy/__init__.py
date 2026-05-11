"""Verbatim copies of the stock-analysis skill scripts + a thin clean API.

The originals (analyze_stock.py, dividends.py, hot_scanner.py, rumor_scanner.py)
were written as standalone CLIs. This package re-exposes them as importable
functions returning JSON-serializable dicts, so LangChain @tool wrappers in
app/tools/ can call them without going through argparse / sys.exit.

Public API:
    analyze_ticker(ticker, fast=False)         → dict
    analyze_dividends(ticker)                  → dict | None
    scan_hot_trends(no_social=True)            → dict
    scan_rumors()                              → dict

The cache directory used by the legacy scripts resolves to
``backend/app/cache/`` because their ``Path(__file__).parent.parent / "cache"``
expression evaluates relative to ``backend/app/legacy/<script>.py``.
"""
from __future__ import annotations

from app.legacy.runner import (
    analyze_ticker,
    analyze_dividends,
    scan_hot_trends,
    scan_rumors,
)

__all__ = [
    "analyze_ticker",
    "analyze_dividends",
    "scan_hot_trends",
    "scan_rumors",
]
