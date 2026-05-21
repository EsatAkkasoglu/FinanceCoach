/**
 * Dashboard — at-a-glance overview wired to live backend data.
 *
 * Layout: a weighted 12-column bento.
 *   Row A — full-width live hero (greeting + today's $ delta).
 *   Row B — 3 metric cards: Net worth (sparkline), Cash flow (mini bars), Savings rate.
 *   Row C — Allocation vs target (drift), Top mover today, Goal progress ring.
 *   Row D — Holdings table w/ per-row sparklines, Daily brief.
 *   Then the coach's Next-Step CTA.
 */
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useLocation } from "react-router-dom";
import {
  TrendingUp, TrendingDown, Sparkles, AlertCircle, Flame, Newspaper, Coins,
  type LucideIcon,
  Loader2, ArrowUpRight, ArrowDownRight, PiggyBank,
  Info, ArrowRight, Wallet, Receipt, Target, Briefcase,
} from "lucide-react";
import {
  PieChart, Pie, Cell, ResponsiveContainer, Tooltip,
} from "recharts";

import {
  listPortfolio, getBriefing, getBudgetSummary, captureNetWorth, netWorthHistory,
  listAccounts, listGoals,
  type Holding, type PortfolioTotals, type BriefingItem, type BudgetSummary, type NetWorthPoint,
  type Goal,
} from "@/lib/api";
import { formatCurrency, formatPercent } from "@/lib/format";
import { useFxRates, type UseFxRates } from "@/lib/fx";
import { cn } from "@/lib/cn";
import { assetColor, pnlColor, chartTooltipContentStyle, chartTooltipItemStyle } from "@/lib/chartColors";
import { Sparkline, MiniBars, ProgressTrack, InsightLine, DonutRing } from "@/components/ui/dataviz";
import { useDashboardStore, useUserStore, useAuthStore } from "@/store";
import { AVATARS } from "@/components/onboarding/data";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { buildLocalizedPath, getLanguageFromPath } from "@/lib/routing";

const ICONS: Record<BriefingItem["icon"], LucideIcon> = {
  trending_up: TrendingUp,
  trending_down: TrendingDown,
  sparkles: Sparkles,
  alert_circle: AlertCircle,
  flame: Flame,
  newspaper: Newspaper,
  coins: Coins,
};

// Cache verisi 5 dakika taze kabul edilir
const STALE_MS = 5 * 60 * 1000;

// Target allocation by risk profile (equities vs defensive vs cash). Drives the
// "allocation vs target" drift card. equity_band only arrives via chat reasoning,
// so we use a simple, defensible mapping here as the source of truth.
const TARGET_ALLOC: Record<string, { equity: number; defensive: number; cash: number }> = {
  conservative: { equity: 35, defensive: 50, cash: 15 },
  balanced:     { equity: 60, defensive: 30, cash: 10 },
  aggressive:   { equity: 80, defensive: 15, cash: 5 },
};
// Map asset classes into the three target buckets.
const EQUITY_CLASSES = new Set(["stock", "etf", "crypto"]);
const DEFENSIVE_CLASSES = new Set(["bond"]);

