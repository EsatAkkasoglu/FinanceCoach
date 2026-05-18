/**
 * Funds — Turkish TEFAS mutual & pension fund explorer.
 *
 * Backed by /funds/{search,top,quote,history}. Lets the user browse the
 * universe by category chip, search by free text, and inspect a 30/90-day
 * NAV history for any fund.
 */
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Loader2, Search } from "lucide-react";
import {
  CartesianGrid, LineChart, Line, ResponsiveContainer, Tooltip as RechartsTooltip, XAxis, YAxis,
} from "recharts";

import {
  searchFunds,
  topFunds,
  fundHistory,
  type FundRow,
  type FundHistoryPoint,
} from "@/lib/api";
import { cn } from "@/lib/cn";

function ReturnCell({ value }: { value: number | null | undefined }) {
  if (value == null) return <td className="px-3 py-2 text-right text-[hsl(var(--text-muted))]">—</td>;
  const cls = value >= 0 ? "text-gain" : "text-loss";
  return (
    <td className={cn("px-3 py-2 text-right num tabular-nums", cls)}>
      {value >= 0 ? "+" : ""}{value.toFixed(2)}%
    </td>
  );
}

const CATEGORY_KEYS: { key: string; tKey: string }[] = [
  { key: "altın", tKey: "categories.gold" },
  { key: "hisse", tKey: "categories.equity" },
  { key: "eurobond", tKey: "categories.eurobond" },
  { key: "fon sepeti", tKey: "categories.basket" },
  { key: "kıymetli", tKey: "categories.preciousMetals" },
  { key: "kısa vadeli", tKey: "categories.shortTerm" },
];

