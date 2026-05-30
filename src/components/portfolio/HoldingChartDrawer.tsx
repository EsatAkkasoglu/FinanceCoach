/**
 * HoldingChartDrawer — slide-in panel with a historical price chart for a
 * single holding. Works for any asset class: stocks/ETFs/indices/crypto via
 * yfinance/CoinGecko, and TEFAS funds via the fund history endpoint.
 */
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { X, Loader2 } from "lucide-react";
import {
  CartesianGrid, LineChart, Line, ResponsiveContainer,
  Tooltip as RechartsTooltip, XAxis, YAxis,
} from "recharts";

import { priceHistory, type FundHistoryPoint } from "@/lib/api";
import { ACCENT, chartTooltip } from "@/lib/chartColors";
import { cn } from "@/lib/cn";

const RANGES = [30, 90, 180, 365] as const;

interface Props {
  ticker: string | null;
  assetClass: string | null;
  onClose: () => void;
}

export function HoldingChartDrawer({ ticker, assetClass, onClose }: Props) {
  const { t } = useTranslation("portfolio");
  const [days, setDays] = useState<number>(90);
  const [points, setPoints] = useState<FundHistoryPoint[]>([]);
  const [currency, setCurrency] = useState<string | undefined>();
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!ticker) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    setPoints([]);
    priceHistory(ticker, assetClass ?? "stock", days)
      .then((r) => {
        if (cancelled) return;
        setPoints(r.points);
        setCurrency(r.currency);
        if (r.error || r.points.length < 2) {
          setError(r.error ?? t("chart.noData", { defaultValue: "No historical data available." }));
        }
      })
      .catch((e) => { if (!cancelled) setError((e as Error).message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [ticker, assetClass, days, t]);

  const stats = useMemo(() => {
    if (points.length < 2) return null;
    const first = points[0].price;
    const last = points[points.length - 1].price;
    if (!first) return null;
    const totalReturn = ((last - first) / first) * 100;
    const min = Math.min(...points.map((p) => p.price));
    const max = Math.max(...points.map((p) => p.price));
    return { totalReturn, min, max, last };
  }, [points]);

  const { niceDomain, niceTicks, formatTick } = useMemo(() => {
    if (!stats) {
      return {
        niceDomain: ["auto", "auto"] as [number | string, number | string],
        niceTicks: undefined as number[] | undefined,
        formatTick: (v: number) => v.toFixed(2),
      };
    }
    const range = stats.max - stats.min || stats.max * 0.01 || 1;
    const pad = range * 0.08;
    const lo = stats.min - pad;
    const hi = stats.max + pad;
    const rawStep = (hi - lo) / 4;
    const mag = Math.pow(10, Math.floor(Math.log10(rawStep)));
    const norm = rawStep / mag;
    const niceMul = norm < 1.5 ? 1 : norm < 3 ? 2 : norm < 7 ? 5 : 10;
    const step = niceMul * mag;
    const start = Math.floor(lo / step) * step;
    const end = Math.ceil(hi / step) * step;
    const ticks: number[] = [];
    for (let v = start; v <= end + step / 2; v += step) ticks.push(parseFloat(v.toFixed(10)));
    const decimals = step >= 10 ? 0 : step >= 1 ? 2 : step >= 0.1 ? 3 : 4;
    return {
      niceDomain: [start, end] as [number, number],
      niceTicks: ticks,
      formatTick: (v: number) => v.toFixed(decimals),
    };
  }, [stats]);

  if (!ticker) return null;

  return (
    <div className="fixed inset-0 z-40" role="dialog" aria-modal="true">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />
      <aside className="absolute right-0 top-0 flex h-full w-full max-w-xl flex-col overflow-y-auto border-l border-line bg-bg p-5 shadow-2xl animate-in slide-in-from-right">
        <header className="mb-4 flex items-start justify-between gap-3">
          <div>
            <p className="text-overline uppercase text-content-muted">
              {t("chart.title", { defaultValue: "Price history" })}
            </p>
            <h2 className="font-mono text-3xl font-semibold text-emerald-300">{ticker}</h2>
            {currency && (
              <p className="mt-0.5 text-[11px] text-content-muted">{currency}</p>
            )}
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-2 text-content-muted hover:bg-surface-raised hover:text-content"
            aria-label={t("chart.close", { defaultValue: "Close" })}
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="mb-3 flex items-center gap-2">
          {RANGES.map((d) => (
            <button
              key={d}
              onClick={() => setDays(d)}
              className={cn(
                "rounded-full border px-2.5 py-0.5 text-[10px] transition",
                days === d
                  ? "border-accent bg-accent-muted text-accent"
                  : "border-line text-content-muted hover:text-content",
              )}
            >
              {d}d
            </button>
          ))}
          {stats && (
            <span className="ml-auto text-xs">
              <span className={cn("num font-semibold", stats.totalReturn >= 0 ? "text-gain" : "text-loss")}>
                {stats.totalReturn >= 0 ? "+" : ""}{stats.totalReturn.toFixed(2)}%
              </span>
            </span>
          )}
        </div>

        <div className="h-72">
          {loading ? (
            <div className="flex h-full items-center justify-center text-content-muted">
              <Loader2 className="h-5 w-5 animate-spin" />
            </div>
          ) : error || points.length < 2 ? (
            <div className="flex h-full items-center justify-center text-xs text-content-muted">
              {error ?? t("chart.noData", { defaultValue: "No historical data available." })}
            </div>
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={points} margin={{ top: 8, right: 16, left: 8, bottom: 4 }}>
                <CartesianGrid stroke="hsl(var(--border))" strokeDasharray="2 4" vertical={false} opacity={0.4} />
                <XAxis
                  dataKey="date"
                  tick={{ fill: "hsl(var(--text-muted))", fontSize: 10 }}
                  tickLine={false}
                  axisLine={false}
                  interval="preserveStartEnd"
                  minTickGap={56}
                  tickMargin={8}
                  padding={{ left: 8, right: 8 }}
                  tickFormatter={(v: string) => {
                    const d = new Date(v);
                    return isNaN(d.getTime()) ? v : d.toLocaleDateString(undefined, { month: "short", day: "2-digit" });
                  }}
                />
                <YAxis
                  orientation="right"
                  domain={niceDomain}
                  ticks={niceTicks}
                  tick={{ fill: "hsl(var(--text-muted))", fontSize: 10 }}
                  tickLine={false}
                  axisLine={false}
                  width={56}
                  tickFormatter={formatTick}
                  tickMargin={6}
                />
                <RechartsTooltip
                  {...chartTooltip}
                  formatter={(v: number) => [formatTick(v), t("chart.price", { defaultValue: "Price" })]}
                />
                <Line
                  type="monotone"
                  dataKey="price"
                  stroke={ACCENT}
                  strokeWidth={2}
                  dot={false}
                  isAnimationActive
                  animationDuration={600}
                  animationEasing="ease-out"
                />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>
      </aside>
    </div>
  );
}
