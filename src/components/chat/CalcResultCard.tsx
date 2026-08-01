/**
 * Renders the standard envelope returned by the backend `calc_*` tools
 * (see backend/app/tools/_calc_result.py). The backend already did the math
 * AND the formatting, so this component only PRESENTS:
 *   • formatted_value verbatim (never re-formats numbers)
 *   • the formula, as a "show the math" caption
 *   • a dataviz picked by `ui_type` via a plain switch — no key-sniffing.
 */
import { useReducedMotion } from "framer-motion";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";
import { DivergingBar, DonutRing, ProgressTrack } from "@/components/ui/dataviz";
import { ACCENT, chartTooltip, GAIN, LOSS, NEUTRAL } from "@/lib/chartColors";
import { cn } from "@/lib/cn";

export interface CalcEnvelope {
  ok?: boolean;
  raw_value?: unknown;
  formatted_value?: string;
  formula?: string | null;
  explanation?: string | null;
  /** Mirrors `UiType` in backend/app/tools/_calc_result.py — keep both in sync. */
  ui_type?:
    | "metric"
    | "donut"
    | "diverging_bar"
    | "bars"
    | "table"
    | "none"
    | "equity_curve"
    | "frontier"
    | "heatmap";
  data?: Record<string, unknown>;
  error?: string;
  inputs_received?: Record<string, unknown>;
}

/** True for both success and error envelopes from the calc tool layer. */
export function isCalcEnvelope(v: unknown): v is CalcEnvelope {
  if (!v || typeof v !== "object") return false;
  const o = v as Record<string, unknown>;
  return typeof o.ok === "boolean" && ("ui_type" in o || "error" in o || "formatted_value" in o);
}

interface LabeledValue {
  label: string;
  value: number;
}

function asBars(data: Record<string, unknown> | undefined): LabeledValue[] {
  const raw = (data?.bars ?? data?.allocation) as unknown;
  if (!Array.isArray(raw)) return [];
  return raw
    .filter((r): r is Record<string, unknown> => !!r && typeof r === "object")
    .map((r) => ({ label: String(r.label ?? r.asset_class ?? "?"), value: Number(r.value ?? 0) }))
    .filter((r) => Number.isFinite(r.value));
}

function fmtPct(n: number): string {
  return `${n > 0 ? "+" : ""}${n.toFixed(1)}%`;
}

function MetricView({ env }: { env: CalcEnvelope }) {
  const d = env.data ?? {};
  const extras: Array<[string, unknown]> = [];
  // Surface the few interpretable breakdown fields when present.
  for (const k of ["total_contributed", "growth", "required_monthly", "hhi", "level"]) {
    if (d[k] != null) extras.push([k.replace(/_/g, " "), d[k]]);
  }
  return (
    <div className="space-y-1">
      <p className="num text-lg font-semibold text-content">{env.formatted_value ?? "—"}</p>
      {extras.length > 0 && (
        <p className="text-[10px] text-content-muted">
          {extras.map(([k, v]) => `${k}: ${typeof v === "number" ? v.toLocaleString("en-US") : String(v)}`).join(" · ")}
        </p>
      )}
    </div>
  );
}

function BarsView({ data }: { data?: Record<string, unknown> }) {
  const bars = asBars(data);
  if (bars.length === 0) return null;
  return (
    <div className="space-y-1.5">
      {bars.slice(0, 10).map((b, i) => (
        <div key={`${b.label}-${i}`} className="flex items-center gap-2">
          <span className="w-24 shrink-0 truncate text-[11px] text-content-muted">{b.label}</span>
          <ProgressTrack pct={b.value} className="flex-1" />
          <span className="num w-12 shrink-0 text-right text-[11px] text-content">{b.value.toFixed(1)}%</span>
        </div>
      ))}
    </div>
  );
}