export function Funds() {
  const { t } = useTranslation("funds");
  const [category, setCategory] = useState<string | null>("altın");
  const [query, setQuery] = useState("");
  const [rows, setRows] = useState<FundRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<FundRow | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        let results: FundRow[];
        if (query.trim()) {
          results = await searchFunds(query.trim(), "mutual", 25);
        } else if (category) {
          results = await topFunds("best_rank", 25, category);
        } else {
          results = await topFunds("best_rank", 25);
        }
        if (!cancelled) setRows(results);
      } catch (e) {
        if (!cancelled) setError((e as Error).message || "Funds failed to load");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    const debounce = window.setTimeout(load, query ? 250 : 0);
    return () => {
      cancelled = true;
      window.clearTimeout(debounce);
    };
  }, [category, query]);

  return (
    <div className="flex flex-col gap-4">
      <header>
        <h1 className="text-xl font-semibold tracking-tight">{t("title")}</h1>
        <p className="text-sm text-[hsl(var(--text-muted))]">
          {t("subtitle")}
        </p>
      </header>

      <div className="flex flex-wrap items-center gap-2">
        {CATEGORY_KEYS.map((c) => (
          <button
            key={c.key}
            onClick={() => { setCategory(c.key); setQuery(""); }}
            className={cn(
              "rounded-full border px-3 py-1 text-xs transition",
              category === c.key && !query
                ? "border-accent bg-accent-muted text-accent"
                : "border-[hsl(var(--border))] text-[hsl(var(--text-muted))] hover:text-[hsl(var(--text))]",
            )}
          >
            {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
            {(t as any)(c.tKey)}
          </button>
        ))}
        <button
          onClick={() => { setCategory(null); setQuery(""); }}
          className={cn(
            "rounded-full border px-3 py-1 text-xs transition",
            !category && !query
              ? "border-accent bg-accent-muted text-accent"
              : "border-[hsl(var(--border))] text-[hsl(var(--text-muted))] hover:text-[hsl(var(--text))]",
          )}
        >
          {t("allBest")}
        </button>

        <div className="ml-auto relative w-full max-w-xs">
          <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[hsl(var(--text-muted))]" />
          <input
            value={query}
            onChange={(e) => { setQuery(e.target.value); }}
            placeholder={t("searchPlaceholder")}
            className="w-full rounded-full border border-[hsl(var(--border))] bg-[hsl(var(--surface-2))] py-1.5 pl-8 pr-3 text-xs outline-none focus:border-accent"
          />
        </div>
      </div>

      <div className="card overflow-hidden p-0">
        {loading && (
          <div className="flex h-32 items-center justify-center text-[hsl(var(--text-muted))]">
            <Loader2 className="h-5 w-5 animate-spin" />
          </div>
        )}
        {!loading && error && (
          <div className="p-4 text-sm text-warning">{error}</div>
        )}
        {!loading && !error && rows.length === 0 && (
          <div className="p-6 text-center text-sm text-[hsl(var(--text-muted))]">
            {t("noResults")}
          </div>
        )}
        {!loading && !error && rows.length > 0 && (
          <table className="w-full text-sm">
            <thead className="bg-[hsl(var(--surface-2))] text-[10px] uppercase tracking-wide text-[hsl(var(--text-muted))]">
              <tr>
                <th className="px-3 py-2 text-left">{t("table.code")}</th>
                <th className="px-3 py-2 text-left">{t("table.name")}</th>
                <th className="px-3 py-2 text-left">{t("table.category")}</th>
                <th className="px-3 py-2 text-right">{t("table.risk")}</th>
                <th className="px-3 py-2 text-right">{t("table.oneMonth")}</th>
                <th className="px-3 py-2 text-right">{t("table.sixMonths")}</th>
                <th className="px-3 py-2 text-right">{t("table.oneYear")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr
                  key={r.code}
                  onClick={() => setSelected(r)}
                  className={cn(
                    "cursor-pointer border-t border-[hsl(var(--border))] transition hover:bg-[hsl(var(--surface-2))]",
                    selected?.code === r.code && "bg-accent-muted/40",
                  )}
                >
                  <td className="px-3 py-2 font-mono text-emerald-300">{r.code}</td>
                  <td className="px-3 py-2 truncate max-w-[20rem]">{r.title ?? "—"}</td>
                  <td className="px-3 py-2 truncate max-w-[14rem] text-[11px] text-[hsl(var(--text-muted))]">
                    {r.category?.replace(/\s*Şemsiye Fonu\s*$/i, "") ?? "—"}
                  </td>
                  <td className="px-3 py-2 text-right text-[hsl(var(--text-muted))]">{r.risk ?? "—"}</td>
                  <ReturnCell value={r.return_1m} />
                  <ReturnCell value={r.return_6m} />
                  <ReturnCell value={r.return_1y} />
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {selected && <FundDetailCard fund={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}

function FundDetailCard({ fund, onClose }: { fund: FundRow; onClose: () => void }) {
  const { t } = useTranslation("funds");
  const [days, setDays] = useState(90);
  const [points, setPoints] = useState<FundHistoryPoint[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fundHistory(fund.code, days)
      .then((p) => { if (!cancelled) setPoints(p); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [fund.code, days]);

  const stats = useMemo(() => {
    if (points.length < 2) return null;
    const first = points[0].price;
    const last = points[points.length - 1].price;
    if (!first) return null;
    const totalReturn = ((last - first) / first) * 100;
    const min = Math.min(...points.map((p) => p.price));
    const max = Math.max(...points.map((p) => p.price));
    return { totalReturn, min, max };
  }, [points]);

  const { niceDomain, niceTicks, formatTick } = useMemo(() => {
    if (!stats) {
      return { niceDomain: ["auto", "auto"] as [number | string, number | string], niceTicks: undefined as number[] | undefined, formatTick: (v: number) => v.toFixed(2) };
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

  return (
    <div className="card">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="font-mono text-lg text-emerald-300">{fund.code}</div>
          <div className="text-xs text-[hsl(var(--text-muted))] max-w-md">{fund.title}</div>
        </div>
        <div className="flex items-center gap-2">
          {[30, 90, 180, 365].map((d) => (
            <button
              key={d}
              onClick={() => setDays(d)}
              className={cn(
                "rounded-full border px-2.5 py-0.5 text-[10px] transition",
                days === d
                  ? "border-accent bg-accent-muted text-accent"
                  : "border-[hsl(var(--border))] text-[hsl(var(--text-muted))] hover:text-[hsl(var(--text))]",
              )}
            >
              {d}d
            </button>
          ))}
          <button
            onClick={onClose}
            className="rounded-full border border-[hsl(var(--border))] px-2.5 py-0.5 text-[10px] text-[hsl(var(--text-muted))] hover:text-[hsl(var(--text))]"
          >
            {t("close")}
          </button>
        </div>
      </div>

      {stats && (
        <div className="mt-2 flex gap-4 text-xs">
          <span>
            <span className="text-[hsl(var(--text-muted))]">{t("daysReturn", { days })} </span>
            <span className={cn("num font-semibold", stats.totalReturn >= 0 ? "text-gain" : "text-loss")}>
              {stats.totalReturn >= 0 ? "+" : ""}{stats.totalReturn.toFixed(2)}%
            </span>
          </span>
          <span className="text-[hsl(var(--text-muted))]">
            {t("minMax", { min: stats.min.toFixed(4), max: stats.max.toFixed(4) })}
          </span>
        </div>
      )}

      <div className="mt-3 h-64">
        {loading ? (
          <div className="flex h-full items-center justify-center text-[hsl(var(--text-muted))]">
            <Loader2 className="h-5 w-5 animate-spin" />
          </div>
        ) : points.length < 2 ? (
          <div className="flex h-full items-center justify-center text-xs text-[hsl(var(--text-muted))]">
            {t("noHistoricalData")}
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
                contentStyle={{ background: "hsl(var(--surface))", border: "1px solid hsl(var(--border))" }}
                labelStyle={{ color: "hsl(var(--text-muted))" }}
                formatter={(v: number) => [formatTick(v), "Price"]}
              />
              <Line
                type="monotone"
                dataKey="price"
                stroke="#14B8A6"
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
    </div>
  );
}
