"""Deterministic finance & math tools.

LLMs predict tokens — they do NOT calculate — so every number that matters is
computed HERE, in plain Python/numpy, and handed back through the standard
envelope in ``_calc_result`` (ok/err + raw_value + formatted_value + formula +
ui_type + data). The prose layer is told to quote these numbers verbatim.

Two families:
  • Time-value-of-money calculators (numpy-financial): future_value,
    goal_required_contribution.
  • Portfolio analytics over the user's real holdings (reusing get_quote /
    get_fund_quote and the FX router): compute_portfolio_summary,
    compute_concentration, compute_allocation_drift, plus the pure-series
    risk tools compute_return_metrics and correlation_matrix, and the
    cross-instrument compare_instruments.

Data freshness: quote lookups go through the existing tools, which share the
per-turn ``_cache`` — so when the portfolio + market desks both run, each
ticker is priced once.
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
import numpy_financial as npf
from langchain_core.tools import tool

import app.services.yfinance_service as yf_svc
from app.auth import get_display_currency
from app.tools._cache import cache_get, cache_set
from app.tools._calc_result import err, format_money, format_pct, ok
from app.tools.fund_tools import get_fund_history, get_fund_quote
from app.tools.market_tools import get_company_overview, get_quote
from app.tools.portfolio_tools import list_holdings

log = logging.getLogger("fincoach.tools.calc")

# Soft bound — a rate outside this is almost certainly a units mistake
# (e.g. 800 when the user meant 8). We reject it so the agent re-asks.
_MAX_ABS_RATE_PCT = 1000.0
_MAX_HOLDINGS_IN_DATA = 12  # keep SSE payloads small


# ─────────────────────────────────────────────────────────────────────────────
# FX + holding valuation helpers (module-level, not tools)
# ─────────────────────────────────────────────────────────────────────────────


def _fx_convert(amount: float, from_ccy: str, to_ccy: str) -> tuple[float, bool]:
    """Convert ``amount`` from one currency to another. Best-effort.

    Returns ``(converted, fx_applied)``. On any failure returns the original
    amount with ``fx_applied=False`` so a calc never crashes on an FX hiccup.
    Rates are memoised in the per-turn cache.
    """
    f = (from_ccy or "").upper()
    t = (to_ccy or "").upper()
    if not f or not t or f == t:
        return amount, True

    cache_key = f"fx:{f}:{t}"
    cached = cache_get(cache_key)
    if isinstance(cached, (int, float)):
        return amount * float(cached), True

    try:
        from app.routers.fx import _get_rates  # noqa: PLC0415

        rates, _ = _get_rates(f)
        rate = rates.get(t)
        if not rate:
            inv_rates, _ = _get_rates(t)
            inv = inv_rates.get(f)
            rate = (1.0 / inv) if inv else None
        if rate:
            cache_set(cache_key, rate)
            return amount * rate, True
    except Exception as exc:  # noqa: BLE001
        log.info("fx convert %s→%s failed: %s", f, t, exc)
    return amount, False


def _price_for(h: dict[str, Any]) -> tuple[float, str]:
    """Best-effort current price + native currency for one holding row.

    Falls back to the recorded cost basis if the live quote can't be fetched,
    so valuation degrades gracefully instead of dropping the position.
    """
    asset_class = h.get("asset_class")
    ticker = h.get("ticker")
    cost_basis = float(h.get("cost_basis") or 0.0)
    if asset_class == "cash":
        return 1.0, (h.get("currency") or "USD").upper()
    if asset_class == "fund":
        q = get_fund_quote.invoke({"code": ticker})
        if isinstance(q, dict) and q.get("price"):
            return float(q["price"]), (q.get("currency") or "TRY").upper()
        return cost_basis, (h.get("currency") or "TRY").upper()
    q = get_quote.invoke({"ticker": ticker})
    if isinstance(q, dict) and not q.get("error") and q.get("price"):
        return float(q["price"]), (q.get("currency") or h.get("currency") or "USD").upper()
    return cost_basis, (h.get("currency") or "USD").upper()


def _valued_holdings(display_ccy: str) -> tuple[list[dict[str, Any]], float, float, bool]:
    """Value every holding in ``display_ccy``. Returns (rows, total_value,
    total_cost, fx_complete)."""
    holdings = list_holdings.invoke({})
    rows: list[dict[str, Any]] = []
    total_value = 0.0
    total_cost = 0.0
    fx_complete = True
    for h in holdings:
        qty = float(h.get("quantity") or 0.0)
        price, native_ccy = _price_for(h)
        native_value = qty * price
        native_cost = qty * float(h.get("cost_basis") or 0.0)
        value, ok1 = _fx_convert(native_value, native_ccy, display_ccy)
        cost, ok2 = _fx_convert(native_cost, native_ccy, display_ccy)
        fx_complete = fx_complete and ok1 and ok2
        rows.append({
            "ticker": h.get("ticker"),
            "asset_class": h.get("asset_class") or "stock",
            "native_currency": native_ccy,
            "value": round(value, 2),
            "cost": round(cost, 2),
            "pnl": round(value - cost, 2),
        })
        total_value += value
        total_cost += cost
    return rows, total_value, total_cost, fx_complete


# ─────────────────────────────────────────────────────────────────────────────
# Time-value-of-money calculators
# ─────────────────────────────────────────────────────────────────────────────


@tool
def future_value(
    monthly_contribution: float,
    annual_rate_pct: float,
    years: float,
    initial_amount: float = 0.0,
    currency: str | None = None,
) -> dict[str, Any]:
    """Project the future value of regular monthly investing with compounding.

    Use for "if I invest X per month at Y% for Z years, what will I have?".
    Computed deterministically with the numpy-financial FV formula — quote the
    returned numbers verbatim; never recompute them yourself.

    Args:
        monthly_contribution: amount added each month (>= 0).
        annual_rate_pct: expected annual return as a PERCENT — pass 8 for 8%,
            not 0.08.
        years: investing horizon in years (> 0).
        initial_amount: lump sum invested today (>= 0).
        currency: ISO code for display; defaults to the user's display currency.

    Returns the standard calc envelope with raw_value = future value.
    """
    if years <= 0:
        return err("years must be > 0", years=years)
    if monthly_contribution < 0 or initial_amount < 0:
        return err(
            "contributions cannot be negative",
            monthly_contribution=monthly_contribution,
            initial_amount=initial_amount,
        )
    if abs(annual_rate_pct) > _MAX_ABS_RATE_PCT:
        return err(
            f"annual_rate_pct={annual_rate_pct} looks wrong — pass a percent like 8 for 8%",
            annual_rate_pct=annual_rate_pct,
        )

    ccy = (currency or get_display_currency() or "USD").upper()
    n = int(round(years * 12))
    r = (annual_rate_pct / 100.0) / 12.0
    if r == 0:  # avoid numpy-financial's divide-by-zero warning; FV is just the sum
        fv = initial_amount + monthly_contribution * n
    else:
        fv = float(npf.fv(r, n, -monthly_contribution, -initial_amount))
    contributed = initial_amount + monthly_contribution * n
    growth = fv - contributed

    return ok(
        raw_value=round(fv, 2),
        formatted_value=format_money(fv, ccy),
        formula=f"FV(rate={r:.6f}/mo, nper={n}, pmt={monthly_contribution}, pv={initial_amount})",
        explanation=(
            f"Investing {format_money(monthly_contribution, ccy)}/month "
            f"({format_money(initial_amount, ccy)} upfront) for {years:g} years at "
            f"{annual_rate_pct:g}% grows to {format_money(fv, ccy)} — "
            f"{format_money(contributed, ccy)} contributed, "
            f"{format_money(growth, ccy)} from compounding."
        ),
        ui_type="metric",
        data={
            "future_value": round(fv, 2),
            "total_contributed": round(contributed, 2),
            "growth": round(growth, 2),
            "currency": ccy,
            "years": years,
            "annual_rate_pct": annual_rate_pct,
        },
    )


@tool
def goal_required_contribution(
    target_amount: float,
    months: float,
    annual_rate_pct: float = 0.0,
    current_amount: float = 0.0,
    currency: str | None = None,
) -> dict[str, Any]:
    """Monthly amount needed to reach a savings goal by its target date.

    Use for "how much per month do I need to hit my goal?". Read the goal's
    target amount, saved amount, and months remaining from ``list_user_goals``
    (its ``months_left`` field) and pass them here. Computed with the
    numpy-financial PMT formula.

    Args:
        target_amount: goal target (> 0).
        months: months remaining until the target date (>= 1).
        annual_rate_pct: assumed annual return as a PERCENT (0 = plain saving).
        current_amount: already saved toward the goal (>= 0).
        currency: ISO code for display; defaults to the user's display currency.

    Returns the standard calc envelope with raw_value = required monthly amount.
    """
    if target_amount <= 0:
        return err("target_amount must be > 0", target_amount=target_amount)
    if months < 1:
        return err("months must be >= 1", months=months)
    if current_amount < 0:
        return err("current_amount cannot be negative", current_amount=current_amount)
    if abs(annual_rate_pct) > _MAX_ABS_RATE_PCT:
        return err(
            f"annual_rate_pct={annual_rate_pct} looks wrong — pass a percent like 8 for 8%",
            annual_rate_pct=annual_rate_pct,
        )

    ccy = (currency or get_display_currency() or "USD").upper()
    n = int(round(months))
    remaining = target_amount - current_amount
    if remaining <= 0:
        return ok(
            raw_value=0.0,
            formatted_value=format_money(0, ccy),
            formula="target already reached",
            explanation=(
                f"You already have {format_money(current_amount, ccy)} against a "
                f"{format_money(target_amount, ccy)} goal — no monthly contribution needed."
            ),
            ui_type="metric",
            data={"required_monthly": 0.0, "currency": ccy, "already_reached": True},
        )

    r = (annual_rate_pct / 100.0) / 12.0
    if r == 0:
        required = remaining / n
    else:
        required = abs(float(npf.pmt(r, n, -current_amount, target_amount)))

    return ok(
        raw_value=round(required, 2),
        formatted_value=format_money(required, ccy),
        formula=f"PMT(rate={r:.6f}/mo, nper={n}, pv={current_amount}, fv={target_amount})",
        explanation=(
            f"To reach {format_money(target_amount, ccy)} in {n} months at "
            f"{annual_rate_pct:g}% (starting from {format_money(current_amount, ccy)}), "
            f"save {format_money(required, ccy)} per month."
        ),
        ui_type="metric",
        data={
            "required_monthly": round(required, 2),
            "currency": ccy,
            "months": n,
            "target_amount": target_amount,
            "current_amount": current_amount,
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# Portfolio analytics (over the user's real holdings)
# ─────────────────────────────────────────────────────────────────────────────


@tool
def compute_portfolio_summary() -> dict[str, Any]:
    """Value the user's holdings and break them down by position and asset class.

    Fetches live prices, converts every position into the user's display
    currency, and returns total value, total cost, unrealized P&L, per-position
    weights, and asset-class allocation. Deterministic — quote these numbers
    directly. Call this before any "is my portfolio …" judgement.

    Returns the standard calc envelope; ``data`` holds positions + allocation.
    """
    ccy = get_display_currency() or "USD"
    rows, total_value, total_cost, fx_complete = _valued_holdings(ccy)
    if not rows:
        return ok(
            raw_value=0.0,
            formatted_value=format_money(0, ccy),
            explanation="No holdings on file yet.",
            ui_type="none",
            data={"positions": [], "allocation": [], "currency": ccy},
        )

    for r in rows:
        r["weight_pct"] = round((r["value"] / total_value * 100.0), 2) if total_value else 0.0
    rows.sort(key=lambda x: x["value"], reverse=True)

    by_class: dict[str, float] = {}
    for r in rows:
        by_class[r["asset_class"]] = by_class.get(r["asset_class"], 0.0) + r["value"]
    allocation = [
        {
            "label": cls,
            "value": round((val / total_value * 100.0), 2) if total_value else 0.0,
        }
        for cls, val in sorted(by_class.items(), key=lambda kv: kv[1], reverse=True)
    ]

    pnl = total_value - total_cost
    pnl_pct = (pnl / total_cost * 100.0) if total_cost else 0.0

    return ok(
        raw_value=round(total_value, 2),
        formatted_value=format_money(total_value, ccy),
        formula="Σ(quantity × price), converted to display currency",
        explanation=(
            f"Total value {format_money(total_value, ccy)} across {len(rows)} positions; "
            f"P&L {format_money(pnl, ccy)} ({format_pct(pnl_pct)})."
            + ("" if fx_complete else " (some FX rates unavailable — values approximate.)")
        ),
        ui_type="bars",
        data={
            "currency": ccy,
            "total_value": round(total_value, 2),
            "total_cost": round(total_cost, 2),
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "fx_complete": fx_complete,
            "positions": rows[:_MAX_HOLDINGS_IN_DATA],
            "allocation": allocation,
            # MiniBars-friendly series (asset-class weights)
            "bars": allocation,
        },
    )


@tool
def compute_concentration(top_n: int = 5) -> dict[str, Any]:
    """Measure how concentrated the portfolio is (HHI + largest positions).

    Returns the Herfindahl-Hirschman Index (sum of squared weight fractions,
    0–1: higher = more concentrated), the single largest position weight, and
    the top-N positions by weight. Use to answer "is my portfolio too
    concentrated?". Deterministic.

    Args:
        top_n: how many of the largest positions to list (1–20).
    """
    top_n = max(1, min(int(top_n), 20))
    ccy = get_display_currency() or "USD"
    rows, total_value, _, _ = _valued_holdings(ccy)
    if not rows or total_value <= 0:
        return ok(
            raw_value=0.0,
            explanation="No holdings on file yet.",
            ui_type="none",
            data={"positions": [], "currency": ccy},
        )

    for r in rows:
        r["weight_pct"] = round((r["value"] / total_value * 100.0), 2)
    rows.sort(key=lambda x: x["value"], reverse=True)

    hhi = float(sum((r["value"] / total_value) ** 2 for r in rows))
    top = rows[:top_n]
    largest = top[0]
    if hhi >= 0.25:
        level = "highly concentrated"
    elif hhi >= 0.15:
        level = "moderately concentrated"
    else:
        level = "well diversified"

    return ok(
        raw_value=round(hhi, 4),
        formatted_value=f"HHI {hhi:.2f} ({level})",
        formula="HHI = Σ(weightᵢ)²  over all positions",
        explanation=(
            f"HHI {hhi:.2f} → {level}. Largest position {largest['ticker']} at "
            f"{format_pct(largest['weight_pct'])} of the portfolio."
        ),
        ui_type="bars",
        data={
            "currency": ccy,
            "hhi": round(hhi, 4),
            "level": level,
            "largest_position": {"ticker": largest["ticker"], "weight_pct": largest["weight_pct"]},
            "positions": top,
            "bars": [{"label": r["ticker"], "value": r["weight_pct"]} for r in top],
        },
    )


@tool
def compute_allocation_drift(target_weights: dict[str, float]) -> dict[str, Any]:
    """Compare the current asset-class mix to a target allocation.

    Computes, per asset class, current weight − target weight (the drift). Use
    after a target allocation is set/known to answer "how far am I from my
    plan?". Deterministic.

    Args:
        target_weights: asset class → target weight in PERCENT, e.g.
            {"stock": 60, "bond": 30, "cash": 10}. Need not sum to exactly 100;
            it is normalised.

    Returns drift per class; ``data.bars`` is signed for a diverging bar chart.
    """
    if not target_weights:
        return err("target_weights is required", target_weights=target_weights)
    try:
        targets = {str(k).lower(): float(v) for k, v in target_weights.items()}
    except (TypeError, ValueError):
        return err("target_weights values must be numbers", target_weights=target_weights)
    total_target = sum(targets.values())
    if total_target <= 0:
        return err("target_weights must sum to a positive number", target_weights=target_weights)
    targets = {k: (v / total_target * 100.0) for k, v in targets.items()}  # normalise

    ccy = get_display_currency() or "USD"
    rows, total_value, _, _ = _valued_holdings(ccy)
    if not rows or total_value <= 0:
        return ok(
            raw_value=0.0,
            explanation="No holdings on file yet — nothing to compare against the target.",
            ui_type="none",
            data={"drift": [], "currency": ccy},
        )

    current: dict[str, float] = {}
    for r in rows:
        current[r["asset_class"]] = current.get(r["asset_class"], 0.0) + r["value"]
    current_pct = {k: (v / total_value * 100.0) for k, v in current.items()}

    classes = sorted(set(targets) | set(current_pct))
    drift_rows = []
    bars = []
    max_abs = 0.0
    for cls in classes:
        cur = round(current_pct.get(cls, 0.0), 2)
        tgt = round(targets.get(cls, 0.0), 2)
        d = round(cur - tgt, 2)
        max_abs = max(max_abs, abs(d))
        drift_rows.append({"asset_class": cls, "current_pct": cur, "target_pct": tgt, "drift_pct": d})
        bars.append({"label": cls, "value": d})

    worst = max(drift_rows, key=lambda x: abs(x["drift_pct"]))
    return ok(
        raw_value=round(max_abs, 2),
        formatted_value=f"max drift {format_pct(worst['drift_pct'])} ({worst['asset_class']})",
        formula="driftᵢ = current_weightᵢ − target_weightᵢ",
        explanation=(
            f"Largest drift: {worst['asset_class']} is {format_pct(worst['drift_pct'])} vs target "
            f"({format_pct(worst['current_pct'])} now, {worst['target_pct']:g}% target)."
        ),
        ui_type="diverging_bar",
        data={"currency": ccy, "drift": drift_rows, "bars": bars},
    )


# ─────────────────────────────────────────────────────────────────────────────
# Pure-series risk math (caller supplies the numbers)
# ─────────────────────────────────────────────────────────────────────────────


def _returns_from(prices: list[float] | None, returns: list[float] | None) -> np.ndarray | None:
    if returns:
        return np.asarray([float(x) for x in returns], dtype=float)
    if prices and len(prices) >= 2:
        p = np.asarray([float(x) for x in prices], dtype=float)
        if np.any(p[:-1] == 0):
            return None
        return p[1:] / p[:-1] - 1.0
    return None


def _metrics_from_returns(r: np.ndarray, ppy: int, rf: float) -> dict[str, float]:
    """Core risk/return math shared by compute_return_metrics and
    analyze_portfolio_risk. ``rf`` is the annual risk-free rate as a decimal."""
    ann_vol = float(np.std(r, ddof=1) * np.sqrt(ppy))
    ann_return = float(np.mean(r) * ppy)
    # Guard against float dust: a flat/degenerate series has vol ~1e-16, not 0,
    # which would otherwise explode Sharpe to a meaningless ~1e16.
    sharpe = ((ann_return - rf) / ann_vol) if ann_vol > 1e-12 else 0.0
    equity = np.cumprod(1.0 + r)
    peak = np.maximum.accumulate(equity)
    max_dd = float(np.min(equity / peak - 1.0))
    total_return = float(equity[-1] - 1.0)
    cagr = float(equity[-1] ** (ppy / r.size) - 1.0) if equity[-1] > 0 else float("nan")
    return {
        "ann_return": ann_return,
        "ann_vol": ann_vol,
        "sharpe": sharpe,
        "max_dd": max_dd,
        "total_return": total_return,
        "cagr": cagr,
    }


@tool
def compute_return_metrics(
    prices: list[float] | None = None,
    returns: list[float] | None = None,
    periods_per_year: int = 252,
    risk_free_rate_pct: float = 0.0,
    label: str | None = None,
) -> dict[str, Any]:
    """Risk/return metrics for a price or return series: annualised volatility,
    Sharpe ratio, CAGR, and max drawdown.

    Pass EITHER ``prices`` (e.g. NAV history from get_fund_history) OR
    ``returns`` (period returns as decimals). Deterministic.

    Args:
        prices: price/NAV series, oldest → newest.
        returns: period returns as decimals (0.01 = 1%), oldest → newest.
        periods_per_year: 252 daily, 12 monthly, 52 weekly.
        risk_free_rate_pct: annual risk-free rate as a percent (for Sharpe).
        label: optional name of the instrument for the explanation.
    """
    r = _returns_from(prices, returns)
    if r is None or r.size < 2:
        return err(
            "need at least 2 prices or 2 returns",
            prices_len=len(prices or []),
            returns_len=len(returns or []),
        )
    ppy = int(periods_per_year) if periods_per_year else 252
    m = _metrics_from_returns(r, ppy, risk_free_rate_pct / 100.0)

    who = f"{label}: " if label else ""
    return ok(
        raw_value=round(m["sharpe"], 3),
        formatted_value=f"Sharpe {m['sharpe']:.2f}",
        formula="vol=σ(r)·√P ; Sharpe=(μ·P − rf)/vol ; maxDD=min(equity/peak − 1)",
        explanation=(
            f"{who}annualised volatility {format_pct(m['ann_vol'] * 100)}, "
            f"Sharpe {m['sharpe']:.2f}, CAGR {format_pct(m['cagr'] * 100)}, "
            f"max drawdown {format_pct(m['max_dd'] * 100)}."
        ),
        ui_type="table",
        data={
            "rows": [
                {"metric": "Annualised return", "value": round(m["ann_return"] * 100, 2), "unit": "%"},
                {"metric": "Annualised volatility", "value": round(m["ann_vol"] * 100, 2), "unit": "%"},
                {"metric": "Sharpe ratio", "value": round(m["sharpe"], 3), "unit": ""},
                {"metric": "CAGR", "value": round(m["cagr"] * 100, 2), "unit": "%"},
                {"metric": "Max drawdown", "value": round(m["max_dd"] * 100, 2), "unit": "%"},
                {"metric": "Total return", "value": round(m["total_return"] * 100, 2), "unit": "%"},
            ],
            "periods_per_year": ppy,
            "n_periods": int(r.size),
        },
    )


@tool
def correlation_matrix(series: dict[str, list[float]]) -> dict[str, Any]:
    """Pairwise return correlations across instruments (diversification check).

    Each series is a price history; they are aligned to the shortest length,
    converted to returns, and correlated. Values near +1 move together (poor
    diversification); near 0 or negative diversify. Deterministic.

    Args:
        series: name → price series (oldest → newest). Provide 2+ series.
    """
    if not series or len(series) < 2:
        return err("provide at least 2 series", n_series=len(series or {}))
    names = list(series.keys())
    arrays = []
    min_len = min(len(v) for v in series.values())
    if min_len < 3:
        return err("each series needs at least 3 prices", min_len=min_len)
    for name in names:
        prices = np.asarray([float(x) for x in series[name][-min_len:]], dtype=float)
        if np.any(prices[:-1] == 0):
            return err(f"series '{name}' contains a zero price", series_with_zero=name)
        arrays.append(prices[1:] / prices[:-1] - 1.0)

    mat = np.corrcoef(np.vstack(arrays))
    matrix = {
        names[i]: {names[j]: round(float(mat[i, j]), 3) for j in range(len(names))}
        for i in range(len(names))
    }
    # Highest off-diagonal pair
    hi_pair, hi_val = ("", ""), -2.0
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            if mat[i, j] > hi_val:
                hi_val = float(mat[i, j])
                hi_pair = (names[i], names[j])

    return ok(
        raw_value=round(hi_val, 3),
        formatted_value=f"max corr {hi_val:.2f} ({hi_pair[0]}↔{hi_pair[1]})",
        formula="Pearson correlation of period returns",
        explanation=(
            f"Most-correlated pair: {hi_pair[0]} ↔ {hi_pair[1]} at {hi_val:.2f}. "
            "Pairs near +1 add little diversification."
        ),
        ui_type="table",
        data={"names": names, "matrix": matrix, "n_periods": int(min_len - 1)},
    )


# ─────────────────────────────────────────────────────────────────────────────
# Whole-portfolio risk (real holdings → vol / Sharpe / drawdown / correlation)
# ─────────────────────────────────────────────────────────────────────────────


def _yf_period(days: int) -> str:
    if days <= 35:
        return "1mo"
    if days <= 95:
        return "3mo"
    if days <= 190:
        return "6mo"
    if days <= 370:
        return "1y"
    return "2y"


def _holding_close_series(asset_class: str, ticker: str, days: int) -> dict[str, float] | None:
    """Best-effort {date: close} for one holding's native-currency price.
    Returns None if it can't be fetched (the holding is then excluded)."""
    try:
        if asset_class == "fund":
            rows = get_fund_history.invoke({"code": ticker, "days": days})
            return {r["date"]: float(r["price"]) for r in rows if r.get("price")}
        rows = yf_svc.history(ticker, period=_yf_period(days))
        return {r["date"]: float(r["close"]) for r in rows if r.get("close")}
    except Exception as exc:  # noqa: BLE001
        log.info("risk: history fetch failed for %s: %s", ticker, exc)
        return None


