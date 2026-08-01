"""Option-pricing tests — pure, no network.

Anchored on the textbook case (S=100, K=100, T=1, r=5%, σ=20% → call ≈ 10.4506)
and on identities that must hold exactly: put-call parity, the jump-diffusion
collapsing to Black-Scholes at zero intensity, and implied vol round-tripping.
"""
from __future__ import annotations

import math

import pytest

from app.quant.options import (
    bs_greeks,
    bs_price,
    implied_vol,
    merton_jump_price,
    smile,
)

BASE = {"S": 100.0, "K": 100.0, "T": 1.0, "r": 0.05, "sigma": 0.20}


# ── price ────────────────────────────────────────────────────────────────────


def test_atm_call_matches_the_textbook_value():
    assert bs_price(**BASE, kind="call") == pytest.approx(10.450583572185565, abs=1e-9)


def test_atm_put_matches_the_textbook_value():
    assert bs_price(**BASE, kind="put") == pytest.approx(5.573526022256971, abs=1e-9)


def test_put_call_parity_holds():
    c = bs_price(**BASE, kind="call")
    p = bs_price(**BASE, kind="put")
    S, K, T, r = BASE["S"], BASE["K"], BASE["T"], BASE["r"]
    assert c - p == pytest.approx(S - K * math.exp(-r * T), abs=1e-9)


def test_parity_holds_with_a_dividend_yield():
    kw = {**BASE, "q": 0.03}
    c = bs_price(**kw, kind="call")
    p = bs_price(**kw, kind="put")
    S, K, T, r, q = BASE["S"], BASE["K"], BASE["T"], BASE["r"], 0.03
    assert c - p == pytest.approx(S * math.exp(-q * T) - K * math.exp(-r * T), abs=1e-9)


def test_price_is_monotone_in_volatility():
    prices = [bs_price(**{**BASE, "sigma": s}, kind="call") for s in (0.1, 0.2, 0.4, 0.8)]
    assert prices == sorted(prices)


def test_deep_itm_call_approaches_its_intrinsic_floor():
    price = bs_price(S=200.0, K=100.0, T=1.0, r=0.05, sigma=0.01, kind="call")
    assert price == pytest.approx(200.0 - 100.0 * math.exp(-0.05), abs=1e-6)


def test_degenerate_inputs_return_none_rather_than_raising():
    assert bs_price(S=0.0, K=100.0, T=1.0, r=0.05, sigma=0.2) is None
    assert bs_price(**{**BASE, "T": 0.0}) is None
    assert bs_price(**{**BASE, "sigma": -0.2}) is None
    assert bs_price(**BASE, kind="straddle") is None


# ── greeks ───────────────────────────────────────────────────────────────────


def test_call_and_put_delta_differ_by_the_discounted_unit():
    gc = bs_greeks(**BASE, kind="call")
    gp = bs_greeks(**BASE, kind="put")
    assert gc["delta"] - gp["delta"] == pytest.approx(1.0, abs=1e-9)


def test_atm_call_delta_is_slightly_above_a_half():
    g = bs_greeks(**BASE, kind="call")
    assert 0.5 < g["delta"] < 0.75


def test_gamma_and_vega_are_shared_by_calls_and_puts():
    gc = bs_greeks(**BASE, kind="call")
    gp = bs_greeks(**BASE, kind="put")
    assert gc["gamma"] == pytest.approx(gp["gamma"], abs=1e-12)
    assert gc["vega"] == pytest.approx(gp["vega"], abs=1e-12)


def test_vega_matches_a_numerical_bump_of_one_vol_point():
    """vega is quoted per 1 vol point, so it must track a 1% finite difference."""
    base = bs_price(**BASE, kind="call")
    bumped = bs_price(**{**BASE, "sigma": 0.21}, kind="call")
    assert bs_greeks(**BASE, kind="call")["vega"] == pytest.approx(bumped - base, abs=1e-3)


def test_theta_is_negative_for_a_long_atm_option():
    assert bs_greeks(**BASE, kind="call")["theta"] < 0


