/**
 * Dashboard — at-a-glance overview wired to live backend data.
 *
 * Sections:
 *   - Personalized hero header: greeting + avatar + risk badge
 *   - Net Worth card: sum of holdings (incl. cash) with all-time P&L
 *   - Budget snapshot: income vs expense MTD + savings rate
 *   - Daily Brief card: 3 dynamic items from /briefing
 *   - Portfolio Donut: allocation by asset class
 *   - Holdings table: per-position P&L
 */
import { useEffect, useMemo, useState } from "react";
import {
  TrendingUp, TrendingDown, Sparkles, AlertCircle, Flame, Newspaper, Coins,
  type LucideIcon,
  Loader2, ArrowUpRight, ArrowDownRight, PiggyBank,
} from "lucide-react";
import {
  PieChart, Pie, Cell, ResponsiveContainer, Tooltip,
  LineChart, Line, XAxis, YAxis,
} from "recharts";

import { listPortfolio, getBriefing, getBudgetSummary, captureNetWorth, netWorthHistory, type Holding, type PortfolioTotals, type BriefingItem, type BudgetSummary, type NetWorthPoint } from "@/lib/api";
import { formatCurrency, formatPercent } from "@/lib/format";
import { useFxRates } from "@/lib/fx";
import { cn } from "@/lib/cn";
import { useDashboardStore, useUserStore } from "@/store";
import { AVATARS } from "@/components/onboarding/data";
import { Disclaimer } from "@/components/ui/Disclaimer";

const ICONS: Record<BriefingItem["icon"], LucideIcon> = {
  trending_up: TrendingUp,
  trending_down: TrendingDown,
  sparkles: Sparkles,
  alert_circle: AlertCircle,
  flame: Flame,
  newspaper: Newspaper,
  coins: Coins,
};

const ASSET_COLORS: Record<string, string> = {
  stock: "#14B8A6",   // teal — non-brand so it doesn't read as interactive
  etf: "#8B5CF6",     // violet — was #3FCB95, too close to stock green
  crypto: "#F59E0B",  // amber
  bond: "#3B82F6",    // blue
  cash: "#9CA3AF",    // gray
};

// Cache verisi 5 dakika taze kabul edilir
const STALE_MS = 5 * 60 * 1000;

function useGreeting(name: string) {
  return useMemo(() => {
    const h = new Date().getHours();
    const salutation = h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
    return name ? `${salutation}, ${name}` : salutation;
  }, [name]);
}

const RISK_BADGE: Record<string, { label: string; cls: string }> = {
  conservative: { label: "Conservative", cls: "bg-blue-500/15 text-blue-400" },
  balanced:     { label: "Balanced",     cls: "bg-accent/15 text-accent" },
  aggressive:   { label: "Aggressive",   cls: "bg-orange-500/15 text-orange-400" },
};

