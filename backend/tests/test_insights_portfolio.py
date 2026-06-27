"""Regressions for two prod bugs:

* Portfolio showed fund cost basis as the live price (``_quote_or_none`` checked
  a non-existent ``ok`` key on ``get_fund_quote``'s result).
* ``/insights/*`` raised unhandled 500s (which bypass CORS/security middleware
  and surface as a misleading CORS error) instead of degrading gracefully.
"""
from __future__ import annotations

import app.tools.fund_tools as ft
from app.main import _quote_or_none
from app.routers.insights import _safe_tool


class _FakeTool:
    """Stand-in for a langchain @tool exposing ``.invoke``."""

    def __init__(self, ret):
        self._ret = ret

    def invoke(self, _payload):
        return self._ret


def test_quote_or_none_fund_uses_price_without_ok_key(monkeypatch):
    # get_fund_quote's real success shape has NO "ok" key.
    monkeypatch.setattr(
        ft, "get_fund_quote", _FakeTool({"code": "ICZ", "price": 8.786, "currency": "TRY"})
    )
    assert _quote_or_none("ICZ", "fund") == {"price": 8.786, "currency": "TRY"}


def test_quote_or_none_fund_none_on_error(monkeypatch):
    monkeypatch.setattr(ft, "get_fund_quote", _FakeTool({"code": "ZZZ", "error": "not found"}))
    assert _quote_or_none("ZZZ", "fund") is None


def test_safe_tool_degrades_exception_to_error_dict():
    def boom():
        raise RuntimeError("yfinance exploded")

    out = _safe_tool("aapl", "technicals", boom)
    assert out["error"] == "yfinance exploded"
    assert out["ticker"] == "AAPL"


def test_safe_tool_passes_through_success():
    payload = {"ticker": "AAPL", "rsi": {"value": 55}}
    assert _safe_tool("AAPL", "8dim", lambda: payload) == payload


def test_safe_tool_no_ticker_omits_ticker_field():
    out = _safe_tool("", "trends", lambda: (_ for _ in ()).throw(ValueError("nope")))
    assert out == {"error": "nope"}
