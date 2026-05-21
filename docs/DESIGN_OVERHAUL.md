# FinCoach — Conceptual Design Overhaul

_Dashboard · Budget · Explore (Discover) — structural grid + data-density analysis_

This is a conceptual analysis, not an implementation. It audits the three primary
panels as they exist in the code today, then proposes a "bold reinvention" toward a
denser, terminal-grade information architecture — without losing the existing dark
theme, accent-green identity, or the recharts/Tailwind/shadcn stack.

Three companion mockups were produced alongside this doc (rendered in chat): the
proposed bento Dashboard, the data-dense Budget grid, and the terminal-grade Explore
grid. This document is the written spec behind those visuals.

---

## 0. The core problem, in one sentence

The panels are built from **uniform, equally-weighted cards in a loose grid**, so
the layout reads as "a list of boxes" rather than "a cockpit." The eye has no
hierarchy to latch onto, there is meaningful empty space inside cards, and a
surprising amount of data the backend already computes never reaches the screen.

The fix is not more cards. It is a **deliberate grid with weighted regions**, every
region carrying a live metric, and a handful of genuinely new infographics built
from data that already exists in the API.

---

## 1. What works today (keep these)

A fair audit starts with what's already good, because the overhaul should preserve it:

- **The token system is clean and centralized.** `index.css` `:root` HSL vars +
  `tailwind.config.ts` + `chartColors.ts` give a single source of truth for color,
  including the important detail that recharts reads literal hex (so the JS palette
  mirrors the CSS tokens). This is exactly the foundation a denser redesign needs.
- **Semantic gain/loss/warning colors are consistent** across all three panels.
- **The `card` / `card-muted` component classes** already enforce consistent radius,
  border, and padding — the grid overhaul can lean on these rather than reinventing.
- **FX conversion is handled rigorously** (`useFxRates`, `convertBag`, per-holding
  currency). Any new metric can reuse this and stay multi-currency-correct.
- **Empty / loading / skeleton states exist** on every panel. The Budget skeleton and
  the per-card `Loader2` spinners are good; the redesign should keep this discipline.
- **The Budget `KPICard` is the strongest single component** — animated count-up,
  MoM delta pill, tone ring, per-currency fallback. It should become the _template_
  for metric cards everywhere, including the Dashboard.

---

## 2. Cross-cutting findings (apply to all three panels)

### 2.1 The grid is uniform where it should be weighted

- Dashboard uses `grid-cols-6` with every card spanning 2 (`lg:col-span-2`), i.e.
  three equal columns. Budget uses `lg:grid-cols-3` and `lg:grid-cols-2` blocks.
  Discover uses `lg:grid-cols-2`. In all three, **cards carry roughly equal visual
  weight**, so nothing signals "look here first."
- **Proposal:** move to an explicit 12-column bento on the Dashboard (hero full-width;
  a 4/4/4 KPI row; then asymmetric 5/4/3 and 7/5 rows). Weighted spans create the
  hierarchy the flat grid lacks. Budget and Explore get the same treatment with 7/5
  and 5/7 splits so the "primary" region in each row is unmistakable.

### 2.2 Data the backend computes but the UI never shows

This is the highest-leverage finding. The API surface (`src/lib/api.ts`) and backend
already expose rich fields that no panel renders:

| Field / endpoint | Where it lives | Surfaced today? |
|---|---|---|
| Per-position **day P&L** | `/briefing` computes `day_pnl` (main.py ~L1150) | Only as one brief text line |
| `change_today` on holdings | Read defensively in Dashboard hero | **Never returned by `/portfolio`** — hero delta is always 0 |
| `credit_card_debt` | `BudgetSummary.credit_card_debt` | **Not rendered anywhere** |
| 8-dimension stock score | `/insights/8dim` → `EightDimResult` | Only in `TickerDrawer` + chat, not on Explore grid |
| RSI / SMA technicals | `/insights/technicals` → `TechnicalsResult` | Only in drawer + chat |
| Dividend yield / safety | `/insights/dividend` → `DividendResult` | Only in drawer + chat |
| Fund returns 1m/3m/6m/1y/ytd | `FundRow` | Funds page only |
| `most_active` tickers | `TrendsResult.most_active` | **Fetched-typed but unused** |
| Goal progress | `/goals` | Count only on Dashboard; no progress viz |
| `acquired_at` per holding | `Holding` | Unused (could power holding-age / cost-vs-now) |

> **Note on `change_today`:** the Dashboard hero (`Dashboard.tsx` L206–218) sums
> `value * change_today/100`, but `/portfolio` (main.py L874–886) never includes a
> `change_today` key — so `todayDelta` is always 0 and the hero silently falls back
> to the static subtitle. This is a real bug-shaped gap, not just a design one. The
> redesign's "▲ $X today" hero depends on the backend adding this field (the
> `/briefing` path already does the per-position math, so it's a small lift).

### 2.3 Empty space inside cards

