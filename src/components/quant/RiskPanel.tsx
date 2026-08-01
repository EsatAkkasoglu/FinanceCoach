/**
 * Risk panel — tail risk and benchmark statistics for the real portfolio.
 *
 * Loads on mount (unlike the other two panels, it needs no input beyond the
 * holdings already on file), and re-runs when the window or confidence changes.
 */
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useReducedMotion } from "framer-motion";
import {
  Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { Field, Select, TextInput } from "@/components/ui/Field";
import { getQuantRisk, type QuantRiskResponse } from "@/lib/api";
import { chartTooltip, LOSS } from "@/lib/chartColors";
import { cn } from "@/lib/cn";

const fmt = (n: number | null | undefined, digits = 2, suffix = "") =>
  n == null ? "—" : `${n.toFixed(digits)}${suffix}`;

function Stat({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="rounded-lg bg-surface-raised px-2.5 py-2">
      <div className="text-[10px] uppercase tracking-wide text-content-muted">{label}</div>
      <div className={cn("num text-sm font-semibold", tone ?? "text-content")}>{value}</div>
    </div>
  );
}

export function RiskPanel() {
  const { t } = useTranslation("quant");
  const reduce = useReducedMotion();

  const [periodDays, setPeriodDays] = useState(365);
  const [confidence, setConfidence] = useState(0.95);
  const [benchmark, setBenchmark] = useState("SPY");
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState<QuantRiskResponse | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await getQuantRisk(periodDays, confidence, benchmark));
    } catch (e) {
      setData({ ok: false, error: e instanceof Error ? e.message : String(e) });
    } finally {
      setLoading(false);
    }
  }, [periodDays, confidence, benchmark]);

  useEffect(() => {
    let cancelled = false;
    // Debounced so typing in the number field doesn't fire a request per keystroke.
    const id = setTimeout(() => { if (!cancelled) void load(); }, 350);
    return () => { cancelled = true; clearTimeout(id); };
  }, [load]);

  const curve = (data?.drawdown_curve ?? []).map((v, i) => ({ i, dd: v }));
  const stats = data?.benchmark_stats;

  return (
    <div className="space-y-4">
      <div className="card">
        <h2 className="mb-1 text-base font-semibold">{t("risk.title")}</h2>
        <p className="mb-3 text-xs text-content-muted">{t("risk.hint")}</p>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <Field label={t("risk.period")}>
            <TextInput type="number" min={60} max={1825} value={periodDays}
                       onChange={(e) => setPeriodDays(Number(e.target.value))} />
          </Field>
          <Field label={t("risk.confidence")}>
            <Select
              value={String(confidence)}
              onChange={(e) => setConfidence(Number(e.target.value))}
              options={[
                { value: "0.9", label: "90%" },
                { value: "0.95", label: "95%" },
                { value: "0.99", label: "99%" },
              ]}
            />
          </Field>
          <Field label={t("risk.benchmark")}>
            <TextInput value={benchmark}
                       onChange={(e) => setBenchmark(e.target.value.toUpperCase())} />
          </Field>
        </div>
      </div>

      {loading && <div className="card text-sm text-content-muted">{t("common.loading")}</div>}

      {!loading && data && !data.ok && (
        <div className="card border-l-4 border-l-loss text-sm text-loss">{data.error}</div>
      )}

      {!loading && data?.ok && (
        <>
          <div className="card">
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7">
              <Stat label={t("risk.var")} value={fmt(data.var_pct, 2, "%")} tone="text-loss" />
              <Stat label={t("risk.cvar")} value={fmt(data.cvar_pct, 2, "%")} tone="text-loss" />
              <Stat label={t("risk.cornishFisher")}
                    value={fmt(data.cornish_fisher_var_pct, 2, "%")} tone="text-loss" />
              <Stat label={t("risk.ewmaVol")} value={fmt(data.ewma_vol_pct, 1, "%")} />
              <Stat label={t("risk.worstDay")} value={fmt(data.worst_day_pct, 2, "%")}
                    tone="text-loss" />
              <Stat label={t("risk.maxDd")} value={fmt(data.max_drawdown_pct, 1, "%")}
                    tone="text-loss" />
              <Stat label={t("risk.observations")} value={String(data.n_obs ?? 0)} />
            </div>
          </div>

          {curve.length > 1 && (
            <div className="card">
              <h3 className="mb-2 text-sm font-semibold">{t("risk.drawdownCurve")}</h3>
              <div className="h-40 w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={curve} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
                    <defs>
                      <linearGradient id="ddFill" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor={LOSS} stopOpacity={0.05} />
                        <stop offset="100%" stopColor={LOSS} stopOpacity={0.35} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid stroke="hsl(var(--border))" strokeOpacity={0.35}
                                   vertical={false} />
                    <XAxis dataKey="i" hide />
                    <YAxis width={48} tick={{ fontSize: 10, fill: "hsl(var(--text-muted))" }}
                           tickFormatter={(v: number) => `${Math.round(v)}%`}
                           axisLine={false} tickLine={false} domain={["dataMin", 0]} />
                    <Tooltip {...chartTooltip} labelFormatter={() => ""}
                             formatter={(v: number) => [`${v.toFixed(2)}%`, t("risk.maxDd")]} />
                    <Area type="monotone" dataKey="dd" stroke={LOSS} strokeWidth={1.25}
                          fill="url(#ddFill)" isAnimationActive={!reduce} />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}

          {stats && (
            <div className="card">
              <h3 className="mb-2 text-sm font-semibold">
                {t("risk.benchmarkTitle", { benchmark: data.benchmark })}
              </h3>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7">
                <Stat label={t("risk.beta")} value={fmt(stats.beta)} />
                <Stat label={t("risk.alpha")} value={fmt(stats.alpha_annualized_pct, 2, "%")}
                      tone={stats.alpha_annualized_pct >= 0 ? "text-gain" : "text-loss"} />
                <Stat label={t("risk.r2")} value={fmt(stats.r2)} />
                <Stat label={t("risk.trackingError")}
                      value={fmt(stats.tracking_error_pct, 1, "%")} />
                <Stat label={t("risk.idioVol")} value={fmt(stats.idiosyncratic_vol_pct, 1, "%")} />
                <Stat label={t("risk.upCapture")}
                      value={fmt(data.capture?.up_capture_pct, 0, "%")} />
                <Stat label={t("risk.downCapture")}
                      value={fmt(data.capture?.down_capture_pct, 0, "%")} />
              </div>
            </div>
          )}

          {(data.weights?.length ?? 0) > 0 && (
            <div className="card">
              <h3 className="mb-2 text-sm font-semibold">{t("risk.weights")}</h3>
              <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-content-muted">
                {data.weights?.map((w) => (
                  <span key={w.label} className="num">
                    {w.label} {w.value.toFixed(1)}%
                  </span>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