@tool
def analyze_portfolio_risk(
    period_days: int = 365, risk_free_rate_pct: float = 0.0
) -> dict[str, Any]:
    """Real risk metrics for the user's ACTUAL portfolio: annualised volatility,
    Sharpe ratio, max drawdown, and a holding-to-holding correlation matrix.

    Prices each holding's history, builds the value-weighted portfolio return
    series on the days every holding traded (rₚ = Σ wᵢ·rᵢ), and runs the metrics
    deterministically. Returns are in each asset's native currency — inter-asset
    FX drift is not modeled. Use for "how risky is my portfolio?", "what's my
    Sharpe?", "are my holdings diversified / too correlated?".

    Args:
        period_days: lookback window in days (30–1825; default 365).
        risk_free_rate_pct: annual risk-free rate as a percent (for Sharpe).
    """
    period_days = max(30, min(int(period_days), 1825))
    ccy = get_display_currency() or "USD"
    valued, _total, _cost, _fx = _valued_holdings(ccy)
    non_cash = [r for r in valued if r["asset_class"] != "cash" and r["value"] > 0]
    if not non_cash:
        return ok(
            raw_value=0.0,
            explanation="No priced non-cash holdings to analyze.",
            ui_type="none",
            data={"currency": ccy},
        )

    series: dict[str, dict[str, float]] = {}
    for r in non_cash:
        s = _holding_close_series(r["asset_class"], r["ticker"], period_days)
        if s and len(s) >= 5:
            series[r["ticker"]] = s
    if not series:
        return ok(
            raw_value=None,
            explanation="Couldn't fetch price history for any holding.",
            ui_type="none",
            data={"currency": ccy},
        )

    names = list(series.keys())
    inc_value = sum(r["value"] for r in non_cash if r["ticker"] in series)
    weights = {r["ticker"]: r["value"] / inc_value for r in non_cash if r["ticker"] in series}
    excluded = [r["ticker"] for r in non_cash if r["ticker"] not in series]
    rf = risk_free_rate_pct / 100.0

    common = sorted(set.intersection(*[set(s.keys()) for s in series.values()]))
    if len(common) < 6:
        # Too few overlapping trading days for portfolio-level stats — fall back
        # to each holding's own volatility from its full series.
        rows = []
        for tkr in names:
            dates = sorted(series[tkr])
            p = np.asarray([series[tkr][d] for d in dates], dtype=float)
            if p.size >= 3 and not np.any(p[:-1] == 0):
                mh = _metrics_from_returns(p[1:] / p[:-1] - 1.0, 252, rf)
                rows.append(
                    {"metric": f"{tkr} volatility", "value": round(mh["ann_vol"] * 100, 2), "unit": "%"}
                )
        return ok(
            raw_value=None,
            formatted_value="insufficient overlapping history",
            explanation=(
                "Holdings share too few overlapping trading days for "
                "portfolio-level stats; showing each holding's own volatility."
            ),
            ui_type="table",
            data={"currency": ccy, "rows": rows, "note": "low_overlap", "excluded": excluded},
        )

    # Returns matrix on the common dates: shape (n_assets, n_periods).
    arrays = []
    for tkr in names:
        p = np.asarray([series[tkr][d] for d in common], dtype=float)
        arrays.append(p[1:] / p[:-1] - 1.0)
    matrix = np.vstack(arrays)
    w = np.asarray([weights[tkr] for tkr in names], dtype=float)
    port_returns = w @ matrix  # value-weighted portfolio return per period
    m = _metrics_from_returns(port_returns, 252, rf)

    rows = [
        {"metric": "Annualised volatility", "value": round(m["ann_vol"] * 100, 2), "unit": "%"},
        {"metric": "Sharpe ratio", "value": round(m["sharpe"], 2), "unit": ""},
        {"metric": "Max drawdown", "value": round(m["max_dd"] * 100, 2), "unit": "%"},
        {"metric": "Annualised return", "value": round(m["ann_return"] * 100, 2), "unit": "%"},
    ]
    for i, tkr in enumerate(names):
        vol_i = float(np.std(matrix[i], ddof=1) * np.sqrt(252) * 100)
        rows.append({"metric": f"{tkr} volatility", "value": round(vol_i, 2), "unit": "%"})

    correlation: dict[str, dict[str, float]] | None = None
    hi_pair: tuple[str, str] | None = None
    hi_val = -2.0
    if len(names) >= 2:
        cm = np.corrcoef(matrix)
        correlation = {
            names[i]: {names[j]: round(float(cm[i, j]), 3) for j in range(len(names))}
            for i in range(len(names))
        }
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                if cm[i, j] > hi_val:
                    hi_val = float(cm[i, j])
                    hi_pair = (names[i], names[j])

    explanation = (
        f"Portfolio annualised volatility {format_pct(m['ann_vol'] * 100)}, "
        f"Sharpe {m['sharpe']:.2f}, max drawdown {format_pct(m['max_dd'] * 100)} "
        f"over {len(common)} common trading days."
    )
    if hi_pair:
        explanation += f" Most-correlated pair: {hi_pair[0]}↔{hi_pair[1]} ({hi_val:.2f})."
    if excluded:
        explanation += f" Excluded (no history): {', '.join(excluded)}."

    return ok(
        raw_value=round(m["sharpe"], 3),
        formatted_value=f"Vol {m['ann_vol'] * 100:.1f}% · Sharpe {m['sharpe']:.2f}",
        formula="rₚ=Σ wᵢ·rᵢ ; vol=σ(rₚ)·√252 ; Sharpe=(μ·252 − rf)/vol",
        explanation=explanation + " (Native-currency returns; inter-asset FX drift not modeled.)",
        ui_type="table",
        data={
            "currency": ccy,
            "rows": rows,
            "weights": {k: round(v * 100, 1) for k, v in weights.items()},
            "correlation": correlation,
            "n_periods": len(common) - 1,
            "excluded": excluded,
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# Cross-instrument comparison
# ─────────────────────────────────────────────────────────────────────────────


def _looks_like_fund_code(ticker: str) -> bool:
    t = (ticker or "").strip().upper()
    return t.isalpha() and 2 <= len(t) <= 6 and "." not in t


@tool
def compare_instruments(tickers: list[str]) -> dict[str, Any]:
    """Side-by-side metrics for 2–8 tickers and/or TEFAS fund codes.

    For each symbol: live price + 1-day change, plus (equities) P/E, dividend
    yield, beta, or (TEFAS funds) trailing returns and risk score. Best-effort
    per symbol — a failed lookup is reported in the row, not fatal.

    Args:
        tickers: e.g. ["AAPL", "MSFT"] or ["AFA", "IIH"] or a mix.
    """
    if not tickers or len(tickers) < 2:
        return err("provide 2–8 tickers", tickers=tickers)
    tickers = [str(t).strip().upper() for t in tickers if str(t).strip()][:8]

    rows: list[dict[str, Any]] = []
    for t in tickers:
        row: dict[str, Any] = {"ticker": t}
        q = get_quote.invoke({"ticker": t})
        if (not isinstance(q, dict) or q.get("error") or not q.get("price")) and _looks_like_fund_code(t):
            fq = get_fund_quote.invoke({"code": t})
            if isinstance(fq, dict) and fq.get("price"):
                row.update({
                    "kind": "fund",
                    "price": fq.get("price"),
                    "change_pct": fq.get("change_pct"),
                    "currency": fq.get("currency", "TRY"),
                    "return_1y_pct": fq.get("return_1y"),
                    "return_ytd_pct": fq.get("return_ytd"),
                    "risk": fq.get("risk"),
                })
                rows.append(row)
                continue
        if isinstance(q, dict) and q.get("price") and not q.get("error"):
            row.update({
                "kind": "equity",
                "price": q.get("price"),
                "change_pct": q.get("change_pct"),
                "currency": q.get("currency", "USD"),
            })
            ov = get_company_overview.invoke({"ticker": t})
            if isinstance(ov, dict) and not ov.get("error"):
                row.update({
                    "pe_ratio": ov.get("pe_ratio"),
                    "dividend_yield": ov.get("dividend_yield"),
                    "beta": ov.get("beta"),
                })
        else:
            row["error"] = q.get("error", "no data") if isinstance(q, dict) else "no data"
        rows.append(row)

    priced = [r for r in rows if r.get("price")]
    explanation = (
        f"Compared {len(rows)} symbols; {len(priced)} priced successfully."
        if priced else "Could not price any of the requested symbols."
    )
    return ok(
        raw_value=len(priced),
        formatted_value=f"{len(priced)}/{len(rows)} priced",
        formula=None,
        explanation=explanation,
        ui_type="table",
        data={"rows": rows},
    )
