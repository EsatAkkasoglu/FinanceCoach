/**
 * Dashboard — at-a-glance financial overview.
 *
 * UX improvements over v1:
 * - Framer Motion stagger entrance: cards animate in sequentially
 * - Skeleton cards: shimmer placeholders matching each card's shape
 * - CountUp: net worth number counts up on first load
 * - Hero redesign: net worth is the primary visual element
 * - Market status indicator (US market open/pre/post/closed)
 * - Holdings table: asset-class color indicator, row hover, better empty state
 * - Briefing card: left-border tone coding per insight item
 * - Card hover: subtle accent glow on hover
 * - Progressive feel: skeletons reveal before data, cards animate in individually
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useLocation } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import {
  TrendingUp, TrendingDown, Sparkles, AlertCircle, Flame, Newspaper, Coins,
  type LucideIcon,
  ArrowUpRight, ArrowDownRight, PiggyBank,
  Info, ArrowRight, Wallet, Receipt, Target, Briefcase, Activity,
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
import { Sparkline, MiniBars, InsightLine, DonutRing } from "@/components/ui/dataviz";
import { useDashboardStore, useUserStore, useAuthStore } from "@/store";
import { AVATARS } from "@/components/onboarding/data";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { buildLocalizedPath, getLanguageFromPath } from "@/lib/routing";

// ── Constants ─────────────────────────────────────────────────────────────────

const ICONS: Record<BriefingItem["icon"], LucideIcon> = {
  trending_up: TrendingUp, trending_down: TrendingDown, sparkles: Sparkles,
  alert_circle: AlertCircle, flame: Flame, newspaper: Newspaper, coins: Coins,
};

const STALE_MS = 5 * 60 * 1000;

const TARGET_ALLOC: Record<string, { equity: number; defensive: number; cash: number }> = {
  conservative: { equity: 35, defensive: 50, cash: 15 },
  balanced:     { equity: 60, defensive: 30, cash: 10 },
  aggressive:   { equity: 80, defensive: 15, cash: 5 },
};
const EQUITY_CLASSES = new Set(["stock", "etf", "crypto"]);
const DEFENSIVE_CLASSES = new Set(["bond"]);

const RISK_BADGE_CLS: Record<string, string> = {
  conservative: "bg-blue-500/15 text-blue-400 border-blue-500/20",
  balanced:     "bg-accent/15 text-accent border-accent/20",
  aggressive:   "bg-orange-500/15 text-orange-400 border-orange-500/20",
};

// ── Animation variants ────────────────────────────────────────────────────────

const CARD_VAR = {
  hidden:  { opacity: 0, y: 18, scale: 0.99 },
  visible: { opacity: 1, y: 0,  scale: 1,
    transition: { duration: 0.38, ease: [0.4, 0, 0.2, 1] } },
};

// ── Hooks ─────────────────────────────────────────────────────────────────────

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

function useCountUp(target: number, duration = 960) {
  const [val, setVal] = useState(0);
  const ran = useRef(false);
  useEffect(() => {
    if (target === 0 || ran.current) { setVal(target); return; }
    ran.current = true;
    const t0 = performance.now();
    let raf: number;
    function frame(now: number) {
      const progress = Math.min((now - t0) / duration, 1);
      const ease = 1 - (1 - progress) ** 3;
      setVal(target * ease);
      if (progress < 1) raf = requestAnimationFrame(frame);
      else setVal(target);
    }
    raf = requestAnimationFrame(frame);
    return () => cancelAnimationFrame(raf);
  }, [target, duration]);
  return target === 0 ? 0 : val;
}

function useMarketStatus(): "open" | "pre" | "post" | "closed" {
  const [status, setStatus] = useState<"open" | "pre" | "post" | "closed">("closed");
  useEffect(() => {
    function compute() {
      const ny = new Date(new Date().toLocaleString("en-US", { timeZone: "America/New_York" }));
      const day = ny.getDay();
      const mins = ny.getHours() * 60 + ny.getMinutes();
      if (day === 0 || day === 6) return "closed";
      if (mins >= 570 && mins < 960)  return "open";
      if (mins >= 480 && mins < 570)  return "pre";
      if (mins >= 960 && mins < 1200) return "post";
      return "closed";
    }
    setStatus(compute());
    const id = setInterval(() => setStatus(compute()), 60_000);
    return () => clearInterval(id);
  }, []);
  return status;
}

// ── Skeleton shimmer ──────────────────────────────────────────────────────────

function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded-lg bg-surface-raised", className)} />;
}

function SkeletonCard({ lines = 3, hasBar = false }: { lines?: number; hasBar?: boolean }) {
  return (
    <div className="mt-3 space-y-2.5">
      <Skeleton className="h-8 w-2/3" />
      {Array.from({ length: lines - 1 }).map((_, i) => (
        <Skeleton key={i} className={`h-3 ${i === 0 ? "w-full" : "w-1/2"}`} />
      ))}
      {hasBar && <Skeleton className="mt-1 h-2 w-full" />}
    </div>
  );
}

// ── Shared helpers ────────────────────────────────────────────────────────────

function computeSavingsRate(budget: BudgetSummary | null, fx: UseFxRates): number | null {
  if (!budget) return null;
  const income  = fx.rates ? fx.convertBag(budget.income_mtd)  : sumBag(budget.income_mtd);
  const expense = fx.rates ? fx.convertBag(budget.expense_mtd) : sumBag(budget.expense_mtd);
  if (income == null || income <= 0 || expense == null || expense <= 0) return null;
  return ((income - expense) / income) * 100;
}
function sumBag(bag: Record<string, number>): number {
  return Object.values(bag).reduce((a, b) => a + b, 0);
}
function aggregateByAssetClass(holdings: Holding[]): { name: string; value: number }[] {
  const m = new Map<string, number>();
  for (const h of holdings) {
    const v = h.current_value ?? (h.quantity * h.cost_basis);
    m.set(h.asset_class, (m.get(h.asset_class) ?? 0) + v);
  }
  return Array.from(m, ([name, value]) => ({ name, value })).sort((a, b) => b.value - a.value);
}

// ── Card header component ─────────────────────────────────────────────────────

function CardHeader({ icon: Icon, label, iconColor = "text-content-muted" }: {
  icon?: React.ElementType;
  label: string;
  iconColor?: string;
}) {
  return (
    <div className="flex items-center gap-1.5">
      {Icon && <Icon className={cn("h-3.5 w-3.5 shrink-0", iconColor)} />}
      <span className="text-xs uppercase tracking-wide text-content-muted">{label}</span>
    </div>
  );
}

// ── Market status badge ───────────────────────────────────────────────────────

function MarketBadge() {
  const status = useMarketStatus();
  const { t } = useTranslation("dashboard");
  // Static lookup to satisfy i18n strict typing
  const MARKET_LABELS = {
    open:   { dot: "bg-gain shadow-[0_0_6px_rgba(34,197,94,0.7)] animate-pulse", label: t("marketOpen"),   cls: "text-gain"          },
    pre:    { dot: "bg-warning",                                                   label: t("marketPre"),    cls: "text-warning"       },
    post:   { dot: "bg-yellow-600",                                                label: t("marketPost"),   cls: "text-yellow-500"    },
    closed: { dot: "bg-content-muted/40",                                          label: t("marketClosed"), cls: "text-content-muted" },
  } satisfies Record<string, { dot: string; label: string; cls: string }>;
  const config = MARKET_LABELS[status];
  return (
    <div className={cn("flex items-center gap-1.5 text-[10px] font-medium", config.cls)}>
      <span className={cn("h-1.5 w-1.5 rounded-full", config.dot)} />
      {config.label}
    </div>
  );
}

// ── Dashboard ─────────────────────────────────────────────────────────────────

export function Dashboard() {
  const { t } = useTranslation("dashboard");
  const { cache, loading, setCache, setLoading } = useDashboardStore();
  const [error, setError] = useState<string | null>(null);
  const [budget, setBudget] = useState<BudgetSummary | null>(null);
  const [accountCount, setAccountCount] = useState<number | null>(null);
  const [goals, setGoals] = useState<Goal[]>([]);
  const [briefingFetchedAt, setBriefingFetchedAt] = useState<number | null>(null);
  const [history, setHistory] = useState<NetWorthPoint[]>([]);

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

  useEffect(() => {
    if (cache && Date.now() - cache.fetchedAt < STALE_MS) return;
    if (loading) return;
    let cancelled = false;
    async function load() {
      setLoading(true); setError(null);
      try {
        const [p, b, budgetData, accounts, goalsData] = await Promise.all([
          listPortfolio(), getBriefing(),
          getBudgetSummary().catch(() => null),
          listAccounts().catch(() => []),
          listGoals().catch(() => []),
        ]);
        if (cancelled) return;
        setCache({ holdings: p.holdings, totals: p.totals, briefing: b.items, fetchedAt: Date.now() });
        setBudget(budgetData); setAccountCount(accounts.length);
        setGoals(goalsData); setBriefingFetchedAt(Date.now());
        if (p.totals?.count && p.totals.count > 0) captureNetWorth(p.totals.value, "USD").catch(() => {});
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
      {/* Top bar */}
      <div className="mb-5 flex items-center justify-between border-b border-line pb-3">
        <span className="text-xs font-medium uppercase tracking-[0.14em] text-content-muted">
          {t("title")}
        </span>
        <RiskBadge cls={badgeCls} label={badgeLabel} explanation={riskExplain} title={t("riskExplanation.title")} />
      </div>

      {/* Error */}
      <AnimatePresence>
        {error && (
          <motion.div
            initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
            className="mb-4 rounded-xl border border-loss/40 bg-loss/10 px-4 py-3 text-sm text-loss"
          >
            {error}
          </motion.div>
        )}
      </AnimatePresence>

      {/* Bento grid */}
      <motion.div
        className="grid grid-cols-1 gap-3 lg:grid-cols-12"
        variants={{ visible: { transition: { staggerChildren: 0.07, delayChildren: 0.05 } } }}
        initial="hidden"
        animate="visible"
      >
        {/* Row A — Hero */}
        <HeroStrip
          avatarEmoji={avatarMeta.emoji}
          greeting={greeting}
          totals={totals}
          holdings={holdings}
          budget={budget}
          badge={{ cls: badgeCls, label: badgeLabel }}
          fallbackSubtitle={t("todayAtAGlance")}
          loading={isLoading}
        />

        {/* Row B — Metric cards */}
        <NetWorthCard totals={totals} holdings={holdings} history={history} loading={isLoading} />
        <CashFlowCard budget={budget} loading={isLoading} />
        <SavingsRateCard budget={budget} loading={isLoading} />

        {/* Row C */}
        <AllocationCard holdings={holdings} riskProfile={riskProfile} loading={isLoading} />
        <TopMoverCard holdings={holdings} loading={isLoading} />
        <GoalCard goals={goals} loading={isLoading} />

        {/* Row D */}
        <HoldingsTable holdings={holdings} loading={isLoading} />
        <BriefingCard items={briefing} loading={isLoading} fetchedAt={briefingFetchedAt} />
      </motion.div>

      {/* Next step CTA */}
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