- Dashboard `NetWorthCard` only draws its sparkline when `history.length >= 2`;
  with sparse history the card is mostly blank. `BudgetSnapshotCard` shows 2–3 rows
  of text in a card sized for more. The donut cards reserve a fixed `h-44`/`h-36`
  even when data is thin.
- **Proposal:** every card should have a "dense state" — when the headline metric is
  present, fill the remaining height with a secondary infographic (sparkline, mini
  bar row, progress track, or contextual insight line) rather than whitespace.

### 2.4 No contextual "coach" insight layer

The product is a _finance coach_, but the panels mostly _report_ numbers. There's a
`/briefing` and the chat agents, but the static panels rarely _interpret_. The
overhaul should thread a thin **insight line** into cards: "savings rate up 7pts MoM,"
"NVDA drives 48% of today's gain," "you're 5% over your equity target." These are
cheap to compute from data already on the client and directly serve engagement +
the coaching mission.

---

## 3. Dashboard — panel deep-dive

**Current structure** (`Dashboard.tsx`): top bar → hero (avatar + greeting + today
delta) → 6-col grid of five equal-ish cards (NetWorth 2, BudgetSnapshot 2, Briefing 2,
Allocation 2, Holdings 4) → NextStep CTA → disclaimer.

### What to change

1. **Hero becomes a live strip, not a greeting.** Keep the avatar + greeting, but make
   the "▲ $X today · +Y%" the visual anchor (the data finally works once `change_today`
   ships). Add net-worth and savings-rate micro-stats inline.
2. **Promote to a 12-col bento.** Suggested rows:
   - Row A: full-width hero strip.
   - Row B: three 4-span metric cards — Net worth (with sparkline), Cash flow MTD
     (with a 6-bar income/expense mini chart), Savings rate (with a progress track and
     MoM comparison).
   - Row C: 5-span **Allocation vs target** (drift donut + over/under list), 4-span
     **Top mover today** (ticker + its share of today's gain), 3-span **Goal progress**
     (ring + pace).
   - Row D: 7-span **Holdings table with per-row sparklines** + sortable columns,
     5-span **Daily brief**.
3. **Allocation card upgrade: drift, not just slices.** Today it's a plain donut by
   asset class. Add the user's _target_ allocation (derivable from `risk_profile`'s
   equity band, already in `ReasoningPayload.equity_band`) and show over/under per
   class. This is a high-value coaching infographic.
4. **Holdings table → sparkline + sortable.** Add a 30-day mini-line per row (reuse the
   net-worth history pattern, or a new lightweight per-ticker series) and make P&L /
   value sortable. Fills the table's horizontal space with signal.
5. **Top mover attribution.** "NVDA +4.2%, drives 48% of today's gain" — a single
   computed line that makes the dashboard feel intelligent. Pure client-side math over
   per-position day P&L.

### Specific richer-metric placements

- Hero: today $ delta + % (needs `change_today`), net worth, savings rate.
- Net worth card: sparkline always (even 2 pts), plus best/worst position chips.
- Cash-flow card: 6-month income-vs-expense micro bars.
- New Goal card: ring + "on pace / behind" using `target_date` vs `current_amount`.

---

## 4. Budget — panel deep-dive

**Current structure** (`Budget.tsx`): header → 4 KPI cards (cash, income, spending,
net) → categories donut + upcoming charges (3-col) → accounts + recurring-income
(2-col) → subscriptions → transactions table.

This is the most feature-complete panel; the opportunity is **surfacing hidden data**
and **filling the band above accounts** with trend infographics.

### What to change

1. **Add a 5th KPI: Credit-card debt + utilization.** `credit_card_debt` is in
   `BudgetSummary` and rendered nowhere. For a coach app, debt + utilization is a
   first-class number. Use the existing `KPICard` with a warning tone.
2. **New trend band (currently empty conceptual space).** Above accounts, add a 7/5 row:
   - 7-span **Income vs expense, 6 months** — two lines. The data needs a small backend
     addition (monthly aggregates) or can be approximated from transactions client-side.
   - 5-span **30-day spend heatmap** — a calendar grid colored by daily spend, built
     from `transactions` you already fetch. This is the single most "modern fintech"
     visual you can add and it's pure client-side.
3. **Upcoming charges → timeline view.** Today it's a sorted list with day badges.
   Reframe as a horizontal "next 30 days" timeline so income (green, right) and
   expenses (red/amber) are spatially placed — turns a list into an infographic.
4. **Categories donut → keep, but add MoM per category.** The donut is good; append a
   small "+12% vs last month" per legend row (you have `top_categories`; prev-month
   would need a parallel query or a backend field).
5. **Transactions table: add a running-balance column or inline category sparkbars.**
   The table is currently text-only; a thin per-category spark or a running balance
   gives the eye something to scan.

### Specific richer-metric placements

- KPI row: 4 → 5 cards (add card debt). Each KPI keeps the MoM delta pill.
- New band: 6-month income/expense lines + 30-day spend heatmap.
- Upcoming: timeline with income/expense on opposite sides.
- Categories: MoM delta per row.

---

## 5. Explore (Discover) — panel deep-dive

