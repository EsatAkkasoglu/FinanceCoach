/**
 * Single source of truth for chart colors.
 *
 * Recharts renders to SVG and reads literal color strings on `stroke` / `fill`
 * props, so it cannot consume Tailwind classes or `hsl(var(--…))` reliably.
 * This module mirrors the design tokens (tailwind.config.ts) as JS constants so
 * the same palette is shared across Dashboard, Budget and Funds instead of being
 * redefined per file.
 *
 * Keep these hexes in sync with the `gain` / `loss` / `warning` tokens.
 */

import type { CSSProperties } from "react";

// Semantic up/down — must match the `gain` / `loss` tokens in tailwind.config.ts.
export const GAIN = "#22C55E"; // tailwind token: gain
export const LOSS = "#EF4444"; // tailwind token: loss

/** Pick gain/loss color from a signed value (>= 0 is gain). */
export const pnlColor = (value: number): string => (value >= 0 ? GAIN : LOSS);

// Brand accent — for single-series charts that aren't gain/loss (e.g. price line).
export const ACCENT = "#1FB57A"; // tailwind token: accent

/**
 * Categorical palette — for multi-slice / multi-series charts where colors only
 * need to be distinct (budget category donut, etc.). Ordered for good adjacent
 * contrast. Brand green is intentionally excluded so slices never read as the
 * interactive accent.
 */
export const CHART_PALETTE = [
  "#14B8A6", // teal
  "#8B5CF6", // violet
  "#F59E0B", // amber
  "#3B82F6", // blue
  "#EC4899", // pink
  "#10B981", // emerald
  "#EF4444", // red
] as const;

/** Cycle the categorical palette by index (wraps automatically). */
export const paletteAt = (i: number): string =>
  CHART_PALETTE[((i % CHART_PALETTE.length) + CHART_PALETTE.length) % CHART_PALETTE.length];

/**
 * Asset-class color map — semantic, named slices for the portfolio allocation
 * chart. Each class keeps a stable, recognizable color.
 */
export const ASSET_COLORS: Record<string, string> = {
  stock: "#14B8A6", // teal — non-brand so it doesn't read as interactive
  etf: "#8B5CF6", // violet
  crypto: "#F59E0B", // amber
  bond: "#3B82F6", // blue
  cash: "#9CA3AF", // gray
};

/** Neutral gray fallback for an unknown category / asset class. */
export const NEUTRAL = "#9CA3AF";

/** Look up an asset-class color, falling back to neutral gray. */
export const assetColor = (name: string): string => ASSET_COLORS[name] ?? NEUTRAL;

/**
 * Shared Recharts tooltip theming. The tooltip renders to a DOM <div>, so it can
 * consume `hsl(var(--…))` CSS variables directly (unlike SVG stroke/fill props).
 * Centralizing these keeps every chart's tooltip visually identical and tied to
 * the surface/text/border tokens in index.css.
 *
 * Usage:  <Tooltip {...chartTooltip} formatter={…} />
 */

export const chartTooltipContentStyle: CSSProperties = {
  background: "hsl(var(--surface))",
  border: "1px solid hsl(var(--border))",
  borderRadius: 8,
  fontSize: 12,
};

export const chartTooltipLabelStyle: CSSProperties = {
  color: "hsl(var(--text-muted))",
};

export const chartTooltipItemStyle: CSSProperties = {
  color: "hsl(var(--text))",
};

/** Spread onto a Recharts <Tooltip /> to apply the shared theme in one shot. */
export const chartTooltip = {
  contentStyle: chartTooltipContentStyle,
  labelStyle: chartTooltipLabelStyle,
  itemStyle: chartTooltipItemStyle,
} as const;