function useGreeting(name: string) {
  const { t } = useTranslation("dashboard");
  return useMemo(() => {
    const h = new Date().getHours();
    const key = h < 12 ? "greeting.morning" : h < 18 ? "greeting.afternoon" : "greeting.evening";
    const salutation = t(key);
    return name ? `${salutation}, ${name}` : salutation;
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [name, t]);
}

const RISK_BADGE_CLS: Record<string, string> = {
  conservative: "bg-blue-500/15 text-blue-400",
  balanced:     "bg-accent/15 text-accent",
  aggressive:   "bg-orange-500/15 text-orange-400",
};

export function Dashboard() {
  const { t } = useTranslation("dashboard");
  const { cache, loading, setCache, setLoading } = useDashboardStore();
  const [error, setError] = useState<string | null>(null);
  const [budget, setBudget] = useState<BudgetSummary | null>(null);
  const [accountCount, setAccountCount] = useState<number | null>(null);
  const [goals, setGoals] = useState<Goal[]>([]);
  const [briefingFetchedAt, setBriefingFetchedAt] = useState<number | null>(null);

  const { name, avatar, riskProfile, riskScore, monthlyIncome } = useUserStore();
  const authUser = useAuthStore((s) => s.user);
  const avatarMeta = AVATARS.find((a) => a.id === avatar) ?? AVATARS[0];
  const greeting = useGreeting(name);
  const badgeCls = RISK_BADGE_CLS[riskProfile] ?? RISK_BADGE_CLS.balanced;
  const badgeLabel = t(`riskBadge.${riskProfile}`);
  const riskExplain = t(`riskExplanation.${riskProfile}`, { score: riskScore });

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
        const [p, b, budgetData, accounts, goalsData] = await Promise.all([
          listPortfolio(),
          getBriefing(),
          getBudgetSummary().catch(() => null),
          listAccounts().catch(() => []),
          listGoals().catch(() => []),
        ]);
        if (cancelled) return;
        setCache({ holdings: p.holdings, totals: p.totals, briefing: b.items, fetchedAt: Date.now() });
        setBudget(budgetData);
        setAccountCount(accounts.length);
        setGoals(goalsData);
        setBriefingFetchedAt(Date.now());

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

  // Compute totals for the next-step recommendation
  const hasIncome = useMemo(() => {
    if (!budget) return monthlyIncome > 0;
    return Object.values(budget.income_mtd).some((v) => v > 0) || monthlyIncome > 0;
  }, [budget, monthlyIncome]);
  const hasExpense = useMemo(() => {
    if (!budget) return false;
    return Object.values(budget.expense_mtd).some((v) => v > 0);
  }, [budget]);

  const isLoading = loading && !cache;

  return (
    <div>
      {/* Top bar — anchors page title vs page content */}
      <div className="mb-5 flex items-center justify-between border-b border-line pb-3">
        <span className="text-xs font-medium uppercase tracking-[0.14em] text-content-muted">
          {t("title")}
        </span>
        <RiskBadge cls={badgeCls} label={badgeLabel} explanation={riskExplain} title={t("riskExplanation.title")} />
      </div>

      {error && (
        <div className="mb-4 rounded-xl border border-loss/40 bg-loss/10 px-4 py-3 text-sm text-loss">
          {error}
        </div>
      )}

      {/* 12-column bento */}
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-12">
        {/* Row A — live hero */}
        <HeroStrip
          avatarEmoji={avatarMeta.emoji}
          greeting={greeting}
          totals={totals}
          holdings={holdings}
          budget={budget}
          badge={{ cls: badgeCls, label: badgeLabel }}
          fallbackSubtitle={t("todayAtAGlance")}
        />

        {/* Row B — metric cards */}
        <NetWorthCard totals={totals} holdings={holdings} history={history} loading={isLoading} />
        <CashFlowCard budget={budget} loading={isLoading} />
        <SavingsRateCard budget={budget} loading={isLoading} />

        {/* Row C — allocation drift / top mover / goal ring */}
        <AllocationCard holdings={holdings} riskProfile={riskProfile} loading={isLoading} />
        <TopMoverCard holdings={holdings} loading={isLoading} />
        <GoalCard goals={goals} loading={isLoading} />

        {/* Row D — holdings + brief */}
        <HoldingsTable holdings={holdings} loading={isLoading} />
        <BriefingCard items={briefing} loading={isLoading} fetchedAt={briefingFetchedAt} />
      </div>

      <NextStepCard
        loading={isLoading}
        hasOnboarded={authUser?.has_onboarded ?? false}
        accountCount={accountCount}
        hasIncome={hasIncome}
        hasExpense={hasExpense}
        goalCount={goals.length}
        holdingCount={holdings.length}
      />

      <Disclaimer className="mt-8 text-center" />
    </div>
  );
}

// ---------- Hero (live strip) ----------
function HeroStrip({
  avatarEmoji, greeting, totals, holdings, budget, badge, fallbackSubtitle,
}: {
  avatarEmoji: string;
  greeting: string;
  totals: PortfolioTotals | null;
  holdings: Holding[];
  budget: BudgetSummary | null;
  badge: { cls: string; label: string };
  fallbackSubtitle: string;
}) {
  const { t } = useTranslation("dashboard");
  const fx = useFxRates();
  const displayCcy = fx.rates ? fx.target : "USD";

  // Today's delta, summed in the display currency from per-position day_pnl.
  const { todayDelta, totalValue, hasDelta } = useMemo(() => {
    let value = 0;
    let delta = 0;
    let sawDelta = false;
    for (const h of holdings) {
      const ccy = h.currency ?? "USD";
      const hv = fx.rates ? (fx.convert(h.current_value ?? 0, ccy) ?? (h.current_value ?? 0)) : (h.current_value ?? 0);
      value += hv;
      if (typeof h.day_pnl === "number") {
        const dv = fx.rates ? (fx.convert(h.day_pnl, ccy) ?? h.day_pnl) : h.day_pnl;
        delta += dv;
        sawDelta = true;
      }
    }
    if (totals && value === 0) value = totals.value;
    return { todayDelta: delta, totalValue: value, hasDelta: sawDelta };
  }, [holdings, totals, fx]);

  const positive = todayDelta >= 0;
  const pct = totalValue > 0 ? (todayDelta / totalValue) * 100 : 0;

  // Savings rate (for the hero micro-stat).
  const savingsRate = useMemo(() => computeSavingsRate(budget, fx), [budget, fx]);

  return (
    <div className="lg:col-span-12">
      <div className="flex flex-wrap items-center gap-5 rounded-2xl border border-line bg-gradient-to-br from-surface-raised via-surface to-surface p-5">
        <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl bg-accent/20 text-3xl leading-none shadow-glow">
          {avatarEmoji}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h1 className="truncate text-[26px] font-semibold leading-tight tracking-tight">{greeting}</h1>
            <span className={cn("rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide", badge.cls)}>
              {badge.label}
            </span>
          </div>
          {totalValue > 0 ? (
            <p className="mt-1.5 flex flex-wrap items-baseline gap-x-2 text-sm text-content-muted">
              <span className="num font-medium text-content">{formatCurrency(totalValue, displayCcy)}</span>
              {hasDelta && todayDelta !== 0 && (
                <>
                  <span className="opacity-50">·</span>
                  <span className={cn("num font-medium", positive ? "text-gain" : "text-loss")}>
                    {positive ? "▲" : "▼"} {formatCurrency(Math.abs(todayDelta), displayCcy)} ({formatPercent(pct)}) {t("today")}
                  </span>
                </>
              )}
              {!hasDelta && <span>{fallbackSubtitle}</span>}
            </p>
          ) : (
            <p className="mt-1.5 text-sm text-content-muted">{fallbackSubtitle}</p>
          )}
        </div>
        {/* Hero micro-stats */}
        <div className="flex shrink-0 items-center gap-5">
          {savingsRate != null && (
            <HeroStat label={t("savingsRate")} value={formatPercent(savingsRate)} tone={savingsRate >= 0 ? "gain" : "loss"} />
          )}
          {totals && totals.count > 0 && (
            <HeroStat
              label={t("netWorth")}
              value={formatCurrency(totalValue, displayCcy)}
              tone="neutral"
            />
          )}
        </div>
      </div>
    </div>
  );
}

function HeroStat({ label, value, tone }: { label: string; value: string; tone: "gain" | "loss" | "neutral" }) {
  return (
    <div className="text-right">
      <div className="text-[10px] uppercase tracking-widest text-content-muted">{label}</div>
      <div className={cn("num text-sm font-semibold", tone === "gain" ? "text-gain" : tone === "loss" ? "text-loss" : "text-content")}>
        {value}
      </div>
    </div>
  );
}

// Shared: savings rate from budget summary (income & expense both required).
function computeSavingsRate(budget: BudgetSummary | null, fx: UseFxRates): number | null {
  if (!budget) return null;
  const income = fx.rates ? fx.convertBag(budget.income_mtd) : sumBag(budget.income_mtd);
  const expense = fx.rates ? fx.convertBag(budget.expense_mtd) : sumBag(budget.expense_mtd);
  if (income == null || income <= 0 || expense == null || expense <= 0) return null;
  return ((income - expense) / income) * 100;
}
function sumBag(bag: Record<string, number>): number {
  return Object.values(bag).reduce((a, b) => a + b, 0);
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
  const { t } = useTranslation("dashboard");
  const fx = useFxRates();
  const displayCcy = fx.rates ? fx.target : "USD";
  let value = totals?.value ?? 0;
  let pnl = totals?.pnl ?? 0;
  let pnlPct = totals?.pnl_pct ?? 0;
  if (fx.rates && totals && totals.count > 0) {
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
  const spark = history.map((h) => h.value);
  return (
    <div className="card lg:col-span-4">
      <div className="text-xs uppercase tracking-wide text-content-muted">{t("netWorth")}</div>
      {loading ? (
        <CardSpinner h="h-12" />
      ) : totals && totals.count > 0 ? (
        <>
          <div className="num mt-2 text-3xl font-semibold">{formatCurrency(value, displayCcy)}</div>
          <div className={cn("mt-1 text-sm", pnl >= 0 ? "text-gain" : "text-loss")}>
            {formatPercent(pnlPct)} ({formatCurrency(pnl, displayCcy)}) {t("allTime")}
          </div>
          {spark.length >= 2 ? (
            <div className="mt-3">
              <Sparkline values={spark} width={240} height={40} color={pnlColor(pnl)} className="w-full" />
              <p className="mt-1 text-[10px] text-content-muted">{t("lastNDays", { count: spark.length })}</p>
            </div>
          ) : (
            <BestWorstChips holdings={holdings} fx={fx} />
          )}
        </>
      ) : (
        <>
          <div className="num mt-2 text-3xl font-semibold">{formatCurrency(0, displayCcy)}</div>
          <div className="mt-1 text-xs text-content-muted">{t("noHoldings")}</div>
        </>
      )}
    </div>
  );
}

function BestWorstChips({ holdings, fx }: { holdings: Holding[]; fx: UseFxRates }) {
  const ranked = holdings
    .filter((h) => typeof h.change_today === "number")
    .sort((a, b) => (b.change_today ?? 0) - (a.change_today ?? 0));
  if (ranked.length === 0) return null;
  const best = ranked[0];
  const worst = ranked[ranked.length - 1];
  void fx;
  return (
    <div className="mt-3 flex flex-wrap gap-2 text-[11px]">
      <span className="inline-flex items-center gap-1 rounded-full bg-gain/10 px-2 py-0.5 text-gain">
        <TrendingUp className="h-3 w-3" /> {best.ticker} {formatPercent(best.change_today ?? 0)}
      </span>
      {worst !== best && (
        <span className="inline-flex items-center gap-1 rounded-full bg-loss/10 px-2 py-0.5 text-loss">
          <TrendingDown className="h-3 w-3" /> {worst.ticker} {formatPercent(worst.change_today ?? 0)}
        </span>
      )}
    </div>
  );
}

// ---------- Cash flow ----------
function CashFlowCard({ budget, loading }: { budget: BudgetSummary | null; loading: boolean }) {
  const { t } = useTranslation("dashboard");
  const fx = useFxRates();
  const displayCcy = fx.rates ? fx.target : "USD";

  const income = budget ? (fx.rates ? fx.convertBag(budget.income_mtd) : sumBag(budget.income_mtd)) : null;
  const expense = budget ? (fx.rates ? fx.convertBag(budget.expense_mtd) : sumBag(budget.expense_mtd)) : null;
  const net = income != null && expense != null ? income - expense : null;
  const hasFlow = (income ?? 0) > 0 || (expense ?? 0) > 0;

  return (
    <div className="card lg:col-span-4">
      <div className="text-xs uppercase tracking-wide text-content-muted">{t("cashFlow")}</div>
      {loading ? (
        <CardSpinner h="h-12" />
      ) : !hasFlow ? (
        <p className="mt-3 text-sm text-content-muted">{t("cashFlowEmpty")}</p>
      ) : (
        <>
          <div className={cn("num mt-2 text-3xl font-semibold", (net ?? 0) >= 0 ? "text-gain" : "text-loss")}>
            {net != null ? `${net >= 0 ? "+" : ""}${formatCurrency(net, displayCcy)}` : "—"}
          </div>
          <div className="mt-1 flex items-center gap-3 text-xs">
            <span className="flex items-center gap-1 text-gain"><ArrowUpRight className="h-3 w-3" />{income != null ? formatCurrency(income, displayCcy) : "—"}</span>
            <span className="flex items-center gap-1 text-loss"><ArrowDownRight className="h-3 w-3" />{expense != null ? formatCurrency(expense, displayCcy) : "—"}</span>
          </div>
          <div className="mt-3">
            <MiniBars
              values={[income ?? 0, expense ?? 0]}
              colorFor={(_, i) => (i === 0 ? "#22C55E" : "#EF4444")}
              className="h-9"
            />
          </div>
        </>
      )}
    </div>
  );
}

// ---------- Savings rate ----------
function SavingsRateCard({ budget, loading }: { budget: BudgetSummary | null; loading: boolean }) {
  const { t } = useTranslation("dashboard");
  const fx = useFxRates();
  const rate = useMemo(() => computeSavingsRate(budget, fx), [budget, fx]);

  return (
    <div className="card lg:col-span-4">
      <div className="text-xs uppercase tracking-wide text-content-muted">{t("savingsRate")}</div>
      {loading ? (
        <CardSpinner h="h-12" />
      ) : rate == null ? (
        <p className="mt-3 text-sm text-content-muted">{t("noBudgetData")}</p>
      ) : (
        <>
          <div className={cn("num mt-2 text-3xl font-semibold", rate >= 0 ? "text-gain" : "text-loss")}>
            {Math.round(rate)}%
          </div>
          <div className="mt-3 flex items-center gap-2">
            <PiggyBank className="h-4 w-4 shrink-0 text-accent" />
            <ProgressTrack pct={Math.max(0, rate)} />
          </div>
          <InsightLine tone={rate >= 20 ? "positive" : "neutral"}>
            {rate >= 20 ? "Strong saving this month." : "Room to push your savings higher."}
          </InsightLine>
        </>
      )}
    </div>
  );
}

// ---------- Allocation vs target ----------
function AllocationCard({
  holdings, riskProfile, loading,
}: { holdings: Holding[]; riskProfile: string; loading: boolean }) {
  const { t } = useTranslation("dashboard");
  const fx = useFxRates();
  const displayCcy = fx.rates ? fx.target : "USD";

  const convertedHoldings = holdings.map((h) => ({
    ...h,
    current_value: fx.rates
      ? (fx.convert(h.current_value ?? 0, h.currency ?? "USD") ?? (h.current_value ?? 0))
      : (h.current_value ?? 0),
  }));
  const data = aggregateByAssetClass(convertedHoldings);
  const hasData = data.length > 0;

  // Compute actual vs target by bucket.
  const total = data.reduce((a, b) => a + b.value, 0);
  const buckets = { equity: 0, defensive: 0, cash: 0 };
  for (const d of data) {
    if (EQUITY_CLASSES.has(d.name)) buckets.equity += d.value;
    else if (DEFENSIVE_CLASSES.has(d.name)) buckets.defensive += d.value;
    else buckets.cash += d.value;
  }
  const target = TARGET_ALLOC[riskProfile] ?? TARGET_ALLOC.balanced;
  const rows = (["equity", "defensive", "cash"] as const).map((k) => {
    const actual = total ? (buckets[k] / total) * 100 : 0;
    const drift = actual - target[k];
    return { key: k, actual, target: target[k], drift };
  });

  return (
    <div className="card lg:col-span-5">
      <div className="text-xs uppercase tracking-wide text-content-muted">{t("allocationVsTarget")}</div>
      {loading ? (
        <CardSpinner h="h-44" />
      ) : !hasData ? (
        <p className="mt-3 text-sm text-content-muted">{t("addHoldingsForBreakdown")}</p>
      ) : (
        <div className="mt-2 flex items-center gap-4">
          <div className="h-36 w-36 shrink-0">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={data} dataKey="value" innerRadius={42} outerRadius={64} paddingAngle={2} strokeWidth={0}>
                  {data.map((d) => (<Cell key={d.name} fill={assetColor(d.name)} />))}
                </Pie>
                <Tooltip
                  contentStyle={chartTooltipContentStyle}
                  formatter={(v: number, name: string) => [formatCurrency(v, displayCcy), name.charAt(0).toUpperCase() + name.slice(1)]}
                  labelFormatter={() => ""}
                  itemStyle={chartTooltipItemStyle}
                />
              </PieChart>
            </ResponsiveContainer>
          </div>
          <ul className="flex-1 space-y-2 text-xs">
            {rows.map((r) => {
              const onTarget = Math.abs(r.drift) < 3;
              const driftLabel = onTarget
                ? t("onTarget")
                : `${Math.abs(Math.round(r.drift))}% ${r.drift > 0 ? t("over") : t("under")}`;
              const tone = onTarget ? "text-gain" : r.drift > 0 ? "text-warning" : "text-loss";
              return (
                <li key={r.key} className="flex items-center justify-between">
                  <span className="capitalize text-content">{r.key}</span>
                  <span className="flex items-center gap-2">
                    <span className="num text-content-muted">{Math.round(r.actual)}%</span>
                    <span className={cn("num text-[10px]", tone)}>{driftLabel}</span>
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}

// ---------- Top mover today ----------
function TopMoverCard({ holdings, loading }: { holdings: Holding[]; loading: boolean }) {
  const { t } = useTranslation("dashboard");
  const fx = useFxRates();
  const displayCcy = fx.rates ? fx.target : "USD";

  const movers = holdings.filter((h) => typeof h.day_pnl === "number" && h.day_pnl !== 0);
  const totalAbs = movers.reduce((a, h) => a + Math.abs(h.day_pnl ?? 0), 0);
  const top = movers.slice().sort((a, b) => Math.abs(b.day_pnl ?? 0) - Math.abs(a.day_pnl ?? 0))[0];

  let dayPnl = top?.day_pnl ?? 0;
  if (top && fx.rates) dayPnl = fx.convert(top.day_pnl ?? 0, top.currency ?? "USD") ?? dayPnl;
  const share = top && totalAbs ? Math.round((Math.abs(top.day_pnl ?? 0) / totalAbs) * 100) : 0;
  const positive = (top?.change_today ?? 0) >= 0;

  return (
    <div className="card lg:col-span-4">
      <div className="text-xs uppercase tracking-wide text-content-muted">{t("topMover")}</div>
      {loading ? (
        <CardSpinner h="h-20" />
      ) : !top ? (
        <p className="mt-3 text-sm text-content-muted">{t("noMoverData")}</p>
      ) : (
        <>
          <div className="num mt-2 text-2xl font-semibold">{top.ticker}</div>
          <div className={cn("mt-1 text-sm", positive ? "text-gain" : "text-loss")}>
            {formatPercent(top.change_today ?? 0)} · {dayPnl >= 0 ? "+" : ""}{formatCurrency(dayPnl, displayCcy)}
          </div>
          <InsightLine tone={positive ? "positive" : "negative"} icon={<Flame className="h-3 w-3" />}>
            {t("topMoverShare", { pct: share })}
          </InsightLine>
        </>
      )}
    </div>
  );
}

// ---------- Goal progress ----------
function GoalCard({ goals, loading }: { goals: Goal[]; loading: boolean }) {
  const { t } = useTranslation("dashboard");
  const top = goals
    .map((g) => ({ g, pct: g.target_amount > 0 ? (g.current_amount / g.target_amount) * 100 : 0 }))
    .sort((a, b) => b.pct - a.pct)[0];

  const monthsLeft = top?.g.target_date
    ? Math.max(0, Math.round((new Date(top.g.target_date).getTime() - Date.now()) / (1000 * 60 * 60 * 24 * 30)))
    : null;

  return (
    <div className="card lg:col-span-3">
      <div className="text-xs uppercase tracking-wide text-content-muted">{t("goalProgress")}</div>
      {loading ? (
        <CardSpinner h="h-20" />
      ) : !top ? (
        <p className="mt-3 text-sm text-content-muted">{t("goalNoGoals")}</p>
      ) : (
        <div className="mt-2 flex items-center gap-3">
          <DonutRing pct={top.pct} color="#8B5CF6" size={64} stroke={9}>
            <span className="num text-sm font-semibold">{Math.round(top.pct)}%</span>
          </DonutRing>
          <div className="min-w-0">
            <p className="truncate text-sm font-medium">{top.g.title}</p>
            <p className="text-[11px] text-content-muted">
              {t("goalOnPace")}{monthsLeft != null ? ` · ${t("monthsLeft", { count: monthsLeft })}` : ""}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

// ---------- Briefing ----------
function BriefingCard({
  items, loading, fetchedAt,
}: {
  items: BriefingItem[] | null;
  loading: boolean;
  fetchedAt: number | null;
}) {
  const { t } = useTranslation("dashboard");
  const [, setTick] = useState(0);
  useEffect(() => {
    if (!fetchedAt) return;
    const id = setInterval(() => setTick((n) => n + 1), 60_000);
    return () => clearInterval(id);
  }, [fetchedAt]);

  function relativeTime(): string {
    if (!fetchedAt) return "";
    const minutes = Math.floor((Date.now() - fetchedAt) / 60_000);
    if (minutes < 1) return t("addedJustNow");
    return t("addedMinutesAgo", { count: minutes });
  }

  return (
    <div className="card lg:col-span-5 flex flex-col">
      <div className="text-xs uppercase tracking-wide text-content-muted">{t("todaysBrief")}</div>
      {loading ? (
        <CardSpinner h="h-16" />
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
                  <span className="text-content-muted mr-1">{it.label}:</span>
                  <span>{it.text}</span>
                </div>
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="mt-3 text-sm text-content-muted">{t("briefUnavailable")}</p>
      )}
      {fetchedAt && (
        <div className="mt-auto flex items-center justify-between pt-3 text-[10px] text-content-muted">
          <span className="truncate">{t("briefSource")}</span>
          <span className="shrink-0 pl-2">{t("briefUpdated", { time: relativeTime() })}</span>
        </div>
      )}
    </div>
  );
}

// ---------- Risk Badge (with hover explanation) ----------
function RiskBadge({
  cls, label, explanation, title,
}: {
  cls: string;
  label: string;
  explanation: string;
  title: string;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="relative">
      <button
        type="button"
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "flex items-center gap-1 rounded-full px-2.5 py-1 text-[10px] font-medium uppercase tracking-wide transition",
          cls
        )}
      >
        <span>{label}</span>
        <Info className="h-3 w-3 opacity-70" />
      </button>
      {open && (
        <div className="absolute right-0 top-full z-30 mt-2 w-72 rounded-xl border border-line bg-surface p-3 text-left shadow-2xl">
          <p className="mb-1 text-[10px] font-semibold uppercase tracking-widest text-content-muted">
            {title}
          </p>
          <p className="text-xs leading-relaxed text-content">{explanation}</p>
        </div>
      )}
    </div>
  );
}

// ---------- Next Step Card (coach's call-to-action) ----------
type StepKind = "onboarding" | "account" | "income" | "expense" | "goal" | "holding";

interface NextStepProps {
  loading: boolean;
  hasOnboarded: boolean;
  accountCount: number | null;
  hasIncome: boolean;
  hasExpense: boolean;
  goalCount: number | null;
  holdingCount: number;
}

function NextStepCard({
  loading, hasOnboarded, accountCount, hasIncome, hasExpense, goalCount, holdingCount,
}: NextStepProps) {
  const { t } = useTranslation("dashboard");
  const navigate = useNavigate();
  const location = useLocation();
  const lang = getLanguageFromPath(location.pathname) ?? "en";

  const steps: { kind: StepKind; done: boolean }[] = [
    { kind: "onboarding", done: hasOnboarded },
    { kind: "account",    done: (accountCount ?? 0) > 0 },
    { kind: "income",     done: hasIncome },
    { kind: "expense",    done: hasExpense },
    { kind: "goal",       done: (goalCount ?? 0) > 0 },
    { kind: "holding",    done: holdingCount > 0 },
  ];
  const completedCount = steps.filter((s) => s.done).length;
  const pct = Math.round((completedCount / steps.length) * 100);
  const next = steps.find((s) => !s.done);

  const META: Record<StepKind, {
    title: string; desc: string; cta: string;
    Icon: LucideIcon; path: string;
  }> = {
    onboarding: { title: t("nextStep.completeOnboarding"), desc: t("nextStep.completeOnboardingDesc"), cta: t("nextStep.completeOnboarding"), Icon: Sparkles, path: "/dashboard" },
    account:    { title: t("nextStep.addAccount"),    desc: t("nextStep.addAccountDesc"),    cta: t("nextStep.ctaAccount"),   Icon: Wallet,    path: "/budget" },
    income:     { title: t("nextStep.addIncome"),     desc: t("nextStep.addIncomeDesc"),     cta: t("nextStep.ctaIncome"),    Icon: ArrowUpRight, path: "/budget" },
    expense:    { title: t("nextStep.addExpense"),    desc: t("nextStep.addExpenseDesc"),    cta: t("nextStep.ctaExpense"),   Icon: Receipt,   path: "/budget" },
    goal:       { title: t("nextStep.addGoal"),       desc: t("nextStep.addGoalDesc"),       cta: t("nextStep.ctaGoal"),      Icon: Target,    path: "/goals" },
    holding:    { title: t("nextStep.addHolding"),    desc: t("nextStep.addHoldingDesc"),    cta: t("nextStep.ctaHolding"),   Icon: Briefcase, path: "/portfolio" },
  };

  if (loading) return null;

  const allDone = !next;
  const meta = next ? META[next.kind] : null;

  return (
    <div className="mt-4 overflow-hidden rounded-2xl border border-accent/30 bg-gradient-to-br from-accent/10 via-accent/5 to-transparent p-5">
      <div className="flex flex-col items-start gap-4 md:flex-row md:items-center">
        <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl bg-accent/20 shadow-glow">
          {allDone ? (
            <Sparkles className="h-6 w-6 text-accent" />
          ) : meta ? (
            <meta.Icon className="h-6 w-6 text-accent" />
          ) : null}
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="text-[10px] font-semibold uppercase tracking-widest text-accent">
              {t("nextStep.title")}
            </span>
            <span className="text-[10px] text-content-muted">·</span>
            <span className="text-[10px] text-content-muted">
              {t("nextStep.subtitle")}
            </span>
          </div>
          <h3 className="mt-1 text-lg font-semibold tracking-tight">
            {allDone ? t("nextStep.allDone") : meta?.title}
          </h3>
          <p className="mt-1 text-sm text-content-muted">
            {allDone ? t("nextStep.allDoneDesc") : meta?.desc}
          </p>

          <div className="mt-3 flex items-center gap-3">
            <div className="grid h-1.5 flex-1 grid-cols-20 gap-[2px] overflow-hidden rounded-full bg-surface-raised p-[1px]">
              {Array.from({ length: 20 }, (_, index) => (
                <span
                  key={index}
                  className={cn(
                    "rounded-full transition-colors duration-500",
                    index < Math.ceil((pct / 100) * 20) ? "bg-accent" : "bg-surface-raised",
                  )}
                />
              ))}
            </div>
            <span className="shrink-0 text-[10px] font-medium text-content-muted">
              {completedCount}/{steps.length} · {pct}% {t("profileCompletion.complete")}
            </span>
          </div>
        </div>

        {!allDone && meta && (
          <button
            type="button"
            onClick={() => navigate(buildLocalizedPath(lang, meta.path))}
            className="flex shrink-0 items-center gap-2 rounded-xl bg-accent px-4 py-2.5 text-sm font-medium text-white shadow-glow transition hover:bg-accent/90 active:scale-95"
          >
            {meta.cta}
            <ArrowRight className="h-4 w-4" />
          </button>
        )}
      </div>
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
  const { t } = useTranslation("dashboard");
  const fx = useFxRates();
  function fmt(v: number, h: Holding) {
    const native = h.currency ?? "USD";
    if (!fx.rates) return formatCurrency(v, native);
    const conv = fx.convert(v, native);
    return conv == null ? formatCurrency(v, native) : formatCurrency(conv, fx.target);
  }
  return (
    <div className="card lg:col-span-7">
      <div className="text-xs uppercase tracking-wide text-content-muted">{t("holdings")}</div>
      {loading ? (
        <CardSpinner h="h-32" />
      ) : holdings.length === 0 ? (
        <p className="mt-3 text-sm text-content-muted">{t("noHoldingsDesc")}</p>
      ) : (
        <div className="mt-3 overflow-x-auto">
          <table className="num min-w-full text-sm">
            <thead className="text-xs uppercase tracking-wide text-content-muted">
              <tr className="border-b border-line">
                <th className="py-3 pr-4 text-left font-normal">{t("table.ticker")}</th>
                <th className="py-3 pr-4 text-right font-normal">{t("table.qty")}</th>
                <th className="py-3 pr-4 text-right font-normal">{t("table.price")}</th>
                <th className="py-3 pr-4 text-right font-normal">{t("table.value")}</th>
                <th className="py-3 pr-3 text-center font-normal">{t("today")}</th>
                <th className="py-3 text-right font-normal">{t("table.pnl")}</th>
              </tr>
            </thead>
            <tbody>
              {holdings.map((h) => {
                const dayUp = (h.change_today ?? 0) >= 0;
                return (
                  <tr key={h.ticker} className="border-b border-line last:border-0">
                    <td className="py-3 pr-4 font-semibold">{h.ticker}</td>
                    <td className="py-3 pr-4 text-right">{h.quantity}</td>
                    <td className="py-3 pr-4 text-right">{fmt(h.current_price ?? h.cost_basis, h)}</td>
                    <td className="py-3 pr-4 text-right">{fmt(h.current_value ?? 0, h)}</td>
                    <td className="py-3 pr-3">
                      <div className="flex items-center justify-center gap-1.5">
                        {typeof h.change_today === "number" ? (
                          <>
                            <Sparkline
                              values={dayUp ? [0, 0.4, 0.3, 1] : [1, 0.6, 0.7, 0]}
                              width={36}
                              height={12}
                              color={dayUp ? "#22C55E" : "#EF4444"}
                            />
                            <span className={cn("text-[11px]", dayUp ? "text-gain" : "text-loss")}>
                              {formatPercent(h.change_today)}
                            </span>
                          </>
                        ) : (
                          <span className="text-[11px] text-content-muted">—</span>
                        )}
                      </div>
                    </td>
                    <td className={cn(
                      "py-3 text-right font-medium",
                      (h.pnl ?? 0) >= 0 ? "text-gain" : "text-loss"
                    )}>
                      {formatPercent(h.pnl_pct ?? 0)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function CardSpinner({ h }: { h: string }) {
  return (
    <div className={cn("mt-2 flex items-center", h)}>
      <Loader2 className="h-5 w-5 animate-spin text-content-muted" />
    </div>
  );
}