export function Dashboard() {
  const { cache, loading, setCache, setLoading } = useDashboardStore();
  const [error, setError] = useState<string | null>(null);
  const [budget, setBudget] = useState<BudgetSummary | null>(null);

  const { name, avatar, riskProfile } = useUserStore();
  const avatarMeta = AVATARS.find((a) => a.id === avatar) ?? AVATARS[0];
  const greeting = useGreeting(name);
  const badge = RISK_BADGE[riskProfile] ?? RISK_BADGE.balanced;

  const holdings = cache?.holdings ?? [];
  const totals = cache?.totals ?? null;
  const briefing = cache?.briefing ?? null;
  const [history, setHistory] = useState<NetWorthPoint[]>([]);

  useEffect(() => {
    if (cache && Date.now() - cache.fetchedAt < STALE_MS) return;
    if (loading) return;

    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const [p, b, budgetData] = await Promise.all([
          listPortfolio(),
          getBriefing(),
          getBudgetSummary().catch(() => null),
        ]);
        if (cancelled) return;
        setCache({ holdings: p.holdings, totals: p.totals, briefing: b.items, fetchedAt: Date.now() });
        setBudget(budgetData);

        // Capture today's net-worth snapshot (idempotent) + load 30-day history.
        if (p.totals && p.totals.count > 0) {
          captureNetWorth(p.totals.value, "USD").catch(() => {});
        }
        netWorthHistory(30).then((pts) => { if (!cancelled) setHistory(pts); }).catch(() => {});
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
      {/* Top bar — anchors page title vs page content */}
      <div className="mb-6 flex items-center justify-between border-b border-[hsl(var(--border))] pb-3">
        <span className="text-xs font-medium uppercase tracking-[0.14em] text-[hsl(var(--text-muted))]">
          Dashboard
        </span>
        <span className={cn("rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide", badge.cls)}>
          {badge.label}
        </span>
      </div>

      {/* Personalized hero header */}
      <div className="mb-10 flex items-center gap-5">
        <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-accent/20 text-3xl leading-none shadow-glow shrink-0">
          {avatarMeta.emoji}
        </div>
        <div className="flex-1 min-w-0">
          <h1 className="text-[32px] font-semibold leading-tight tracking-tight truncate">{greeting}</h1>
          <p className="mt-2 text-sm text-[hsl(var(--text-muted))]">Today at a glance</p>
        </div>
      </div>

      {error && (
        <div className="mb-6 rounded-xl border border-loss/40 bg-loss/10 px-4 py-3 text-sm text-loss">
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-6">
        <NetWorthCard totals={totals} holdings={holdings} history={history} loading={loading && !cache} />
        <BudgetSnapshotCard budget={budget} loading={loading && !cache} />
        <BriefingCard items={briefing} loading={loading && !cache} />
        <PortfolioCard holdings={holdings} loading={loading && !cache} />
        <HoldingsTable holdings={holdings} loading={loading && !cache} />
      </div>

      <Disclaimer className="mt-8 text-center" />
    </div>
  );
}

// ---------- Net Worth ----------
function NetWorthCard({
  totals, holdings, history, loading,
}: {
  totals: PortfolioTotals | null;
  holdings: Holding[];
  history: NetWorthPoint[];
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
    <div className="card lg:col-span-2">
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
          {history.length >= 2 && (
            <div className="mt-3 h-12">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={history}>
                  <XAxis dataKey="date" hide />
                  <YAxis domain={["dataMin", "dataMax"]} hide />
                  <Line
                    type="monotone"
                    dataKey="value"
                    stroke={pnl >= 0 ? "#10B981" : "#EF4444"}
                    strokeWidth={1.5}
                    dot={false}
                    isAnimationActive={false}
                  />
                </LineChart>
              </ResponsiveContainer>
              <p className="text-[10px] text-[hsl(var(--text-muted))]">
                Last {history.length} days
              </p>
            </div>
          )}
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

// ---------- Budget Snapshot ----------
function BudgetSnapshotCard({ budget, loading }: { budget: BudgetSummary | null; loading: boolean }) {
  const fx = useFxRates();
  const { monthlyIncome } = useUserStore();

  const totalIncome = useMemo(() => {
    if (!budget) return null;
    return Object.entries(budget.income_mtd).reduce((sum, [ccy, v]) => {
      const conv = fx.rates ? (fx.convert(v, ccy) ?? v) : v;
      return sum + conv;
    }, 0);
  }, [budget, fx]);

  const totalExpense = useMemo(() => {
    if (!budget) return null;
    return Object.entries(budget.expense_mtd).reduce((sum, [ccy, v]) => {
      const conv = fx.rates ? (fx.convert(v, ccy) ?? v) : v;
      return sum + conv;
    }, 0);
  }, [budget, fx]);

  const displayCcy = fx.rates ? fx.target : "USD";

  // Savings rate: (income - expense) / income, or fall back to onboarding monthlyIncome
  const savingsRate = useMemo(() => {
    if (totalIncome != null && totalIncome > 0 && totalExpense != null) {
      return ((totalIncome - totalExpense) / totalIncome) * 100;
    }
    if (monthlyIncome > 0 && totalExpense != null) {
      const inc = fx.rates ? (fx.convert(monthlyIncome, "USD") ?? monthlyIncome) : monthlyIncome;
      return ((inc - totalExpense) / inc) * 100;
    }
    return null;
  }, [totalIncome, totalExpense, monthlyIncome, fx]);

  return (
    <div className="card lg:col-span-2">
      <div className="text-xs uppercase tracking-wide text-[hsl(var(--text-muted))]">This month</div>
      {loading ? (
        <div className="mt-2 flex h-12 items-center">
          <Loader2 className="h-5 w-5 animate-spin text-[hsl(var(--text-muted))]" />
        </div>
      ) : budget == null ? (
        <p className="mt-3 text-sm text-[hsl(var(--text-muted))]">No budget data yet — add transactions.</p>
      ) : (
        <div className="mt-3 space-y-2">
          <div className="flex items-center justify-between text-sm">
            <span className="flex items-center gap-1.5 text-[hsl(var(--text-muted))]">
              <ArrowUpRight className="h-3.5 w-3.5 text-gain" />
              Income
            </span>
            <span className="num font-medium text-gain">
              {totalIncome != null ? formatCurrency(totalIncome, displayCcy) : "—"}
            </span>
          </div>
          <div className="flex items-center justify-between text-sm">
            <span className="flex items-center gap-1.5 text-[hsl(var(--text-muted))]">
              <ArrowDownRight className="h-3.5 w-3.5 text-loss" />
              Expenses
            </span>
            <span className="num font-medium text-loss">
              {totalExpense != null ? formatCurrency(totalExpense, displayCcy) : "—"}
            </span>
          </div>
          {savingsRate != null && (
            <div className="flex items-center justify-between border-t border-[hsl(var(--border))] pt-2 text-sm">
              <span className="flex items-center gap-1.5 text-[hsl(var(--text-muted))]">
                <PiggyBank className="h-3.5 w-3.5 text-accent" />
                Savings rate
              </span>
              <span className={cn("num font-semibold", savingsRate >= 0 ? "text-gain" : "text-loss")}>
                {formatPercent(savingsRate)}
              </span>
            </div>
          )}
        </div>
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
    <div className="card lg:col-span-2">
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
                formatter={(v: number, name: string) => [
                  formatCurrency(v, displayCcy),
                  name.charAt(0).toUpperCase() + name.slice(1),
                ]}
                labelFormatter={() => ""}
                separator=": "
                itemStyle={{ color: "hsl(var(--text))" }}
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
    <div className="card lg:col-span-4">
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
          <table className="num min-w-full text-sm">
            <thead className="text-xs uppercase tracking-wide text-[hsl(var(--text-muted))]">
              <tr className="border-b border-[hsl(var(--border))]">
                <th className="py-3 pr-4 text-left font-normal">Ticker</th>
                <th className="py-3 pr-4 text-right font-normal">Qty</th>
                <th className="py-3 pr-4 text-right font-normal">Price</th>
                <th className="py-3 pr-4 text-right font-normal">Value</th>
                <th className="py-3 text-right font-normal">P&L</th>
              </tr>
            </thead>
            <tbody>
              {holdings.map((h) => (
                <tr key={h.ticker} className="border-b border-[hsl(var(--border))] last:border-0">
                  <td className="py-3 pr-4 font-semibold">{h.ticker}</td>
                  <td className="py-3 pr-4 text-right">{h.quantity}</td>
                  <td className="py-3 pr-4 text-right">{fmt(h.current_price ?? h.cost_basis, h)}</td>
                  <td className="py-3 pr-4 text-right">{fmt(h.current_value ?? 0, h)}</td>
                  <td className={cn(
                    "py-3 text-right font-medium",
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
