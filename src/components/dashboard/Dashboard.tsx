/**
 * Dashboard — at-a-glance overview wired to live backend data.
 *
 * Sections:
 *   - Net Worth card: sum of holdings (incl. cash) with day P&L
 *   - Daily Brief card: 3 dynamic items from /briefing
 *   - Portfolio Donut: allocation by asset class
 *   - Holdings table: per-position P&L
 */
import { useEffect, useState } from "react";
import {
  TrendingUp, TrendingDown, Sparkles, AlertCircle, type LucideIcon,
  Loader2,
} from "lucide-react";
import {
  PieChart, Pie, Cell, ResponsiveContainer, Tooltip,
} from "recharts";

import { listPortfolio, getBriefing, type Holding, type PortfolioTotals, type BriefingItem } from "@/lib/api";
import { formatCurrency, formatPercent } from "@/lib/format";
import { useFxRates } from "@/lib/fx";
import { cn } from "@/lib/cn";
import { useDashboardStore } from "@/store";

const ICONS: Record<BriefingItem["icon"], LucideIcon> = {
  trending_up: TrendingUp,
  trending_down: TrendingDown,
  sparkles: Sparkles,
  alert_circle: AlertCircle,
};

const ASSET_COLORS: Record<string, string> = {
  stock: "#1FB57A",
  etf: "#3FCB95",
  crypto: "#F59E0B",
  bond: "#3B82F6",
  cash: "#9CA3AF",
};

// Cache verisi 5 dakika taze kabul edilir
const STALE_MS = 5 * 60 * 1000;