**Current structure** (`Discover.tsx`): header → personalized banner → global crypto
bar → movers + trending crypto (2-col) → portfolio spotlight → news → rumors. It's a
single descending column of full-width sections.

The panel is data-rich but **all the deep per-ticker intelligence is hidden in the
`TickerDrawer`** — the grid itself is mostly lists. This is where "terminal-grade"
pays off most.

### What to change

1. **Market-pulse strip up top.** Compress the global crypto bar into a 5-cell stat
   strip: S&P 500, BTC dominance, crypto cap, fear/greed, 24h change. (Fear/greed is a
   live data source per CLAUDE.md but isn't surfaced here.) Dense, scannable, sets the
   tone.
2. **Watchlist grid with 8-dim score + RSI — the headline new feature.** Pull the
   `/insights/8dim`, `/insights/technicals` data that currently only appears on click,
   and show it inline for the user's holdings + a watchlist: a recommendation badge
   (buy/hold/sell), the 0–10 score as a bar, and an RSI gauge per row. This single
   change is what makes Explore feel like a pro tool.
3. **Movers → diverging bar chart.** The current `MoversCard` already does a vertical
   bar; lean into a true diverging layout (gainers right, losers left from a center
   axis) for instant read.
4. **News → sentiment-weighted rail.** You have `RumorItem.sentiment` / `impact_score`;
   apply the same to the news list: a colored sentiment edge + a numeric score per
   headline. Merges the separate News and Rumor sections into one ranked rail.
5. **Use `most_active`.** It's typed in `TrendsResult` and fetched but never rendered —
   add a compact "most active" column or chips.

### Specific richer-metric placements

- Top strip: 5 macro stats incl. fear/greed.
- Watchlist grid: 8-dim score bar + recommendation badge + RSI gauge per ticker.
- Movers: diverging bars from a center axis.
- News rail: sentiment edge + score, merged with rumors.

---

## 6. Visual strategy — achieving the "cutting-edge" aesthetic

The goal is denser and more confident, while staying native to the existing dark theme.

1. **Bento grid, weighted spans.** Asymmetric column spans (12-col base) are the single
   biggest "modern" lever. Equal cards read as a CMS; weighted regions read as a product.
2. **Tighten the rhythm.** Current gaps are `gap-4`; a denser cockpit reads better at
   `gap-2`/`gap-3` with slightly reduced card padding (`p-4` → `p-3.5`) so more signal
   fits above the fold.
3. **Monospace for all numerals.** The `.num` class (JetBrains Mono, tabular-nums)
   already exists — apply it universally to figures, tickers, deltas, and axis labels.
   Tabular alignment is a hallmark of finance-grade UI.
4. **Infographic-first cards.** Replace text rows with: sparklines, mini bar rows,
   progress tracks, drift indicators, heatmaps, gauges. Every card earns its height.
5. **A consistent insight line.** One muted, italic-weight contextual sentence per card
   ("drives 48% of today's gain"). This is the coaching voice made visual.
6. **Restrained motion.** Keep the existing `framer-motion` stagger on KPI mount and the
   count-up; add subtle on-scroll reveal for the new infographic band. Avoid motion-heavy
   dashboards — finance users want fast, not bouncy.
7. **Color discipline.** Keep accent-green for brand/interaction only (the `chartColors`
   note already enforces this), gain/loss/warning for semantics, and the categorical
   palette for multi-series. Don't introduce new hues; density should come from layout
   and data, not from a louder palette.

---

## 7. Priority recommendations (highest impact first)

1. **Surface hidden data before adding any new chrome.** Card debt, per-position day
   P&L, 8-dim/RSI on the Explore grid, `most_active`. These are the cheapest, highest-
   value wins because the data already exists. (Item 2.2.)
2. **Fix + ship the Dashboard "today delta."** Add `change_today` to `/portfolio`
   (the `/briefing` math already exists), then the hero's headline number works. (2.2.)
3. **Re-grid the Dashboard into a 12-col bento** with the drift-allocation card and
   per-row holding sparklines. Biggest perceived-quality jump. (Section 3.)
4. **Add the Budget trend band** — 6-month income/expense + 30-day spend heatmap. The
   heatmap is pure client-side and the most "modern fintech" single addition. (Section 4.)
5. **Build the Explore watchlist grid** with inline 8-dim score + RSI. Turns Explore
   from a feed into a tool. (Section 5.)
6. **Thread the insight line** through cards across all three panels for the coaching
   voice. (Item 2.4.)

---

## 8. Open questions / dependencies

- `change_today` on `/portfolio` and 6-month budget aggregates are **backend additions**;
  everything else is client-side or reuses existing endpoints.
- The 8-dim/technicals calls can be slow (the API has a `fast` flag) — the watchlist grid
  should lazy-load scores per row with skeletons, not block the panel.
- Target-allocation drift needs a source of truth for "target." `equity_band` from the
  risk profile is the simplest; a fuller target model could come later.

_All structural and data-availability claims above were checked against `Dashboard.tsx`,
`Budget.tsx`, `Discover.tsx`, `src/lib/api.ts`, and `backend/app/main.py`._
