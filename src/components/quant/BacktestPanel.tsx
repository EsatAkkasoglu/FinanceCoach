/**
 * Backtest panel — run a rule over real price history and see what it did.
 *
 * Two things are deliberately not optional in the UI: the buy & hold line is
 * always drawn next to the strategy, and the walk-forward block is always shown
 * (including when it says it couldn't run). A backtest without either is the
 * kind that flatters itself.
 */
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useReducedMotion } from "framer-motion";
import { AlertTriangle, Play } from "lucide-react";
import {
  CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { Button } from "@/components/ui/Button";
import { Field, Select, TextInput } from "@/components/ui/Field";
import {
  getQuantStrategies, runBacktest,
  type BacktestResponse, type StrategyInfo,
} from "@/lib/api";
import { ACCENT, chartTooltip, LOSS, NEUTRAL } from "@/lib/chartColors";
import { cn } from "@/lib/cn";

function Stat({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="rounded-lg bg-surface-raised px-2.5 py-2">
      <div className="text-[10px] uppercase tracking-wide text-content-muted">{label}</div>
      <div className={cn("num text-sm font-semibold", tone ?? "text-content")}>{value}</div>
    </div>
  );
}

const fmt = (n: number | null | undefined, digits = 2, suffix = "") =>
  n == null ? "—" : `${n.toFixed(digits)}${suffix}`;

const signTone = (n: number | null | undefined) =>
  n == null ? "text-content-muted" : n >= 0 ? "text-gain" : "text-loss";

export function BacktestPanel() {
  const { t } = useTranslation("quant");
  const reduce = useReducedMotion();

  const [strategies, setStrategies] = useState<StrategyInfo[]>([]);
  const [ticker, setTicker] = useState("SPY");
  const [strategy, setStrategy] = useState("sma_cross");
  const [periodDays, setPeriodDays] = useState(1825);
  const [feeBps, setFeeBps] = useState(10);
  const [slippageBps, setSlippageBps] = useState(5);
  const [allowShort, setAllowShort] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<BacktestResponse | null>(null);

  useEffect(() => {
    let cancelled = false;
    getQuantStrategies()
      .then((s) => { if (!cancelled) setStrategies(s); })
      .catch(() => undefined);
    return () => { cancelled = true; };
  }, []);

  async function run() {
    setBusy(true);
    try {
      setResult(await runBacktest({
        ticker, strategy, period_days: periodDays,
        fee_bps: feeBps, slippage_bps: slippageBps,
        allow_short: allowShort, walk_forward: true,
      }));
    } catch (e) {
      setResult({ ok: false, error: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(false);
    }
  }

  const m = result?.metrics;
  const wf = result?.walk_forward;
  const rows = (result?.equity ?? []).map((v, i) => ({
    i,
    date: result?.dates?.[i] ?? "",
    strategy: (v - 1) * 100,
    benchmark: result?.benchmark?.[i] != null ? (result.benchmark[i] - 1) * 100 : null,
    drawdown: result?.drawdown?.[i] ?? null,
  }));

  return (
    <div className="space-y-4">
      <div className="card">
        <h2 className="mb-1 text-base font-semibold">{t("backtest.title")}</h2>
        <p className="mb-3 text-xs text-content-muted">{t("backtest.hint")}</p>

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          <Field label={t("backtest.ticker")}>
            <TextInput
              value={ticker}
              onChange={(e) => setTicker(e.target.value)}
              placeholder={t("backtest.tickerPlaceholder")}
            />
          </Field>
          <Field label={t("backtest.strategy")}>
            <Select
              value={strategy}
              onChange={(e) => setStrategy(e.target.value)}
              options={(strategies.length
                ? strategies.map((s) => s.key)
                : ["sma_cross", "ema_cross", "macd", "rsi_reversion", "tsmom", "donchian", "buy_hold"]
              ).map((k) => ({ value: k, label: k.replace(/_/g, " ") }))}
            />
          </Field>
          <Field label={t("backtest.period")}>
            <TextInput
              type="number" min={90} max={3650} value={periodDays}
              onChange={(e) => setPeriodDays(Number(e.target.value))}
            />
          </Field>
          <Field label={t("backtest.fee")}>
            <TextInput
              type="number" min={0} max={500} value={feeBps}
              onChange={(e) => setFeeBps(Number(e.target.value))}
            />
          </Field>
          <Field label={t("backtest.slippage")}>
            <TextInput
              type="number" min={0} max={500} value={slippageBps}
              onChange={(e) => setSlippageBps(Number(e.target.value))}
            />
          </Field>
          <div className="flex items-end gap-2">
            <label className="flex items-center gap-1.5 pb-2 text-xs text-content-muted">
              <input
                type="checkbox" checked={allowShort}
                onChange={(e) => setAllowShort(e.target.checked)}
                className="accent-accent"
              />
              {t("backtest.allowShort")}
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

      {result?.ok && m && (
        <>
          <div className="card">
            <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-6">
              <Stat label={t("backtest.metrics.totalReturn")}
                    value={fmt(m.total_return_pct, 1, "%")} tone={signTone(m.total_return_pct)} />
              <Stat label={t("backtest.metrics.benchmark")}
                    value={fmt(m.benchmark_return_pct, 1, "%")} tone={signTone(m.benchmark_return_pct)} />
              <Stat label={t("backtest.metrics.excess")}
                    value={fmt(m.excess_vs_buy_hold_pct, 1, "%")} tone={signTone(m.excess_vs_buy_hold_pct)} />
              <Stat label={t("backtest.metrics.sharpe")}
                    value={fmt(m.sharpe_annualized)} tone={signTone(m.sharpe_annualized)} />
              <Stat label={t("backtest.metrics.maxDd")}
                    value={fmt(m.max_drawdown_pct, 1, "%")} tone="text-loss" />
              <Stat label={t("backtest.metrics.costDrag")}
                    value={fmt(m.cost_drag_pct, 2, "%")} tone="text-content-muted" />
            </div>

            <div className="h-56 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                  <CartesianGrid stroke="hsl(var(--border))" strokeOpacity={0.35} vertical={false} />
                  <XAxis
                    dataKey="date" minTickGap={64}
                    tick={{ fontSize: 10, fill: "hsl(var(--text-muted))" }}
                    axisLine={false} tickLine={false}
                  />
                  <YAxis
                    width={48} tick={{ fontSize: 10, fill: "hsl(var(--text-muted))" }}
                    tickFormatter={(v: number) => `${Math.round(v)}%`}
                    axisLine={false} tickLine={false}
                  />
                  <ReferenceLine y={0} stroke="hsl(var(--border))" />
                  <Tooltip {...chartTooltip}
                           formatter={(v: number, name: string) => [`${v.toFixed(1)}%`, name]} />
                  <Line type="monotone" dataKey="benchmark" name={t("backtest.buyHold")}
                        dot={false} stroke={NEUTRAL} strokeWidth={1.25} strokeDasharray="4 4"
                        isAnimationActive={!reduce} />
                  <Line type="monotone" dataKey="strategy" name={t("backtest.strategyLabel")}
                        dot={false} stroke={ACCENT} strokeWidth={2}
                        isAnimationActive={!reduce} />
                </LineChart>
              </ResponsiveContainer>
            </div>

            <div className="mt-2 h-20 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={rows} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
                  <XAxis dataKey="date" hide />
                  <YAxis width={48} tick={{ fontSize: 10, fill: "hsl(var(--text-muted))" }}
                         tickFormatter={(v: number) => `${Math.round(v)}%`}
                         axisLine={false} tickLine={false} domain={["dataMin", 0]} />
                  <Tooltip {...chartTooltip}
                           formatter={(v: number) => [`${v.toFixed(1)}%`, t("backtest.drawdown")]} />
                  <Line type="monotone" dataKey="drawdown" name={t("backtest.drawdown")}
                        dot={false} stroke={LOSS} strokeWidth={1.25} isAnimationActive={!reduce} />
                </LineChart>
              </ResponsiveContainer>
            </div>

            <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-6">
              <Stat label={t("backtest.metrics.cagr")} value={fmt(m.cagr_pct, 1, "%")} />
              <Stat label={t("backtest.metrics.vol")} value={fmt(m.ann_vol_pct, 1, "%")} />
              <Stat label={t("backtest.metrics.sortino")} value={fmt(m.sortino)} />
              <Stat label={t("backtest.metrics.calmar")} value={fmt(m.calmar)} />
              <Stat label={t("backtest.metrics.winRate")}
                    value={m.win_rate == null ? "—" : `${(m.win_rate * 100).toFixed(0)}%`} />
              <Stat label={t("backtest.metrics.trades")} value={String(m.n_trades)} />
            </div>
          </div>

          <WalkForward wf={wf} />
        </>
      )}
    </div>
  );
}

function WalkForward({ wf }: { wf: BacktestResponse["walk_forward"] }) {
  const { t } = useTranslation("quant");
  if (!wf) return null;

  if (!wf.ok) {
    return (
      <div className="card border-l-4 border-l-warning">
        <h3 className="mb-1 flex items-center gap-2 text-sm font-semibold">
          <AlertTriangle className="h-4 w-4 text-warning" />
          {t("backtest.walkForwardTitle")}
        </h3>
        <p className="text-xs text-content-muted">
          {t("backtest.walkForwardUnavailable", { reason: wf.reason ?? "" })}
        </p>
      </div>
    );
  }

  const dsr = wf.oos_dsr;
  const survives = dsr != null && dsr > 0.5;

  return (
    <div className={cn("card border-l-4", survives ? "border-l-gain" : "border-l-warning")}>
      <h3 className="mb-1 text-sm font-semibold">{t("backtest.walkForwardTitle")}</h3>
      <p className="mb-3 text-xs text-content-muted">
        {t("backtest.walkForwardNote", { trials: wf.n_trials ?? 1 })}
      </p>

      <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-5">
        <Stat label={t("backtest.testReturn")} value={fmt(wf.oos_return_pct, 1, "%")}
              tone={signTone(wf.oos_return_pct)} />
        <Stat label={t("backtest.metrics.sharpe")} value={fmt(wf.oos_sharpe_annualized)}
              tone={signTone(wf.oos_sharpe_annualized)} />
        <Stat label={t("backtest.metrics.sortino")} value={fmt(wf.oos_sortino)} />
        <Stat label={t("backtest.metrics.maxDd")} value={fmt(wf.oos_max_drawdown_pct, 1, "%")}
              tone="text-loss" />
        <Stat label={t("backtest.metrics.dsr")} value={fmt(dsr)}
              tone={survives ? "text-gain" : "text-warning"} />
      </div>

      <p className={cn("mb-3 text-xs", survives ? "text-content-muted" : "text-warning")}>
        {survives ? t("backtest.survives") : t("backtest.overfitWarning")}
      </p>

      {(wf.folds?.length ?? 0) > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="text-[10px] uppercase tracking-wide text-content-muted">
              <tr>
                <th className="py-1 text-left font-medium">{t("backtest.fold")}</th>
                <th className="py-1 text-left font-medium">{t("backtest.params")}</th>
                <th className="py-1 text-center font-medium">{t("backtest.trainBars")}</th>
                <th className="py-1 text-center font-medium">{t("backtest.testBars")}</th>
                <th className="py-1 text-center font-medium">{t("backtest.trainSharpe")}</th>
                <th className="py-1 text-center font-medium">{t("backtest.testSharpe")}</th>
                <th className="py-1 text-center font-medium">{t("backtest.testReturn")}</th>
              </tr>
            </thead>
            <tbody>
              {wf.folds?.map((f) => (
                <tr key={f.fold} className="border-t border-border/60">
                  <td className="py-1.5">{f.fold}</td>
                  <td className="py-1.5 font-mono text-[10px] text-content-muted">
                    {Object.entries(f.params).map(([k, v]) => `${k}=${v}`).join(" ") || "—"}
                  </td>
                  <td className="py-1.5 text-center tabular-nums">{f.train_bars}</td>
                  <td className="py-1.5 text-center tabular-nums">{f.test_bars}</td>
                  <td className="py-1.5 text-center tabular-nums">{fmt(f.train_sharpe)}</td>
                  <td className={cn("py-1.5 text-center tabular-nums", signTone(f.test_sharpe))}>
                    {fmt(f.test_sharpe)}
                  </td>
                  <td className={cn("py-1.5 text-center tabular-nums", signTone(f.test_return_pct))}>
                    {fmt(f.test_return_pct, 1, "%")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