export function Dashboard() {
  const { cache, loading, setCache, setLoading } = useDashboardStore();
  const [error, setError] = useState<string | null>(null);

  const holdings = cache?.holdings ?? [];
  const totals = cache?.totals ?? null;
  const briefing = cache?.briefing ?? null;

  useEffect(() => {
    // Cache tazeyse fetch etme (stale-while-revalidate: cache varsa göster, eski ise arka planda güncelle)
    if (cache && Date.now() - cache.fetchedAt < STALE_MS) return;
    if (loading) return;

    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const [p, b] = await Promise.all([listPortfolio(), getBriefing()]);
        if (cancelled) return;
        setCache({ holdings: p.holdings, totals: p.totals, briefing: b.items, fetchedAt: Date.now() });
      } catch (err) {
        if (!cancelled) setError((err as Error).message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => { cancelled = true; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div>
      <div className="mb-8">
        <h1 className="text-2xl font-semibold tracking-tight">Dashboard</h1>
        <p className="text-sm text-[hsl(var(--text-muted))]">Today at a glance</p>
      </div>

      {error && (
        <div className="mb-6 rounded-xl border border-loss/40 bg-loss/10 px-4 py-3 text-sm text-loss">
          {error}
        </div>
      )}

      {/* Sadece hiç veri yokken spinner göster; cache varsa stale olsa bile direkt render et */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <NetWorthCard totals={totals} holdings={holdings} loading={loading && !cache} />
        <BriefingCard items={briefing} loading={loading && !cache} />
        <PortfolioCard holdings={holdings} loading={loading && !cache} />
        <HoldingsTable holdings={holdings} loading={loading && !cache} />
      </div>
    </div>
  );
}

// ---------- Net Worth ----------
function NetWorthCard({
  totals, holdings, loading,
}: {
  totals: PortfolioTotals | null;
  holdings: Holding[];
  loading: boolean;
}) {
  const fx = useFxRates();
  let value = totals?.value ?? 0;
  let pnl = totals?.pnl ?? 0;
  let pnlPct = totals?.pnl_pct ?? 0;
  let displayCcy = "USD";
  if (fx.rates && totals && totals.count > 0) {
    displayCcy = fx.target;
    let v = 0, c = 0;
    for (const h of holdings) {
      const ccy = h.currency ?? "USD";
      const hv = fx.convert(h.current_value ?? 0, ccy);
      const hc = fx.convert(h.cost_total ?? (h.cost_basis * h.quantity), ccy);
      if (hv != null) v += hv;
      if (hc != null) c += hc;
    }
    value = v;
    pnl = v - c;
    pnlPct = c > 0 ? (pnl / c) * 100 : 0;
  }
  return (
    <div className="card lg:col-span-1">
      <div className="text-xs uppercase tracking-wide text-[hsl(var(--text-muted))]">Net worth</div>
      {loading ? (
        <div className="mt-2 flex h-12 items-center">
          <Loader2 className="h-5 w-5 animate-spin text-[hsl(var(--text-muted))]" />
        </div>
      ) : totals && totals.count > 0 ? (
        <>
          <div className="num mt-2 text-3xl font-semibold">{formatCurrency(value, displayCcy)}</div>
          <div className={cn("mt-1 text-sm", pnl >= 0 ? "text-gain" : "text-loss")}>
            {formatPercent(pnlPct)} ({formatCurrency(pnl, displayCcy)}) all-time
          </div>
        </>
      ) : (
        <>
          <div className="num mt-2 text-3xl font-semibold">{formatCurrency(0, displayCcy)}</div>
          <div className="mt-1 text-xs text-[hsl(var(--text-muted))]">
            No holdings yet — add some from the Portfolio tab
          </div>
        </>
      )}
    </div>
  );
}

// ---------- Briefing ----------
function BriefingCard({ items, loading }: { items: BriefingItem[] | null; loading: boolean }) {
  return (
    <div className="card lg:col-span-2">
      <div className="text-xs uppercase tracking-wide text-[hsl(var(--text-muted))]">Today's brief</div>
      {loading ? (
        <div className="mt-3 flex h-16 items-center">
          <Loader2 className="h-5 w-5 animate-spin text-[hsl(var(--text-muted))]" />
        </div>
      ) : items && items.length > 0 ? (
        <ul className="mt-3 space-y-3">
          {items.map((it, i) => {
            const Icon = ICONS[it.icon] ?? Sparkles;
            const tone =
              it.tone === "positive" ? "text-gain" :
              it.tone === "negative" ? "text-loss" :
              it.tone === "warning"  ? "text-warning" :
              "text-accent";
            return (
              <li key={i} className="flex items-start gap-3 text-sm">
                <Icon className={cn("mt-0.5 h-4 w-4 shrink-0", tone)} />
                <div>
                  <span className="text-[hsl(var(--text-muted))] mr-1">{it.label}:</span>
                  <span>{it.text}</span>
                </div>
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="mt-3 text-sm text-[hsl(var(--text-muted))]">Brief unavailable right now.</p>
      )}
    </div>
  );
}

// ---------- Portfolio donut ----------
function PortfolioCard({ holdings, loading }: { holdings: Holding[]; loading: boolean }) {
  const fx = useFxRates();
  const displayCcy = fx.rates ? fx.target : "USD";
  // Convert each holding's value into the display currency before aggregating.
  const convertedHoldings = holdings.map((h) => ({
    ...h,
    current_value: fx.rates
      ? (fx.convert(h.current_value ?? 0, h.currency ?? "USD") ?? (h.current_value ?? 0))
      : (h.current_value ?? 0),
  }));
  const data = aggregateByAssetClass(convertedHoldings);
  const hasData = data.length > 0;
  return (
    <div className="card lg:col-span-1">
      <div className="text-xs uppercase tracking-wide text-[hsl(var(--text-muted))]">Allocation</div>
      {loading ? (
        <div className="mt-3 flex h-44 items-center justify-center">
          <Loader2 className="h-5 w-5 animate-spin text-[hsl(var(--text-muted))]" />
        </div>
      ) : !hasData ? (
        <p className="mt-3 text-sm text-[hsl(var(--text-muted))]">Add holdings to see breakdown.</p>
      ) : (
        <div className="mt-2 h-44">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={data}
                dataKey="value"
                innerRadius={45}
                outerRadius={70}
                paddingAngle={2}
                strokeWidth={0}
              >
                {data.map((d) => (
                  <Cell key={d.name} fill={ASSET_COLORS[d.name] ?? "#666"} />
                ))}
              </Pie>
              <Tooltip
                contentStyle={{
                  background: "hsl(224 14% 9%)",
                  border: "1px solid hsl(224 14% 18%)",
                  borderRadius: 8,
                  fontSize: 12,
                }}
                formatter={(v: number) => formatCurrency(v, displayCcy)}
              />
            </PieChart>
          </ResponsiveContainer>
        </div>
      )}
      {hasData && (
        <ul className="mt-3 space-y-1 text-xs">
          {data.map((d) => (
            <li key={d.name} className="flex items-center justify-between">
              <span className="flex items-center gap-2 capitalize">
                <span
                  className="inline-block h-2 w-2 rounded-full"
                  style={{ background: ASSET_COLORS[d.name] ?? "#666" }}
                />
                {d.name}
              </span>
              <span className="num text-[hsl(var(--text-muted))]">{formatCurrency(d.value, displayCcy)}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function aggregateByAssetClass(holdings: Holding[]): { name: string; value: number }[] {
  const m = new Map<string, number>();
  for (const h of holdings) {
    const v = h.current_value ?? (h.quantity * h.cost_basis);
    m.set(h.asset_class, (m.get(h.asset_class) ?? 0) + v);
  }
  return Array.from(m, ([name, value]) => ({ name, value })).sort((a, b) => b.value - a.value);
}

// ---------- Holdings table ----------
function HoldingsTable({ holdings, loading }: { holdings: Holding[]; loading: boolean }) {
  const fx = useFxRates();
  function fmt(v: number, h: Holding) {
    const native = h.currency ?? "USD";
    if (!fx.rates) return formatCurrency(v, native);
    const conv = fx.convert(v, native);
    return conv == null ? formatCurrency(v, native) : formatCurrency(conv, fx.target);
  }
  return (
    <div className="card lg:col-span-2">
      <div className="text-xs uppercase tracking-wide text-[hsl(var(--text-muted))]">Holdings</div>
      {loading ? (
        <div className="mt-3 flex h-32 items-center">
          <Loader2 className="h-5 w-5 animate-spin text-[hsl(var(--text-muted))]" />
        </div>
      ) : holdings.length === 0 ? (
        <p className="mt-3 text-sm text-[hsl(var(--text-muted))]">
          No holdings yet. Add from the Portfolio tab to see live valuations.
        </p>
      ) : (
        <div className="mt-3 overflow-x-auto">
          <table className="num min-w-full text-xs">
            <thead className="text-[hsl(var(--text-muted))]">
              <tr className="border-b border-[hsl(var(--border))]">
                <th className="py-2 pr-4 text-left font-normal">Ticker</th>
                <th className="py-2 pr-4 text-right font-normal">Qty</th>
                <th className="py-2 pr-4 text-right font-normal">Price</th>
                <th className="py-2 pr-4 text-right font-normal">Value</th>
                <th className="py-2 text-right font-normal">P&L</th>
              </tr>
            </thead>
            <tbody>
              {holdings.map((h) => (
                <tr key={h.ticker} className="border-b border-[hsl(var(--border))] last:border-0">
                  <td className="py-2 pr-4 font-semibold">{h.ticker}</td>
                  <td className="py-2 pr-4 text-right">{h.quantity}</td>
                  <td className="py-2 pr-4 text-right">{fmt(h.current_price ?? h.cost_basis, h)}</td>
                  <td className="py-2 pr-4 text-right">{fmt(h.current_value ?? 0, h)}</td>
                  <td className={cn(
                    "py-2 text-right",
                    (h.pnl ?? 0) >= 0 ? "text-gain" : "text-loss"
                  )}>
                    {formatPercent(h.pnl_pct ?? 0)}
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