function DivergingView({ data }: { data?: Record<string, unknown> }) {
  const bars = asBars(data);
  if (bars.length === 0) return null;
  const max = Math.max(...bars.map((b) => Math.abs(b.value)), 1);
  return (
    <div className="space-y-1.5">
      {bars.slice(0, 10).map((b, i) => (
        <DivergingBar key={`${b.label}-${i}`} pct={b.value} max={max} label={`${b.label} ${fmtPct(b.value)}`} />
      ))}
    </div>
  );
}

function TableView({ data }: { data?: Record<string, unknown> }) {
  const rows = (data?.rows ?? data?.matrix) as unknown;
  if (!Array.isArray(rows) || rows.length === 0) return null;
  const records = rows.filter((r): r is Record<string, unknown> => !!r && typeof r === "object");
  if (records.length === 0) return null;
  // metric/value/unit rows (return metrics) render as a clean 2-col list;
  // anything else renders generically from the union of keys.
  if ("metric" in records[0] && "value" in records[0]) {
    return (
      <div className="grid grid-cols-[1fr_auto] gap-x-3 gap-y-1">
        {records.map((r, i) => (
          <div key={i} className="contents">
            <span className="text-[11px] text-content-muted">{String(r.metric)}</span>
            <span className="num text-right text-[11px] text-content">
              {typeof r.value === "number" ? r.value.toLocaleString("en-US") : String(r.value ?? "—")}
              {r.unit ? String(r.unit) : ""}
            </span>
          </div>
        ))}
      </div>
    );
  }
  const cols = Array.from(new Set(records.flatMap((r) => Object.keys(r)))).slice(0, 6);
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[10px]">
        <thead>
          <tr className="text-content-muted">
            {cols.map((c) => (
              <th key={c} className="px-1 py-0.5 text-left font-medium uppercase">{c.replace(/_/g, " ")}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {records.slice(0, 8).map((r, i) => (
            <tr key={i} className="border-t border-line">
              {cols.map((c) => (
                <td key={c} className="num px-1 py-0.5 text-content">
                  {r[c] == null ? "—" : typeof r[c] === "number" ? (r[c] as number).toLocaleString("en-US") : String(r[c])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function numbers(data: Record<string, unknown> | undefined, key: string): number[] {
  const raw = data?.[key];
  if (!Array.isArray(raw)) return [];
  return raw.map((v) => Number(v)).filter((v) => Number.isFinite(v));
}

/**
 * Backtest equity curve: strategy vs buy & hold, with drawdown underneath.
 *
 * The backend downsamples to ≤80 points and sends parallel float arrays (not
 * objects) to fit the 4000-char SSE cap, so the x-axis is positional — only the
 * two endpoint dates are labelled.
 */
function EquityCurveView({ data }: { data?: Record<string, unknown> }) {
  const reduce = useReducedMotion();
  const equity = numbers(data, "equity");
  const benchmark = numbers(data, "benchmark");
  const drawdown = numbers(data, "drawdown");
  if (equity.length < 2) return null;

  const rows = equity.map((v, i) => ({
    i,
    strategy: (v - 1) * 100,
    benchmark: benchmark[i] != null ? (benchmark[i] - 1) * 100 : null,
    drawdown: drawdown[i] ?? null,
  }));
  const start = typeof data?.start_date === "string" ? data.start_date : "";
  const end = typeof data?.end_date === "string" ? data.end_date : "";
  const final = rows[rows.length - 1];
  const beat = (final.strategy ?? 0) >= (final.benchmark ?? 0);

  return (
    <div className="space-y-1">
      <div className="h-32 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={rows} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
            <CartesianGrid stroke="hsl(var(--border))" strokeOpacity={0.35} vertical={false} />
            <XAxis dataKey="i" hide />
            <YAxis
              width={38}
              tick={{ fontSize: 9, fill: "hsl(var(--text-muted))" }}
              tickFormatter={(v: number) => `${Math.round(v)}%`}
              axisLine={false}
              tickLine={false}
            />
            <ReferenceLine y={0} stroke="hsl(var(--border))" />
            <Tooltip
              {...chartTooltip}
              labelFormatter={() => ""}
              formatter={(v: number, name: string) => [`${v.toFixed(1)}%`, name]}
            />
            <Line
              type="monotone" dataKey="benchmark" name="Buy & hold" dot={false}
              stroke={NEUTRAL} strokeWidth={1.25} strokeDasharray="3 3"
              isAnimationActive={!reduce}
            />
            <Line
              type="monotone" dataKey="strategy" name="Strategy" dot={false}
              stroke={beat ? ACCENT : LOSS} strokeWidth={1.75}
              isAnimationActive={!reduce}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
      {drawdown.length > 1 && (
        <div className="h-10 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={rows} margin={{ top: 2, right: 4, bottom: 0, left: 0 }}>
              <XAxis dataKey="i" hide />
              <YAxis width={38} hide domain={["dataMin", 0]} />
              <Tooltip
                {...chartTooltip}
                labelFormatter={() => ""}
                formatter={(v: number) => [`${v.toFixed(1)}%`, "Drawdown"]}
              />
              <Line
                type="monotone" dataKey="drawdown" dot={false}
                stroke={LOSS} strokeWidth={1} isAnimationActive={!reduce}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
      {(start || end) && (
        <div className="flex justify-between text-[9px] text-content-muted">
          <span>{start}</span>
          <span>{end}</span>
        </div>
      )}
    </div>
  );
}

/** Efficient frontier scatter with the user's current portfolio marked on it. */
function FrontierView({ data }: { data?: Record<string, unknown> }) {
  const reduce = useReducedMotion();
  const raw = data?.points;
  const points = (Array.isArray(raw) ? raw : [])
    .map((p) => p as Record<string, unknown>)
    .map((p) => ({ x: Number(p.vol_pct), y: Number(p.return_pct) }))
    .filter((p) => Number.isFinite(p.x) && Number.isFinite(p.y));
  if (points.length < 2) return null;

  const asPoint = (v: unknown) => {
    const o = (v ?? {}) as Record<string, unknown>;
    const x = Number(o.vol_pct);
    const y = Number(o.return_pct);
    return Number.isFinite(x) && Number.isFinite(y) ? [{ x, y }] : [];
  };
  const current = asPoint(data?.current);
  const optimal = asPoint(data?.optimal);

  return (
    <div className="space-y-1">
      <div className="h-36 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart margin={{ top: 6, right: 8, bottom: 14, left: 0 }}>
            <CartesianGrid stroke="hsl(var(--border))" strokeOpacity={0.35} />
            <XAxis
              type="number" dataKey="x" name="Risk"
              tick={{ fontSize: 9, fill: "hsl(var(--text-muted))" }}
              tickFormatter={(v: number) => `${v.toFixed(0)}%`}
              label={{ value: "vol", position: "insideBottom", offset: -8, fontSize: 9,
                       fill: "hsl(var(--text-muted))" }}
            />
            <YAxis
              type="number" dataKey="y" name="Return" width={38}
              tick={{ fontSize: 9, fill: "hsl(var(--text-muted))" }}
              tickFormatter={(v: number) => `${v.toFixed(0)}%`}
            />
            <ZAxis range={[28, 90]} />
            <Tooltip
              {...chartTooltip}
              cursor={{ strokeDasharray: "3 3" }}
              formatter={(v: number, name: string) => [`${v.toFixed(2)}%`, name]}
            />
            <Scatter name="Frontier" data={points} fill={NEUTRAL} isAnimationActive={!reduce} />
            {current.length > 0 && (
              <Scatter name="Current" data={current} fill={LOSS} shape="cross"
                       isAnimationActive={!reduce} />
            )}
            {optimal.length > 0 && (
              <Scatter name="Optimal" data={optimal} fill={GAIN} shape="star"
                       isAnimationActive={!reduce} />
            )}
          </ScatterChart>
        </ResponsiveContainer>
      </div>
      <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-[9px] text-content-muted">
        <span className="flex items-center gap-1">
          <i className="h-1.5 w-1.5 rounded-full" style={{ background: NEUTRAL }} /> frontier
        </span>
        <span className="flex items-center gap-1">
          <i className="h-1.5 w-1.5 rounded-full" style={{ background: LOSS }} /> current
        </span>
        <span className="flex items-center gap-1">
          <i className="h-1.5 w-1.5 rounded-full" style={{ background: GAIN }} /> optimal
        </span>
      </div>
      <BarsView data={data} />
    </div>
  );
}

/** Matrix heatmap (correlation, vol surface) — teal ramp, same idea as SpendHeatmap. */
function HeatmapView({ data }: { data?: Record<string, unknown> }) {
  const labelsRaw = data?.labels;
  const matrixRaw = data?.matrix;
  const labels = (Array.isArray(labelsRaw) ? labelsRaw : []).map(String);
  const matrix = (Array.isArray(matrixRaw) ? matrixRaw : [])
    .map((row) => (Array.isArray(row) ? row.map((v) => Number(v)) : []))
    .filter((row) => row.length > 0);
  if (labels.length === 0 || matrix.length === 0) return null;

  const flat = matrix.flat().filter((v) => Number.isFinite(v));
  const lo = Math.min(...flat);
  const hi = Math.max(...flat);
  const span = hi - lo || 1;
  const cols = labels.slice(0, 8);

  return (
    <div className="overflow-x-auto">
      <table className="border-separate border-spacing-0.5 text-[9px]">
        <thead>
          <tr>
            <th />
            {cols.map((c) => (
              <th key={c} className="px-1 font-medium text-content-muted">{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {matrix.slice(0, 8).map((row, r) => (
            <tr key={labels[r] ?? r}>
              <td className="pr-1 text-right font-medium text-content-muted">{labels[r] ?? r}</td>
              {row.slice(0, 8).map((v, c) => (
                <td
                  key={c}
                  className="num h-6 w-9 rounded text-center text-content"
                  style={{
                    background: `color-mix(in srgb, ${ACCENT} ${Math.round(((v - lo) / span) * 82)}%, transparent)`,
                  }}
                  title={`${labels[r]} · ${cols[c]}: ${v.toFixed(2)}`}
                >
                  {v.toFixed(2)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function CalcResultCard({ env }: { env: CalcEnvelope }) {
  if (env.ok === false) {
    return (
      <div className="rounded-md border border-loss/40 bg-loss/5 p-2 text-[11px] text-loss">
        <span className="font-medium">Couldn't compute:</span> {env.error ?? "unknown error"}
      </div>
    );
  }

  const ui = env.ui_type ?? "none";
  return (
    <div className="space-y-2">
      {/* Headline number always comes straight from the tool. */}
      {env.formatted_value && ui !== "metric" && (
        <p className="num text-sm font-semibold text-content">{env.formatted_value}</p>
      )}
      {ui === "metric" && <MetricView env={env} />}
      {ui === "bars" && <BarsView data={env.data} />}
      {ui === "donut" && typeof env.raw_value === "number" && (
        <div className="flex justify-center">
          <DonutRing pct={Number(env.raw_value)}>
            <span className="num text-xs text-content">{env.formatted_value}</span>
          </DonutRing>
        </div>
      )}
      {ui === "diverging_bar" && <DivergingView data={env.data} />}
      {ui === "table" && <TableView data={env.data} />}
      {ui === "equity_curve" && <EquityCurveView data={env.data} />}
      {ui === "frontier" && <FrontierView data={env.data} />}
      {ui === "heatmap" && <HeatmapView data={env.data} />}
      {env.formula && (
        <p className={cn("font-mono text-[10px] text-content-muted break-words")}>{env.formula}</p>
      )}
    </div>
  );
}