// ── Hero strip ────────────────────────────────────────────────────────────────

function HeroStrip({
  avatarEmoji, greeting, totals, holdings, budget, badge, fallbackSubtitle, loading,
}: {
  avatarEmoji: string; greeting: string; totals: PortfolioTotals | null;
  holdings: Holding[]; budget: BudgetSummary | null;
  badge: { cls: string; label: string }; fallbackSubtitle: string; loading: boolean;
}) {
  const { t } = useTranslation("dashboard");
  const fx = useFxRates();
  const displayCcy = fx.rates ? fx.target : "USD";

  const { todayDelta, totalValue, hasDelta } = useMemo(() => {
    let value = 0, delta = 0, sawDelta = false;
    for (const h of holdings) {
      const ccy = h.currency ?? "USD";
      const hv = fx.rates ? (fx.convert(h.current_value ?? 0, ccy) ?? (h.current_value ?? 0)) : (h.current_value ?? 0);
      value += hv;
      if (typeof h.day_pnl === "number") {
        const dv = fx.rates ? (fx.convert(h.day_pnl, ccy) ?? h.day_pnl) : h.day_pnl;
        delta += dv; sawDelta = true;
      }
    }
    if (totals && value === 0) value = totals.value;
    return { todayDelta: delta, totalValue: value, hasDelta: sawDelta };
  }, [holdings, totals, fx]);

  const positive = todayDelta >= 0;
  const pct = totalValue > 0 ? (todayDelta / totalValue) * 100 : 0;
  const savingsRate = useMemo(() => computeSavingsRate(budget, fx), [budget, fx]);
  const countedValue = useCountUp(totalValue);

  return (
    <motion.div variants={CARD_VAR} className="lg:col-span-12">
      <div className="relative overflow-hidden rounded-2xl border border-line bg-gradient-to-br from-surface-raised via-surface to-surface p-5">
        {/* Subtle grid pattern */}
        <div
          className="pointer-events-none absolute inset-0 opacity-[0.03]"
          style={{
            backgroundImage: "linear-gradient(rgba(255,255,255,.5) 1px,transparent 1px), linear-gradient(90deg,rgba(255,255,255,.5) 1px,transparent 1px)",
            backgroundSize: "32px 32px",
          }}
        />

        <div className="relative flex flex-wrap items-center gap-5">
          {/* Avatar + greeting */}
          <div className="flex items-center gap-4 min-w-0 flex-1">
            <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl bg-accent/20 text-3xl leading-none shadow-glow">
              {avatarEmoji}
            </div>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="text-lg font-semibold leading-tight tracking-tight text-content-muted">
                  {greeting}
                </h1>
                <span className={cn("rounded-full border px-2.5 py-0.5 text-[10px] font-medium uppercase tracking-wide", badge.cls)}>
                  {badge.label}
                </span>
              </div>
              <MarketBadge />
            </div>
          </div>

          {/* Big net worth (primary visual element) */}
          <div className="flex flex-col items-end gap-1">
            {loading ? (
              <SkeletonCard lines={2} />
            ) : totalValue > 0 ? (
              <>
                <p className="text-[10px] uppercase tracking-widest text-content-muted">{t("netWorth")}</p>
                <p className="num text-3xl font-bold tracking-tight">
                  {formatCurrency(countedValue, displayCcy)}
                </p>
                {hasDelta && todayDelta !== 0 && (
                  <div className={cn(
                    "flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-sm font-medium",
                    positive ? "bg-gain/10 text-gain" : "bg-loss/10 text-loss",
                  )}>
                    {positive ? <TrendingUp className="h-3.5 w-3.5" /> : <TrendingDown className="h-3.5 w-3.5" />}
                    <span className="num">{positive ? "+" : ""}{formatCurrency(todayDelta, displayCcy)}</span>
                    <span className="num opacity-70">({formatPercent(pct)})</span>
                    <span className="text-[10px] opacity-60">{t("today")}</span>
                  </div>
                )}
                {!hasDelta && <p className="text-sm text-content-muted">{fallbackSubtitle}</p>}
              </>
            ) : (
              <p className="text-sm text-content-muted">{fallbackSubtitle}</p>
            )}
          </div>

          {/* Savings rate quick stat */}
          {savingsRate != null && (
            <div className="flex flex-col items-end">
              <p className="text-[10px] uppercase tracking-widest text-content-muted">{t("savingsRate")}</p>
              <p className={cn("num text-2xl font-bold", savingsRate >= 0 ? "text-gain" : "text-loss")}>
                {Math.round(savingsRate)}%
              </p>
              <p className="text-[10px] text-content-muted">{t("thisMonth")}</p>
            </div>
          )}
        </div>
      </div>
    </motion.div>
  );
}

