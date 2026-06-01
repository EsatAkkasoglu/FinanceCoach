/**
 * Renders the standard envelope returned by the backend `calc_*` tools
 * (see backend/app/tools/_calc_result.py). The backend already did the math
 * AND the formatting, so this component only PRESENTS:
 *   • formatted_value verbatim (never re-formats numbers)
 *   • the formula, as a "show the math" caption
 *   • a dataviz picked by `ui_type` via a plain switch — no key-sniffing.
 */
import { DivergingBar, DonutRing, ProgressTrack } from "@/components/ui/dataviz";
import { cn } from "@/lib/cn";

export interface CalcEnvelope {
  ok?: boolean;
  raw_value?: unknown;
  formatted_value?: string;
  formula?: string | null;
  explanation?: string | null;
  ui_type?: "metric" | "donut" | "diverging_bar" | "bars" | "table" | "none";
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
      {env.formula && (
        <p className={cn("font-mono text-[10px] text-content-muted break-words")}>{env.formula}</p>
      )}
    </div>
  );
}
