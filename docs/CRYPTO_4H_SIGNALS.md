# 4-Hour Crypto Signal System

A short-horizon trading layer that fuses **news**, **technical** and **derivatives**
analysis into one risk-defined call per asset, sized to a **4-hour** window. Built
to be scored on realised profit over that window.

> Hackathon prototype — these are **demo signals, not financial advice.**

---

## 1. Asset selection — why BTC, ETH, SOL

The basket (`FINCOACH_CRYPTO_BASKET`, default `BTC,ETH,SOL`) is chosen so **both**
analysis modes are always available and high-quality:

| Requirement | Why it matters for a 4-hour trade | BTC / ETH / SOL |
| --- | --- | --- |
| **Continuous news flow** | Sentiment only moves price intraday if there *is* coverage | CoinDesk + Cointelegraph + Yahoo/Google cover all three constantly |
| **Deep perpetual markets** | Funding rate & open interest are the highest-signal intraday derivatives reads | All three have liquid Binance perps (funding + OI on CoinDesk) |
| **Top liquidity** | Tight spreads → ATR targets/stops are tradeable, not theoretical | Top-5 by volume |
| **Clean reference price** | Index pricing avoids single-exchange noise | CoinDesk CADLI index |

A thin-coverage or no-derivatives coin would leave one of the three signal
components blind — these three never do.

## 2. Signal methodology

`backend/app/tools/crypto_short_term.py` → `compute_short_term_signal()` is a pure,
unit-tested function. It blends three independent reads into a score ∈ [-1, 1]:

```
score = 0.50 · technical  +  0.30 · derivatives  +  0.20 · sentiment
```

**Technical (50%)** — intraday (hourly) candles via the new
`coindesk.coin_history_hourly()`:
- EMA-9 vs EMA-21 separation (trend)
- RSI-14 (momentum, capped at the extremes)
- MACD histogram
- 4-bar price momentum

**Derivatives (30%)** — the existing CoinDesk perpetual layer:
- **Funding rate** as a *contrarian* read: a moderately positive rate confirms
  demand, but an extreme one (over-leveraged longs paying a steep premium) flips
  bearish — crowded leverage precedes liquidation cascades. Mirrored for crowded
  shorts.
- **Open-interest trend** confirms whichever way technicals lean (rising OI +
  uptrend = real capital entering).

**Sentiment (20%)** — mean sentiment of recent crypto headlines (`search_news`,
`asset_class=crypto`), positive/neutral/negative → +1/0/−1.

**Direction**: `score > 0.15` → long, `< -0.15` → short, else neutral.
**Confidence**: magnitude of the score, boosted when the three components agree.

## 3. Targets — ATR-based, never guessed

Volatility scales with √time (standard diffusion approximation), so the 4-hour ATR
≈ hourly ATR × √4. From the live price:

```
long:   target = entry + 1.5 · ATR_4h     stop = entry − 1.0 · ATR_4h
short:  target = entry − 1.5 · ATR_4h     stop = entry + 1.0 · ATR_4h
```

→ a fixed **1.5 : 1 reward : risk**. Neutral signals produce no target (stand aside).

## 4. Demo account

On demo login (`/auth/demo`, idempotent) the basket is seeded best-effort:
- a ~$1.5k notional **holding** per coin, entered at the live signal price, and
- an **ACTIVE 4-hour `TradeTarget`** (entry / target / stop / expiry).

Seeding is fully wrapped — a data-source outage never blocks login.

## 5. API

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/crypto/basket` | curated symbols + display names |
| `GET` | `/crypto/short-term/{ticker}` | compute a 4h plan (no persist) |
| `POST` | `/crypto/targets/scan` | score the basket, (re)create a target each |
| `GET` | `/crypto/targets` | list targets, re-priced live; resolves hit/stopped/expired |

All endpoints degrade to a 200 with an `error` field — never a raw 500 (which
would bypass CORS/security middleware and surface as a misleading CORS error).

The chat coach also gets `get_crypto_short_term_plan(symbol)` (bound to the
market_data agent) for "should I buy now and sell in a few hours?" questions.

## 6. Frontend

`src/components/insights/ShortTermSignals.tsx` renders a **"4-Hour Signals"** desk
on the Markets tab: one card per coin with direction, entry/target/stop, live
price, progress-to-target bar, live P&L, a countdown to expiry, and an expandable
thesis. A **Re-scan** button re-runs the basket. Reduced-motion aware; no WebGL on
the critical path. EN + TR.

## 7. Demo script (for the jury)

1. Open the app → **"Demo"** login. The demo account now holds BTC/ETH/SOL with
   live 4-hour targets.
2. Go to **Markets** → the **4-Hour Signals** desk shows each coin's directional
   call, entry/target/stop and confidence.
3. Press **Re-scan** to recompute against the latest candles + funding + news.
4. Watch the **progress bar** and **P&L** update toward each target over the
   4-hour window; cards flip to *Target hit* / *Stopped* / *Expired* as they
   resolve.
5. Ask the chat coach *"BTC için önümüzdeki 4 saatte pozisyon almalı mıyım?"* —
   it calls the same engine and explains the plan.

## 8. Verification

`ruff` clean · `pytest` 141 not-network + 21 new unit tests (indicators, signal
fusion, target lifecycle) · `tsc` clean · `vitest` 17 · `vite build` OK.

## 9. Config / keys

No new keys required — `COINDESK_API_KEY` (already configured in prod) powers
prices, hourly candles and derivatives; news uses the existing RSS/NewsAPI path.
Tune the basket with `FINCOACH_CRYPTO_BASKET`.
