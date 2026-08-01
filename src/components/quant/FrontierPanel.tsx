/**
 * Optimization panel — efficient frontier over the user's REAL holdings.
 *
 * The current portfolio is always plotted next to the optimum, because "your
 * Sharpe would be 1.4" means nothing without "and it is 1.1 today". The
 * shrinkage intensity and any non-convergence are surfaced rather than hidden:
 * an optimizer that quietly fell back is worse than one that says it did.
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useReducedMotion } from "framer-motion";
import { AlertTriangle, Play } from "lucide-react";
import {
  CartesianGrid, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis,
} from "recharts";
import { Button } from "@/components/ui/Button";
import { Field, Select, TextInput } from "@/components/ui/Field";
import { ProgressTrack } from "@/components/ui/dataviz";
import { optimizePortfolio, type OptimizeResponse } from "@/lib/api";
import { chartTooltip, GAIN, LOSS, NEUTRAL } from "@/lib/chartColors";
import { cn } from "@/lib/cn";

const fmt = (n: number | null | undefined, digits = 2, suffix = "") =>
  n == null ? "—" : `${n.toFixed(digits)}${suffix}`;

export function FrontierPanel() {
  const { t } = useTranslation("quant");
  const reduce = useReducedMotion();

  const [objective, setObjective] = useState("max_sharpe");
  const [periodDays, setPeriodDays] = useState(365);
  const [longOnly, setLongOnly] = useState(true);
  const [maxWeight, setMaxWeight] = useState(0);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<OptimizeResponse | null>(null);

  async function run() {
    setBusy(true);
    try {
      setResult(await optimizePortfolio({
        objective, period_days: periodDays,
        long_only: longOnly, max_weight_pct: maxWeight,
      }));
    } catch (e) {
      setResult({ ok: false, error: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(false);
    }
  }

  const points = (result?.points ?? []).map((p) => ({ x: p.vol_pct, y: p.return_pct }));
  const current = result?.current ? [{ x: result.current.vol_pct, y: result.current.return_pct }] : [];
  const optimal = result?.optimal ? [{ x: result.optimal.vol_pct, y: result.optimal.return_pct }] : [];

  return (
    <div className="space-y-4">
      <div className="card">
        <h2 className="mb-1 text-base font-semibold">{t("optimize.title")}</h2>
        <p className="mb-3 text-xs text-content-muted">{t("optimize.hint")}</p>

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Field label={t("optimize.objective")}>
            <Select
              value={objective}
              onChange={(e) => setObjective(e.target.value)}
              options={[
                { value: "max_sharpe", label: t("optimize.objectives.max_sharpe") },
                { value: "min_variance", label: t("optimize.objectives.min_variance") },
                { value: "risk_parity", label: t("optimize.objectives.risk_parity") },
              ]}
            />
          </Field>
          <Field label={t("optimize.period")}>
            <TextInput type="number" min={90} max={1825} value={periodDays}
                       onChange={(e) => setPeriodDays(Number(e.target.value))} />
          </Field>
          <Field label={t("optimize.maxWeight")}>
            <TextInput type="number" min={0} max={100} value={maxWeight}
                       onChange={(e) => setMaxWeight(Number(e.target.value))} />
          </Field>
          <div className="flex items-end">
            <label className="flex items-center gap-1.5 pb-2 text-xs text-content-muted">
              <input type="checkbox" checked={longOnly}
                     onChange={(e) => setLongOnly(e.target.checked)} className="accent-accent" />
              {t("optimize.longOnly")}
            </label>
          </div>
        </div>

        <Button onClick={run} loading={busy} className="mt-3">
          {!busy && <Play className="h-3.5 w-3.5" />}
          {busy ? t("common.running") : t("common.run")}
        </Button>
      </div>

      {result && !result.ok && (
        <div className="card border-l-4 border-l-loss text-sm text-loss">{result.error}</div>
      )}

      {result?.ok && (
        <>
          {result.converged === false && (
            <div className="card flex items-start gap-2 border-l-4 border-l-warning text-xs text-warning">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              {t("optimize.notConverged")}
            </div>
          )}

          <div className="card">
            <h3 className="mb-2 text-sm font-semibold">{t("optimize.frontier")}</h3>
            <div className="h-64 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <ScatterChart margin={{ top: 8, right: 12, bottom: 18, left: 0 }}>
                  <CartesianGrid stroke="hsl(var(--border))" strokeOpacity={0.35} />
                  <XAxis type="number" dataKey="x" name="vol"
                         tick={{ fontSize: 10, fill: "hsl(var(--text-muted))" }}
                         tickFormatter={(v: number) => `${v.toFixed(0)}%`} />
                  <YAxis type="number" dataKey="y" name="return" width={48}
                         tick={{ fontSize: 10, fill: "hsl(var(--text-muted))" }}
                         tickFormatter={(v: number) => `${v.toFixed(0)}%`} />
                  <ZAxis range={[40, 140]} />
                  <Tooltip {...chartTooltip} cursor={{ strokeDasharray: "3 3" }}
                           formatter={(v: number, name: string) => [`${v.toFixed(2)}%`, name]} />
                  <Scatter name={t("optimize.frontier")} data={points} fill={NEUTRAL}
                           isAnimationActive={!reduce} />
                  {current.length > 0 && (
                    <Scatter name={t("optimize.current")} data={current} fill={LOSS}
                             shape="cross" isAnimationActive={!reduce} />
                  )}
                  {optimal.length > 0 && (
                    <Scatter name={t("optimize.optimal")} data={optimal} fill={GAIN}
                             shape="star" isAnimationActive={!reduce} />
                  )}
                </ScatterChart>
              </ResponsiveContainer>
            </div>

            <div className="mt-2 flex flex-wrap gap-4 text-xs text-content-muted">
              {result.current && (
                <span>
                  <i className="mr-1 inline-block h-2 w-2 rounded-full align-middle"
                     style={{ background: LOSS }} />
                  {t("optimize.current")}: {fmt(result.current.return_pct, 1, "%")} /{" "}
                  {fmt(result.current.vol_pct, 1, "%")} · Sharpe {fmt(result.current.sharpe)}
                </span>
              )}
              {result.optimal && (
                <span>
                  <i className="mr-1 inline-block h-2 w-2 rounded-full align-middle"
                     style={{ background: GAIN }} />
                  {t("optimize.optimal")}: {fmt(result.optimal.return_pct, 1, "%")} /{" "}
                  {fmt(result.optimal.vol_pct, 1, "%")} · Sharpe {fmt(result.optimal.sharpe)}
                </span>
              )}
            </div>

            {result.shrinkage != null && (
              <p className="mt-2 text-[10px] text-content-muted">
                {t("optimize.shrinkage", { value: result.shrinkage.toFixed(2) })}
              </p>
            )}
          </div>

          {(result.changes?.length ?? 0) > 0 && (
            <div className="card">
              <h3 className="mb-2 text-sm font-semibold">{t("optimize.changes")}</h3>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead className="text-[10px] uppercase tracking-wide text-content-muted">
                    <tr>
                      <th className="py-1 text-left font-medium">{t("optimize.ticker")}</th>
                      <th className="py-1 text-center font-medium">{t("optimize.currentPct")}</th>
                      <th className="py-1 text-center font-medium">{t("optimize.targetPct")}</th>
                      <th className="py-1 text-center font-medium">{t("optimize.changePct")}</th>
                      <th className="py-1 pl-3 text-left font-medium">{t("optimize.targetWeights")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.changes?.map((c) => (
                      <tr key={c.ticker} className="border-t border-border/60">
                        <td className="py-1.5 font-medium">{c.ticker}</td>
                        <td className="py-1.5 text-center tabular-nums">{fmt(c.current_pct, 1, "%")}</td>
                        <td className="py-1.5 text-center tabular-nums">{fmt(c.target_pct, 1, "%")}</td>
                        <td className={cn(
                          "py-1.5 text-center tabular-nums",
                          c.change_pct >= 0 ? "text-gain" : "text-loss",
                        )}>
                          {c.change_pct >= 0 ? "+" : ""}{c.change_pct.toFixed(1)}%
                        </td>
                        <td className="py-1.5 pl-3">
                          <ProgressTrack pct={Math.max(0, c.target_pct)} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