def test_greeks_reject_bad_input():
    assert bs_greeks(**{**BASE, "T": -1.0}) is None
    assert bs_greeks(**BASE, kind="nope") is None


# ── implied volatility ───────────────────────────────────────────────────────


@pytest.mark.parametrize("sigma", [0.05, 0.15, 0.30, 0.75, 1.50])
@pytest.mark.parametrize("kind", ["call", "put"])
def test_implied_vol_round_trips(sigma: float, kind: str):
    price = bs_price(**{**BASE, "sigma": sigma}, kind=kind)
    assert implied_vol(price, BASE["S"], BASE["K"], BASE["T"], BASE["r"], kind=kind) == (
        pytest.approx(sigma, abs=1e-6)
    )


def test_implied_vol_round_trips_away_from_the_money():
    for strike in (70.0, 130.0):
        price = bs_price(S=100.0, K=strike, T=0.5, r=0.03, sigma=0.35, kind="call")
        iv = implied_vol(price, 100.0, strike, 0.5, 0.03, kind="call")
        assert iv == pytest.approx(0.35, abs=1e-6)


def test_implied_vol_returns_none_when_the_quote_is_arbitrageable():
    # Above the S·e^(-qT) ceiling — no volatility can produce this price.
    assert implied_vol(150.0, 100.0, 100.0, 1.0, 0.05, kind="call") is None
    # Below the intrinsic floor.
    assert implied_vol(0.0001, 200.0, 100.0, 1.0, 0.05, kind="call") is None


def test_implied_vol_rejects_nonsense_arguments():
    assert implied_vol(10.0, 100.0, 100.0, 0.0, 0.05) is None
    assert implied_vol(10.0, 100.0, 100.0, 1.0, 0.05, kind="binary") is None


# ── jump diffusion ───────────────────────────────────────────────────────────


def test_zero_intensity_collapses_to_black_scholes():
    jump = merton_jump_price(**BASE, lam=0.0, kind="call")
    assert jump == pytest.approx(bs_price(**BASE, kind="call"), abs=1e-12)


def test_jumps_add_value_to_an_atm_option():
    """Extra (jump) variance can only make an option worth more, never less."""
    plain = bs_price(**BASE, kind="call")
    jumpy = merton_jump_price(**BASE, lam=1.0, mu_j=-0.05, sigma_j=0.25, kind="call")
    assert jumpy > plain


def test_jump_diffusion_produces_a_smirk_not_a_flat_line():
    """Negative mean jumps must lift OTM put IV above ATM — the crash smirk."""
    strikes = [80.0, 100.0, 120.0]
    prices = [
        merton_jump_price(S=100.0, K=k, T=0.5, r=0.02, sigma=0.20,
                          lam=1.0, mu_j=-0.10, sigma_j=0.25, kind="put")
        for k in strikes
    ]
    ivs = [row["iv_pct"] for row in smile(strikes, prices, 100.0, 0.5, 0.02, kind="put")]
    assert all(iv is not None for iv in ivs)
    assert ivs[0] > ivs[1]  # 80-strike put richer than ATM


def test_jump_price_rejects_bad_parameters():
    assert merton_jump_price(**BASE, lam=-1.0) is None
    assert merton_jump_price(**{**BASE, "sigma": 0.0}, lam=0.5) is None


# ── smile ────────────────────────────────────────────────────────────────────


def test_smile_is_flat_for_black_scholes_prices():
    strikes = [80.0, 90.0, 100.0, 110.0, 120.0]
    prices = [bs_price(S=100.0, K=k, T=1.0, r=0.05, sigma=0.25, kind="call") for k in strikes]
    rows = smile(strikes, prices, 100.0, 1.0, 0.05, kind="call")
    assert len(rows) == 5
    for row in rows:
        assert row["iv_pct"] == pytest.approx(25.0, abs=1e-3)
    assert rows[2]["moneyness"] == pytest.approx(1.0)


def test_smile_keeps_unsolvable_strikes_visible():
    rows = smile([100.0], [999.0], 100.0, 1.0, 0.05, kind="call")
    assert rows[0]["iv_pct"] is None   # reported as a gap, not silently dropped