// ── Net Worth card ────────────────────────────────────────────────────────────

function NetWorthCard({ totals, holdings, history, loading }: {
  totals: PortfolioTotals | null; holdings: Holding[];
  history: NetWorthPoint[]; loading: boolean;
}) {
  const { t } = useTranslation("dashboard");
  const fx = useFxRates();
  const displayCcy = fx.rates ? fx.target : "USD";
  let value = totals?.value ?? 0, pnl = totals?.pnl ?? 0, pnlPct = totals?.pnl_pct ?? 0;
  if (fx.rates && totals?.count && totals.count > 0) {
    let v = 0, c = 0;
    for (const h of holdings) {
      const ccy = h.currency ?? "USD";
      const hv = fx.convert(h.current_value ?? 0, ccy);
      const hc = fx.convert(h.cost_total ?? (h.cost_basis * h.quantity), ccy);
      if (hv != null) v += hv; if (hc != null) c += hc;
    }
    value = v; pnl = v - c; pnlPct = c > 0 ? (pnl / c) * 100 : 0;
  }
  const countedValue = useCountUp(value);
  const spark = history.map((h) => h.value);

  return (
    <motion.div variants={CARD_VAR} className="card lg:col-span-4 hover:shadow-[0_0_0_1px_rgba(31,181,122,0.15),0_8px_24px_rgba(0,0,0,0.2)] transition-shadow">
      <CardHeader icon={Activity} label={t("netWorth")} iconColor="text-accent" />
      {loading ? <SkeletonCard lines={3} hasBar /> : totals?.count && totals.count > 0 ? (
        <>
          <div className="num mt-2 text-3xl font-semibold">{formatCurrency(countedValue, displayCcy)}</div>
          <div className={cn("mt-1 text-sm", pnl >= 0 ? "text-gain" : "text-loss")}>
            {formatPercent(pnlPct)} ({pnl >= 0 ? "+" : ""}{formatCurrency(pnl, displayCcy)}) {t("allTime")}
          </div>
          {spark.length >= 2 ? (
            <div className="mt-3">
              <Sparkline values={spark} width={240} height={40} color={pnlColor(pnl)} className="w-full" />
              <p className="mt-1 text-[10px] text-content-muted">{t("lastNDays", { count: spark.length })}</p>
            </div>
          ) : <BestWorstChips holdings={holdings} fx={fx} />}
        </>
      ) : (
        <div className="mt-4 flex flex-col items-center py-4 text-center">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-surface-raised">
            <Briefcase className="h-5 w-5 text-content-muted" />
          </div>
          <p className="mt-2 text-sm text-content-muted">{t("noHoldings")}</p>
          <p className="mt-0.5 text-[11px] text-content-muted/60">{t("addHoldingsHint")}</p>
        </div>
      )}
    </motion.div>
  );
}

