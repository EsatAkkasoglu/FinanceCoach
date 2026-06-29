"""Regressions for two prod bugs:

* Portfolio showed fund cost basis as the live price (``_quote_or_none`` checked
  a non-existent ``ok`` key on ``get_fund_quote``'s result).
* ``/insights/*`` raised unhandled 500s (which bypass CORS/security middleware
  and surface as a misleading CORS error) instead of degrading gracefully.
"""
from __future__ import annotations

import app.tools.fund_tools as ft
from app.main import _quote_or_none
from app.routers.insights import _json_safe, _safe_tool


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


def test_json_safe_replaces_non_finite_floats():
    out = _json_safe({"rsi": float("nan"), "sma": float("inf"), "price": 8.78, "ok": True})
    assert out == {"rsi": None, "sma": None, "price": 8.78, "ok": True}


def test_json_safe_recurses_into_nested_structures():
    out = _json_safe({"a": [float("nan"), {"b": float("-inf")}], "c": (1.0, 2.5)})
    assert out == {"a": [None, {"b": None}], "c": [1.0, 2.5]}


def test_safe_tool_sanitizes_nan_so_serialization_cannot_500():
    # This is the real prod failure: tool succeeds but returns NaN, which
    # Starlette's allow_nan=False render would reject. _safe_tool must hand
    # back a JSON-safe dict instead.
    out = _safe_tool("AAPL", "technicals", lambda: {"ticker": "AAPL", "rsi": float("nan")})
    assert out == {"ticker": "AAPL", "rsi": None}
    import json
    json.dumps(out, allow_nan=False)  # must not raise
