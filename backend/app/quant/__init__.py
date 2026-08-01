"""Quantitative research layer — price-path backtesting, risk analytics,
portfolio optimization and option pricing.

Why this package exists
-----------------------
``app/eval/scorecard.py`` already owns a research-grounded metric kernel
(Sharpe/Sortino/Calmar/PSR/DSR/purged-k-fold) but its own docstring names the
gap it cannot fill:

    "a *full* CPCV needs a price-path backtest, which a discrete trade ledger
    doesn't provide — we are honest about that rather than overclaiming."

This package supplies that missing price path. Nothing here re-implements a
metric that ``scorecard`` already has — :mod:`app.quant.backtest` produces the
per-bar return series and hands it straight to those functions.

House style (inherited from ``scorecard.py``)
---------------------------------------------
* Pure computation: no DB, no network, no LangChain. The ``@tool`` wrappers in
  ``app/tools/quant_tools.py`` own the I/O; this package owns the math.
* Every module cites its sources in the docstring and states its limits
  honestly rather than overclaiming.
* JSON-serializable output only — no numpy scalars escape (the SSE layer
  json-dumps tool I/O).
* Never raise into the graph: return ``None``/empty on degenerate input and let
  the tool layer turn that into an ``err()`` envelope.
"""
from __future__ import annotations