function BestWorstChips({ holdings, fx }: { holdings: Holding[]; fx: UseFxRates }) {
  void fx;
  const ranked = holdings.filter((h) => typeof h.change_today === "number")
    .sort((a, b) => (b.change_today ?? 0) - (a.change_today ?? 0));
  if (ranked.length === 0) return null;
  const best = ranked[0], worst = ranked[ranked.length - 1];
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

// ── Cash Flow card ────────────────────────────────────────────────────────────

function CashFlowCard({ budget, loading }: { budget: BudgetSummary | null; loading: boolean }) {
  const { t } = useTranslation("dashboard");
  const fx = useFxRates();
  const displayCcy = fx.rates ? fx.target : "USD";
  const income  = budget ? (fx.rates ? fx.convertBag(budget.income_mtd)  : sumBag(budget.income_mtd))  : null;
  const expense = budget ? (fx.rates ? fx.convertBag(budget.expense_mtd) : sumBag(budget.expense_mtd)) : null;
  const net = income != null && expense != null ? income - expense : null;
  const hasFlow = (income ?? 0) > 0 || (expense ?? 0) > 0;

  return (
    <motion.div variants={CARD_VAR} className="card lg:col-span-4 hover:shadow-[0_0_0_1px_rgba(31,181,122,0.15),0_8px_24px_rgba(0,0,0,0.2)] transition-shadow">
      <CardHeader icon={Wallet} label={t("cashFlow")} iconColor="text-accent" />
      {loading ? <SkeletonCard lines={3} hasBar /> : !hasFlow ? (
        <p className="mt-3 text-sm text-content-muted">{t("cashFlowEmpty")}</p>
      ) : (
        <>
          <div className={cn("num mt-2 text-3xl font-semibold", (net ?? 0) >= 0 ? "text-gain" : "text-loss")}>
            {net != null ? `${net >= 0 ? "+" : ""}${formatCurrency(net, displayCcy)}` : "—"}
          </div>
          <div className="mt-2 grid grid-cols-2 gap-2 text-xs">
            <div className="flex items-center gap-1.5 rounded-lg bg-gain/8 px-2.5 py-1.5 text-gain">
              <ArrowUpRight className="h-3 w-3 shrink-0" />
              <span className="num">{income != null ? formatCurrency(income, displayCcy) : "—"}</span>
            </div>
            <div className="flex items-center gap-1.5 rounded-lg bg-loss/8 px-2.5 py-1.5 text-loss">
              <ArrowDownRight className="h-3 w-3 shrink-0" />
              <span className="num">{expense != null ? formatCurrency(expense, displayCcy) : "—"}</span>
            </div>
          </div>
          <div className="mt-3">
            <MiniBars values={[income ?? 0, expense ?? 0]} colorFor={(_, i) => (i === 0 ? "#22C55E" : "#EF4444")} className="h-9" />
          </div>
        </>
      )}
    </motion.div>
  );
}

// ── Savings Rate card ─────────────────────────────────────────────────────────

function SavingsRateCard({ budget, loading }: { budget: BudgetSummary | null; loading: boolean }) {
  const { t } = useTranslation("dashboard");
  const fx = useFxRates();
  const rate = useMemo(() => computeSavingsRate(budget, fx), [budget, fx]);
  const counted = useCountUp(rate ?? 0);

  return (
    <motion.div variants={CARD_VAR} className="card lg:col-span-4 hover:shadow-[0_0_0_1px_rgba(31,181,122,0.15),0_8px_24px_rgba(0,0,0,0.2)] transition-shadow">
      <CardHeader icon={PiggyBank} label={t("savingsRate")} iconColor="text-accent" />
      {loading ? <SkeletonCard lines={3} hasBar /> : rate == null ? (
        <p className="mt-3 text-sm text-content-muted">{t("noBudgetData")}</p>
      ) : (
        <>
          <div className={cn("num mt-2 text-3xl font-semibold", rate >= 0 ? "text-gain" : "text-loss")}>
            {Math.round(counted)}%
          </div>
          {/* Visual rate bar */}
          <div className="mt-3">
            <div className="flex items-center justify-between text-[10px] text-content-muted mb-1">
              <span>0%</span>
              <span className={rate >= 20 ? "text-gain font-medium" : ""}>20% {t("savingsTarget")}</span>
              <span>100%</span>
            </div>
            <div className="relative h-2 overflow-hidden rounded-full bg-surface-raised">
              <motion.div
                className={cn("h-full rounded-full", rate >= 20 ? "bg-gain" : "bg-warning")}
                initial={{ width: 0 }}
                animate={{ width: `${Math.max(0, Math.min(100, rate))}%` }}
                transition={{ duration: 0.9, ease: "easeOut", delay: 0.3 }}
              />
              {/* 20% marker */}
              <div className="absolute top-0 bottom-0 w-px bg-content-muted/30" style={{ left: "20%" }} />
            </div>
          </div>
          <InsightLine tone={rate >= 20 ? "positive" : "neutral"}>
            {rate >= 20 ? t("savingsStrong") : t("savingsLow")}
          </InsightLine>
        </>
      )}
    </motion.div>
  );
}

// ── Allocation card ───────────────────────────────────────────────────────────

function AllocationCard({ holdings, riskProfile, loading }: {
  holdings: Holding[]; riskProfile: string; loading: boolean;
}) {
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
    <motion.div variants={CARD_VAR} className="card lg:col-span-5 hover:shadow-[0_0_0_1px_rgba(31,181,122,0.15),0_8px_24px_rgba(0,0,0,0.2)] transition-shadow">
      <CardHeader icon={Target} label={t("allocationVsTarget")} iconColor="text-accent" />
      {loading ? <SkeletonCard lines={4} /> : !hasData ? (
        <p className="mt-3 text-sm text-content-muted">{t("addHoldingsForBreakdown")}</p>
      ) : (
        <div className="mt-3 flex items-center gap-4">
          <div className="h-36 w-36 shrink-0">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={data} dataKey="value" innerRadius={42} outerRadius={64} paddingAngle={2} strokeWidth={0}>
                  {data.map((d) => <Cell key={d.name} fill={assetColor(d.name)} />)}
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
          <ul className="flex-1 space-y-3 text-xs">
            {rows.map((r) => {
              const onTarget = Math.abs(r.drift) < 3;
              const driftLabel = onTarget ? t("onTarget") : `${Math.abs(Math.round(r.drift))}% ${r.drift > 0 ? t("over") : t("under")}`;
              const tone = onTarget ? "text-gain" : r.drift > 0 ? "text-warning" : "text-loss";
              return (
                <li key={r.key}>
                  <div className="flex items-center justify-between mb-1">
                    <span className="capitalize text-content font-medium">{r.key}</span>
                    <span className={cn("text-[10px] font-medium", tone)}>{driftLabel}</span>
                  </div>
                  <div className="relative h-1 overflow-hidden rounded-full bg-surface-raised">
                    <div className="absolute h-full rounded-full bg-content-muted/20" style={{ width: `${r.target}%` }} />
                    <motion.div
                      className={cn("absolute h-full rounded-full", onTarget ? "bg-gain" : r.drift > 0 ? "bg-warning" : "bg-loss")}
                      initial={{ width: 0 }}
                      animate={{ width: `${r.actual}%` }}
                      transition={{ duration: 0.8, ease: "easeOut", delay: 0.2 }}
                    />
                  </div>
                  <div className="mt-0.5 flex justify-between text-[9px] text-content-muted">
                    <span>{Math.round(r.actual)}% actual</span>
                    <span>{r.target}% target</span>
                  </div>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </motion.div>
  );
}

// ── Top Mover card ────────────────────────────────────────────────────────────

function TopMoverCard({ holdings, loading }: { holdings: Holding[]; loading: boolean }) {
  const { t } = useTranslation("dashboard");
  const fx = useFxRates();
  const displayCcy = fx.rates ? fx.target : "USD";
  const movers = holdings.filter((h) => typeof h.day_pnl === "number" && h.day_pnl !== 0);
  const totalAbs = movers.reduce((a, h) => a + Math.abs(h.day_pnl ?? 0), 0);
  const top = movers.sort((a, b) => Math.abs(b.day_pnl ?? 0) - Math.abs(a.day_pnl ?? 0))[0];
  let dayPnl = top?.day_pnl ?? 0;
  if (top && fx.rates) dayPnl = fx.convert(top.day_pnl ?? 0, top.currency ?? "USD") ?? dayPnl;
  const share = top && totalAbs ? Math.round((Math.abs(top.day_pnl ?? 0) / totalAbs) * 100) : 0;
  const positive = (top?.change_today ?? 0) >= 0;

  return (
    <motion.div variants={CARD_VAR} className="card lg:col-span-4 hover:shadow-[0_0_0_1px_rgba(31,181,122,0.15),0_8px_24px_rgba(0,0,0,0.2)] transition-shadow">
      <CardHeader icon={Flame} label={t("topMover")} iconColor="text-warning" />
      {loading ? <SkeletonCard lines={3} /> : !top ? (
        <p className="mt-3 text-sm text-content-muted">{t("noMoverData")}</p>
      ) : (
        <>
          <div className="mt-3 flex items-start gap-3">
            {/* Asset class dot */}
            <div
              className="mt-1 h-10 w-1 rounded-full"
              style={{ backgroundColor: assetColor(top.asset_class) }}
            />
            <div>
              <div className="flex items-baseline gap-2">
                <span className="num text-2xl font-bold">{top.ticker}</span>
                <span className={cn("num text-sm font-medium", positive ? "text-gain" : "text-loss")}>
                  {formatPercent(top.change_today ?? 0)}
                </span>
              </div>
              <p className={cn("mt-0.5 num text-sm", positive ? "text-gain" : "text-loss")}>
                {dayPnl >= 0 ? "+" : ""}{formatCurrency(dayPnl, displayCcy)} {t("today")}
              </p>
            </div>
          </div>
          <InsightLine tone={positive ? "positive" : "negative"} icon={<Flame className="h-3 w-3" />}>
            {t("topMoverShare", { pct: share })}
          </InsightLine>
        </>
      )}
    </motion.div>
  );
}

// ── Goal progress card ────────────────────────────────────────────────────────

function GoalCard({ goals, loading }: { goals: Goal[]; loading: boolean }) {
  const { t } = useTranslation("dashboard");
  const ranked = goals
    .map((g) => ({ g, pct: g.target_amount > 0 ? (g.current_amount / g.target_amount) * 100 : 0 }))
    .sort((a, b) => b.pct - a.pct);
  const top = ranked[0];
  const monthsLeft = top?.g.target_date
    ? Math.max(0, Math.round((new Date(top.g.target_date).getTime() - Date.now()) / (1000 * 60 * 60 * 24 * 30)))
    : null;

  return (
    <motion.div variants={CARD_VAR} className="card lg:col-span-3 hover:shadow-[0_0_0_1px_rgba(31,181,122,0.15),0_8px_24px_rgba(0,0,0,0.2)] transition-shadow">
      <CardHeader icon={Target} label={t("goalProgress")} iconColor="text-purple-400" />
      {loading ? <SkeletonCard lines={2} /> : !top ? (
        <p className="mt-3 text-sm text-content-muted">{t("goalNoGoals")}</p>
      ) : (
        <>
          <div className="mt-3 flex items-center gap-3">
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
          {/* Show second goal if available */}
          {ranked.length > 1 && (
            <div className="mt-3 border-t border-line pt-2.5">
              <div className="flex items-center justify-between text-[11px]">
                <span className="truncate text-content-muted">{ranked[1].g.title}</span>
                <span className="num ml-2 shrink-0 text-content-muted">{Math.round(ranked[1].pct)}%</span>
              </div>
              <div className="mt-1 h-1 overflow-hidden rounded-full bg-surface-raised">
                <motion.div
                  className="h-full rounded-full bg-purple-500/60"
                  initial={{ width: 0 }}
                  animate={{ width: `${ranked[1].pct}%` }}
                  transition={{ duration: 0.8, ease: "easeOut", delay: 0.4 }}
                />
              </div>
            </div>
          )}
        </>
      )}
    </motion.div>
  );
}

// ── Holdings table ────────────────────────────────────────────────────────────

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
    <motion.div variants={CARD_VAR} className="card lg:col-span-7 hover:shadow-[0_0_0_1px_rgba(31,181,122,0.15),0_8px_24px_rgba(0,0,0,0.2)] transition-shadow">
      <CardHeader icon={Briefcase} label={t("holdings")} iconColor="text-accent" />
      {loading ? <SkeletonCard lines={5} /> : holdings.length === 0 ? (
        <div className="mt-4 flex flex-col items-center py-6 text-center">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-surface-raised">
            <Briefcase className="h-5 w-5 text-content-muted" />
          </div>
          <p className="mt-2 text-sm text-content-muted">{t("noHoldingsDesc")}</p>
        </div>
      ) : (
        <div className="mt-3 overflow-x-auto">
          <table className="num min-w-full text-sm">
            <thead className="text-xs uppercase tracking-wide text-content-muted">
              <tr className="border-b border-line">
                <th className="py-2.5 pr-4 text-left font-normal">{t("table.ticker")}</th>
                <th className="py-2.5 pr-4 text-right font-normal">{t("table.qty")}</th>
                <th className="py-2.5 pr-4 text-right font-normal">{t("table.price")}</th>
                <th className="py-2.5 pr-4 text-right font-normal">{t("table.value")}</th>
                <th className="py-2.5 pr-3 text-center font-normal">{t("today")}</th>
                <th className="py-2.5 text-right font-normal">{t("table.pnl")}</th>
              </tr>
            </thead>
            <tbody>
              {holdings.map((h) => {
                const dayUp = (h.change_today ?? 0) >= 0;
                return (
                  <tr
                    key={h.ticker}
                    className="group border-b border-line last:border-0 transition-colors hover:bg-surface-raised/50"
                  >
                    <td className="py-2.5 pr-4">
                      <div className="flex items-center gap-2">
                        {/* Asset class color indicator */}
                        <div
                          className="h-4 w-0.5 rounded-full shrink-0"
                          style={{ backgroundColor: assetColor(h.asset_class) }}
                        />
                        <span className="font-semibold">{h.ticker}</span>
                      </div>
                    </td>
                    <td className="py-2.5 pr-4 text-right text-content-muted">{h.quantity}</td>
                    <td className="py-2.5 pr-4 text-right">{fmt(h.current_price ?? h.cost_basis, h)}</td>
                    <td className="py-2.5 pr-4 text-right font-medium">{fmt(h.current_value ?? 0, h)}</td>
                    <td className="py-2.5 pr-3">
                      <div className="flex items-center justify-center gap-1.5">
                        {typeof h.change_today === "number" ? (
                          <>
                            <Sparkline
                              values={dayUp ? [0, 0.4, 0.3, 1] : [1, 0.6, 0.7, 0]}
                              width={36} height={12}
                              color={dayUp ? "#22C55E" : "#EF4444"}
                            />
                            <span className={cn("text-[11px]", dayUp ? "text-gain" : "text-loss")}>
                              {formatPercent(h.change_today)}
                            </span>
                          </>
                        ) : <span className="text-[11px] text-content-muted">—</span>}
                      </div>
                    </td>
                    <td className={cn("py-2.5 text-right font-medium", (h.pnl ?? 0) >= 0 ? "text-gain" : "text-loss")}>
                      {formatPercent(h.pnl_pct ?? 0)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </motion.div>
  );
}

// ── Briefing card ─────────────────────────────────────────────────────────────

function BriefingCard({ items, loading, fetchedAt }: {
  items: BriefingItem[] | null; loading: boolean; fetchedAt: number | null;
}) {
  const { t } = useTranslation("dashboard");
  const [, setTick] = useState(0);
  useEffect(() => {
    if (!fetchedAt) return;
    const id = setInterval(() => setTick((n) => n + 1), 60_000);
    return () => clearInterval(id);
  }, [fetchedAt]);

  function relativeTime() {
    if (!fetchedAt) return "";
    const mins = Math.floor((Date.now() - fetchedAt) / 60_000);
    return mins < 1 ? t("addedJustNow") : t("addedMinutesAgo", { count: mins });
  }

  const toneBorder: Record<string, string> = {
    positive: "border-l-gain bg-gain/5",
    negative: "border-l-loss bg-loss/5",
    warning:  "border-l-warning bg-warning/5",
    neutral:  "border-l-accent bg-accent/5",
  };
  const toneText: Record<string, string> = {
    positive: "text-gain", negative: "text-loss", warning: "text-warning", neutral: "text-accent",
  };

  return (
    <motion.div variants={CARD_VAR} className="card flex flex-col lg:col-span-5 hover:shadow-[0_0_0_1px_rgba(31,181,122,0.15),0_8px_24px_rgba(0,0,0,0.2)] transition-shadow">
      <CardHeader icon={Newspaper} label={t("todaysBrief")} iconColor="text-content-muted" />
      {loading ? <SkeletonCard lines={5} /> : items && items.length > 0 ? (
        <ul className="mt-3 space-y-2">
          {items.map((it, i) => {
            const Icon = ICONS[it.icon] ?? Sparkles;
            const tone = it.tone ?? "neutral";
            return (
              <motion.li
                key={i}
                initial={{ opacity: 0, x: -8 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: i * 0.08, duration: 0.3 }}
                className={cn(
                  "flex items-start gap-3 rounded-r-lg border-l-2 px-3 py-2 text-sm",
                  toneBorder[tone] ?? toneBorder.neutral,
                )}
              >
                <Icon className={cn("mt-0.5 h-4 w-4 shrink-0", toneText[tone] ?? toneText.neutral)} />
                <div>
                  <span className="text-content-muted mr-1">{it.label}:</span>
                  <span>{it.text}</span>
                </div>
              </motion.li>
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
    </motion.div>
  );
}

// ── Risk badge ────────────────────────────────────────────────────────────────

function RiskBadge({ cls, label, explanation, title }: {
  cls: string; label: string; explanation: string; title: string;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="relative">
      <button
        type="button"
        onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}
        onFocus={() => setOpen(true)} onBlur={() => setOpen(false)}
        onClick={() => setOpen((v) => !v)}
        className={cn("flex items-center gap-1 rounded-full border px-2.5 py-1 text-[10px] font-medium uppercase tracking-wide transition", cls)}
      >
        <span>{label}</span>
        <Info className="h-3 w-3 opacity-70" />
      </button>
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: 6, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 4 }}
            transition={{ duration: 0.15 }}
            className="absolute right-0 top-full z-30 mt-2 w-72 rounded-xl border border-line bg-surface p-3 text-left shadow-2xl"
          >
            <p className="mb-1 text-[10px] font-semibold uppercase tracking-widest text-content-muted">{title}</p>
            <p className="text-xs leading-relaxed text-content">{explanation}</p>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// ── Next Step card ────────────────────────────────────────────────────────────

type StepKind = "onboarding" | "account" | "income" | "expense" | "goal" | "holding";

function NextStepCard({
  loading, hasOnboarded, accountCount, hasIncome, hasExpense, goalCount, holdingCount,
}: {
  loading: boolean; hasOnboarded: boolean; accountCount: number | null;
  hasIncome: boolean; hasExpense: boolean; goalCount: number | null; holdingCount: number;
}) {
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

  const META: Record<StepKind, { title: string; desc: string; cta: string; Icon: LucideIcon; path: string }> = {
    onboarding: { title: t("nextStep.completeOnboarding"), desc: t("nextStep.completeOnboardingDesc"), cta: t("nextStep.completeOnboarding"), Icon: Sparkles, path: "/dashboard" },
    account:    { title: t("nextStep.addAccount"),    desc: t("nextStep.addAccountDesc"),    cta: t("nextStep.ctaAccount"),  Icon: Wallet,       path: "/budget" },
    income:     { title: t("nextStep.addIncome"),     desc: t("nextStep.addIncomeDesc"),     cta: t("nextStep.ctaIncome"),   Icon: ArrowUpRight, path: "/budget" },
    expense:    { title: t("nextStep.addExpense"),    desc: t("nextStep.addExpenseDesc"),    cta: t("nextStep.ctaExpense"),  Icon: Receipt,      path: "/budget" },
    goal:       { title: t("nextStep.addGoal"),       desc: t("nextStep.addGoalDesc"),       cta: t("nextStep.ctaGoal"),     Icon: Target,       path: "/goals" },
    holding:    { title: t("nextStep.addHolding"),    desc: t("nextStep.addHoldingDesc"),    cta: t("nextStep.ctaHolding"),  Icon: Briefcase,    path: "/portfolio" },
  };

  if (loading) return null;
  const allDone = !next;
  const meta = next ? META[next.kind] : null;

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.5 }}
      className="mt-4 overflow-hidden rounded-2xl border border-accent/30 bg-gradient-to-br from-accent/10 via-accent/5 to-transparent p-5"
    >
      <div className="flex flex-col items-start gap-4 md:flex-row md:items-center">
        <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl bg-accent/20 shadow-glow">
          {allDone ? <Sparkles className="h-6 w-6 text-accent" /> : meta ? <meta.Icon className="h-6 w-6 text-accent" /> : null}
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="text-[10px] font-semibold uppercase tracking-widest text-accent">{t("nextStep.title")}</span>
            <span className="text-[10px] text-content-muted">·</span>
            <span className="text-[10px] text-content-muted">{t("nextStep.subtitle")}</span>
          </div>
          <h3 className="mt-1 text-lg font-semibold tracking-tight">{allDone ? t("nextStep.allDone") : meta?.title}</h3>
          <p className="mt-1 text-sm text-content-muted">{allDone ? t("nextStep.allDoneDesc") : meta?.desc}</p>

          {/* Segmented progress bar */}
          <div className="mt-3 flex items-center gap-2">
            <div className="flex flex-1 gap-0.5">
              {steps.map((s, i) => (
                <motion.div
                  key={s.kind}
                  className={cn("h-1.5 flex-1 rounded-full", s.done ? "bg-accent" : "bg-surface-raised")}
                  initial={{ scaleX: 0 }}
                  animate={{ scaleX: 1 }}
                  transition={{ duration: 0.4, delay: 0.6 + i * 0.07 }}
                  style={{ transformOrigin: "left" }}
                />
              ))}
            </div>
            <span className="shrink-0 text-[10px] font-medium text-content-muted">
              {completedCount}/{steps.length} · {pct}%
            </span>
          </div>
        </div>

        {!allDone && meta && (
          <motion.button
            whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.97 }}
            type="button"
            onClick={() => navigate(buildLocalizedPath(lang, meta.path))}
            className="flex shrink-0 items-center gap-2 rounded-xl bg-accent px-4 py-2.5 text-sm font-medium text-white shadow-glow transition hover:bg-accent/90"
          >
            {meta.cta}
            <ArrowRight className="h-4 w-4" />
          </motion.button>
        )}
      </div>
    </motion.div>
  );
}
