/**
 * dataviz — small, dependency-light presentational primitives used across the
 * Dashboard, Budget and Explore panels to fill cards with signal instead of
 * whitespace. Each component is pure (no data fetching) and reads the same
 * design tokens (gain/loss/accent) as the rest of the app.
 *
 * Charts here are hand-rolled inline SVG rather than recharts because they are
 * tiny (sparklines, gauges, heatmap cells) and recharts' ResponsiveContainer is
 * overkill — and slower — at this size.
 */
import { type ReactNode } from "react";
import { cn } from "@/lib/cn";
import { GAIN, LOSS, ACCENT, pnlColor } from "@/lib/chartColors";

// ── Sparkline ────────────────────────────────────────────────────────────────

export function Sparkline({
  values,
  width = 64,
  height = 18,
  color,
  strokeWidth = 1.5,
  className,
}: {
  values: number[];
  width?: number;
  height?: number;
  color?: string;
  strokeWidth?: number;
  className?: string;
}) {
  if (values.length < 2) return null;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const stepX = width / (values.length - 1);
  const pts = values
    .map((v, i) => {
      const x = i * stepX;
      const y = height - ((v - min) / span) * height;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  const stroke = color ?? pnlColor(values[values.length - 1] - values[0]);
  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className={className}
      preserveAspectRatio="none"
      aria-hidden="true"
    >
      <polyline
        points={pts}
        fill="none"
        stroke={stroke}
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

// ── MiniBars (e.g. income/expense over recent months) ────────────────────────

export function MiniBars({
  values,
  height = 36,
  className,
  colorFor,
}: {
  values: number[];
  height?: number;
  className?: string;
  /** Optional per-bar color; defaults to accent. */
  colorFor?: (value: number, index: number) => string;
}) {
  if (values.length === 0) return null;
  const max = Math.max(...values.map((v) => Math.abs(v))) || 1;
  return (
    <div
      className={cn("flex items-end gap-1", className)}
      style={{ height }}
      aria-hidden="true"
    >
      {values.map((v, i) => (
        <div
          key={i}
          className="flex-1 rounded-sm"
          style={{
            height: `${Math.max(6, (Math.abs(v) / max) * height)}px`,
            background: colorFor ? colorFor(v, i) : ACCENT,
            opacity: 0.85,
          }}
        />
      ))}
    </div>
  );
}

// ── ProgressTrack ────────────────────────────────────────────────────────────

export function ProgressTrack({
  pct,
  color = ACCENT,
  className,
}: {
  pct: number;
  color?: string;
  className?: string;
}) {
  const clamped = Math.max(0, Math.min(100, pct));
  return (
    <div
      className={cn(
        "h-1.5 w-full overflow-hidden rounded-full bg-surface-raised",
        className,
      )}
    >
      <div
        className="h-full rounded-full transition-all duration-500"
        style={{ width: `${clamped}%`, background: color }}
      />
    </div>
  );
}

// ── RSI gauge (0-100 with overbought/oversold zones) ─────────────────────────

export function RsiGauge({ value, className }: { value: number | null; className?: string }) {
  if (value == null) {
    return <span className={cn("text-[10px] text-content-muted", className)}>RSI —</span>;
  }
  const v = Math.max(0, Math.min(100, value));
  // Overbought (>70) red, oversold (<30) green-ish opportunity, mid neutral.
  const color = v >= 70 ? LOSS : v <= 30 ? GAIN : "hsl(var(--text-muted))";
  return (
    <div className={cn("flex items-center gap-1.5", className)}>
      <div className="h-1 w-12 overflow-hidden rounded-full bg-surface-raised">
        <div className="h-full rounded-full" style={{ width: `${v}%`, background: color }} />
      </div>
      <span className="num text-[10px] tabular-nums" style={{ color }}>
        {Math.round(v)}
      </span>
    </div>
  );
}

// ── InsightLine — the coaching voice, one muted sentence per card ─────────────

export function InsightLine({
  icon,
  children,
  tone = "neutral",
  className,
}: {
  icon?: ReactNode;
  children: ReactNode;
  tone?: "neutral" | "positive" | "negative" | "warning";
  className?: string;
}) {
  const toneCls =
    tone === "positive" ? "text-gain"
    : tone === "negative" ? "text-loss"
    : tone === "warning" ? "text-warning"
    : "text-content-muted";
  return (
    <p className={cn("mt-2 flex items-start gap-1.5 text-[11px] leading-snug", toneCls, className)}>
      {icon && <span className="mt-0.5 shrink-0">{icon}</span>}
      <span>{children}</span>
    </p>
  );
}

// ── Diverging bar (one row of a gainers/losers chart) ────────────────────────

export function DivergingBar({
  pct,
  max,
  label,
  className,
}: {
  pct: number;
  max: number;
  label?: string;
  className?: string;
}) {
  const positive = pct >= 0;
  const width = max ? (Math.abs(pct) / max) * 100 : 0;
  return (
    <div className={cn("flex items-center gap-2 text-xs", className)}>
      {label && <span className="num w-12 shrink-0 truncate font-semibold">{label}</span>}
      <div className="flex h-3 flex-1 items-center">
        <div className="flex w-1/2 justify-end">
          {!positive && (
            <div
              className="h-3 rounded-l-sm"
              style={{ width: `${width}%`, background: LOSS, opacity: 0.85 }}
            />
          )}
        </div>
        <div className="w-px self-stretch bg-line" />
        <div className="flex w-1/2 justify-start">
          {positive && (
            <div
              className="h-3 rounded-r-sm"
              style={{ width: `${width}%`, background: GAIN, opacity: 0.85 }}
            />
          )}
        </div>
      </div>
      <span className={cn("num w-12 shrink-0 text-right", positive ? "text-gain" : "text-loss")}>
        {positive ? "+" : ""}{pct.toFixed(1)}%
      </span>
    </div>
  );
}

// ── SpendHeatmap (30-day calendar of daily spend) ────────────────────────────

export interface HeatCell {
  date: string; // ISO yyyy-mm-dd
  value: number;
}

export function SpendHeatmap({
  cells,
  columns = 10,
  className,
}: {
  cells: HeatCell[];
  columns?: number;
  className?: string;
}) {
  const max = Math.max(...cells.map((c) => c.value), 0) || 1;
  // Teal ramp from chartColors-adjacent values; lightest = no/low spend.
  function shade(v: number): string {
    if (v <= 0) return "hsl(var(--surface-2))";
    const t = v / max; // 0..1
    if (t < 0.2) return "#9FE1CB";
    if (t < 0.4) return "#5DCAA5";
    if (t < 0.6) return "#1D9E75";
    if (t < 0.8) return "#0F6E56";
    return "#085041";
  }
  return (
    <div
      className={cn("grid gap-1", className)}
      style={{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }}
      aria-hidden="true"
    >
      {cells.map((c) => (
        <div
          key={c.date}
          title={`${c.date}: ${c.value.toFixed(0)}`}
          className="rounded-sm"
          style={{ aspectRatio: "1", background: shade(c.value) }}
        />
      ))}
    </div>
  );
}

// ── DonutRing (single-value progress ring, e.g. goals) ───────────────────────

export function DonutRing({
  pct,
  size = 72,
  stroke = 10,
  color = ACCENT,
  children,
}: {
  pct: number;
  size?: number;
  stroke?: number;
  color?: string;
  children?: ReactNode;
}) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const clamped = Math.max(0, Math.min(100, pct));
  const dash = (clamped / 100) * c;
  return (
    <div className="relative inline-flex items-center justify-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden="true">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke="hsl(var(--surface-2))"
          strokeWidth={stroke}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={color}
          strokeWidth={stroke}
          strokeDasharray={`${dash} ${c - dash}`}
          strokeLinecap="round"
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
        />
      </svg>
      {children && (
        <div className="absolute inset-0 flex items-center justify-center text-center">
          {children}
        </div>
      )}
    </div>
  );
}
