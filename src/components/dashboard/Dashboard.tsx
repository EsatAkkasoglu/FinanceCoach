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
  LineChart, Line, XAxis, YAxis,
} from "recharts";

import {
  listPortfolio, getBriefing, getBudgetSummary, captureNetWorth, netWorthHistory,
  listAccounts, listGoals,
  type Holding, type PortfolioTotals, type BriefingItem, type BudgetSummary, type NetWorthPoint,
} from "@/lib/api";
import { formatCurrency, formatPercent } from "@/lib/format";
import { useFxRates } from "@/lib/fx";
import { cn } from "@/lib/cn";
import { assetColor, pnlColor, chartTooltipContentStyle, chartTooltipItemStyle } from "@/lib/chartColors";
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
  const [goalCount, setGoalCount] = useState<number | null>(null);
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
        const [p, b, budgetData, accounts, goals] = await Promise.all([
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
        setGoalCount(goals.length);
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

  return (
    <div>
      {/* Top bar — anchors page title vs page content */}
      <div className="mb-6 flex items-center justify-between border-b border-line pb-3">
        <span className="text-xs font-medium uppercase tracking-[0.14em] text-content-muted">
          {t("title")}
        </span>
        <RiskBadge cls={badgeCls} label={badgeLabel} explanation={riskExplain} title={t("riskExplanation.title")} />
      </div>

      {/* Personalized hero header */}
      <DashboardHero
        avatarEmoji={avatarMeta.emoji}
        greeting={greeting}
        totals={totals}
        holdings={holdings}
        fallbackSubtitle={t("todayAtAGlance")}
      />


      {error && (
        <div className="mb-6 rounded-xl border border-loss/40 bg-loss/10 px-4 py-3 text-sm text-loss">
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-6">
        <NetWorthCard totals={totals} holdings={holdings} history={history} loading={loading && !cache} />
        <BudgetSnapshotCard budget={budget} loading={loading && !cache} />
        <BriefingCard items={briefing} loading={loading && !cache} fetchedAt={briefingFetchedAt} />
        <PortfolioCard holdings={holdings} loading={loading && !cache} />
        <HoldingsTable holdings={holdings} loading={loading && !cache} />
      </div>

      <NextStepCard
        loading={loading && !cache}
        hasOnboarded={authUser?.has_onboarded ?? false}
        accountCount={accountCount}
        hasIncome={hasIncome}
        hasExpense={hasExpense}
        goalCount={goalCount}
        holdingCount={holdings.length}
      />

      <Disclaimer className="mt-8 text-center" />
    </div>
  );
}

// ---------- Hero ----------
function DashboardHero({
  avatarEmoji, greeting, totals, holdings, fallbackSubtitle,
}: {
  avatarEmoji: string;
  greeting: string;
  totals: PortfolioTotals | null;
  holdings: Holding[];
  fallbackSubtitle: string;
}) {
  const fx = useFxRates();
  const displayCcy = fx.rates ? fx.target : "USD";

  // Aggregate today's $ delta across holdings in the display currency.
  // `change_today` is a per-position percentage; the kit's hero shows the
  // sum of (value * change_today / 100). We compute the same here when the
  // backend hasn't aggregated it for us.
  const { todayDelta, totalValue } = useMemo(() => {
    let value = 0;
    let delta = 0;
    for (const h of holdings) {
      const ccy = h.currency ?? "USD";
      const hv = fx.rates ? (fx.convert(h.current_value ?? 0, ccy) ?? (h.current_value ?? 0)) : (h.current_value ?? 0);
      value += hv;
      const pct = (h as unknown as { change_today?: number }).change_today;
      if (typeof pct === "number") delta += hv * (pct / 100);
    }
    if (totals && value === 0) value = totals.value;
    return { todayDelta: delta, totalValue: value };
  }, [holdings, totals, fx]);

  const showDelta = totalValue > 0;
  const positive = todayDelta >= 0;

  return (
    <div className="mb-10 flex items-center gap-5">
      <div className="flex h-16 w-16 shrink-0 items-center justify-center rounded-2xl bg-accent/20 text-3xl leading-none shadow-glow">
        {avatarEmoji}
      </div>
      <div className="min-w-0 flex-1">
        <h1 className="truncate text-[32px] font-semibold leading-tight tracking-tight">{greeting}</h1>
        {showDelta ? (
          <p className="mt-2 flex flex-wrap items-baseline gap-x-2 text-sm text-content-muted">
            <span className="num font-medium text-content">
              {formatCurrency(totalValue, displayCcy)}
            </span>
            <span className="opacity-50">·</span>
            {todayDelta === 0 ? (
              <span className="text-content-muted">{fallbackSubtitle}</span>
            ) : (
              <span className={cn("num font-medium", positive ? "text-gain" : "text-loss")}>
                {positive ? "▲" : "▼"} {formatCurrency(Math.abs(todayDelta), displayCcy)} today
              </span>
            )}
          </p>
        ) : (
          <p className="mt-2 text-sm text-content-muted">{fallbackSubtitle}</p>
        )}
      </div>
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
  const { t } = useTranslation("dashboard");
  const fx = useFxRates();
  // Always honor the user's selected display currency, even when there are
  // no holdings (empty state previously hard-coded USD).
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
  return (
    <div className="card lg:col-span-2">
      <div className="text-xs uppercase tracking-wide text-content-muted">{t("netWorth")}</div>
      {loading ? (
        <div className="mt-2 flex h-12 items-center">
          <Loader2 className="h-5 w-5 animate-spin text-content-muted" />
        </div>
      ) : totals && totals.count > 0 ? (
        <>
          <div className="num mt-2 text-3xl font-semibold">{formatCurrency(value, displayCcy)}</div>
          <div className={cn("mt-1 text-sm", pnl >= 0 ? "text-gain" : "text-loss")}>
            {formatPercent(pnlPct)} ({formatCurrency(pnl, displayCcy)}) {t("allTime")}
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
                    stroke={pnlColor(pnl)}
                    strokeWidth={1.5}
                    dot={false}
                    isAnimationActive={false}
                  />
                </LineChart>
              </ResponsiveContainer>
              <p className="text-[10px] text-content-muted">
                {t("lastNDays", { count: history.length })}
              </p>
            </div>
          )}
        </>
      ) : (
        <>
          <div className="num mt-2 text-3xl font-semibold">{formatCurrency(0, displayCcy)}</div>
          <div className="mt-1 text-xs text-content-muted">
            {t("noHoldings")}
          </div>
        </>
      )}
    </div>
  );
}

// ---------- Budget Snapshot ----------
function BudgetSnapshotCard({ budget, loading }: { budget: BudgetSummary | null; loading: boolean }) {
  const { t } = useTranslation("dashboard");
  const fx = useFxRates();

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

  // Savings rate is only meaningful when BOTH income AND expense have real data
  // for the month. Falling back to onboarding `monthlyIncome` while expenses
  // are 0 makes the rate trivially 100% — misleading and not useful.
  const savingsRate = useMemo(() => {
    if (
      totalIncome != null && totalIncome > 0 &&
      totalExpense != null && totalExpense > 0
    ) {
      return ((totalIncome - totalExpense) / totalIncome) * 100;
    }
    return null;
  }, [totalIncome, totalExpense]);

  return (
    <div className="card lg:col-span-2">
      <div className="text-xs uppercase tracking-wide text-content-muted">{t("thisMonth")}</div>
      {loading ? (
        <div className="mt-2 flex h-12 items-center">
          <Loader2 className="h-5 w-5 animate-spin text-content-muted" />
        </div>
      ) : budget == null ? (
        <p className="mt-3 text-sm text-content-muted">{t("noBudgetData")}</p>
      ) : (
        <div className="mt-3 space-y-2">
          <div className="flex items-center justify-between text-sm">
            <span className="flex items-center gap-1.5 text-content-muted">
              <ArrowUpRight className="h-3.5 w-3.5 text-gain" />
              {t("income")}
            </span>
            <span className="num font-medium text-gain">
              {totalIncome != null ? formatCurrency(totalIncome, displayCcy) : "—"}
            </span>
          </div>
          <div className="flex items-center justify-between text-sm">
            <span className="flex items-center gap-1.5 text-content-muted">
              <ArrowDownRight className="h-3.5 w-3.5 text-loss" />
              {t("expenses")}
            </span>
            <span className="num font-medium text-loss">
              {totalExpense != null ? formatCurrency(totalExpense, displayCcy) : "—"}
            </span>
          </div>
          {savingsRate != null && (
            <div className="flex items-center justify-between border-t border-line pt-2 text-sm">
              <span className="flex items-center gap-1.5 text-content-muted">
                <PiggyBank className="h-3.5 w-3.5 text-accent" />
                {t("savingsRate")}
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
    <div className="card lg:col-span-2 flex flex-col">
      <div className="text-xs uppercase tracking-wide text-content-muted">{t("todaysBrief")}</div>
      {loading ? (
        <div className="mt-3 flex h-16 items-center">
          <Loader2 className="h-5 w-5 animate-spin text-content-muted" />
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

// ---------- Portfolio donut ----------
function PortfolioCard({ holdings, loading }: { holdings: Holding[]; loading: boolean }) {
  const { t } = useTranslation("dashboard");
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
      <div className="text-xs uppercase tracking-wide text-content-muted">{t("allocation")}</div>
      {loading ? (
        <div className="mt-3 flex h-44 items-center justify-center">
          <Loader2 className="h-5 w-5 animate-spin text-content-muted" />
        </div>
      ) : !hasData ? (
        <p className="mt-3 text-sm text-content-muted">{t("addHoldingsForBreakdown")}</p>
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
                  <Cell key={d.name} fill={assetColor(d.name)} />
                ))}
              </Pie>
              <Tooltip
                contentStyle={chartTooltipContentStyle}
                formatter={(v: number, name: string) => [
                  formatCurrency(v, displayCcy),
                  name.charAt(0).toUpperCase() + name.slice(1),
                ]}
                labelFormatter={() => ""}
                separator=": "
                itemStyle={chartTooltipItemStyle}
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
                  style={{ background: assetColor(d.name) }}
                />
                {d.name}
              </span>
              <span className="num text-content-muted">{formatCurrency(d.value, displayCcy)}</span>
            </li>
          ))}
        </ul>
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

  // Build the ordered checklist; first not-yet-done = next step.
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

          {/* Progress bar */}
          <div className="mt-3 flex items-center gap-3">
            <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-raised">
              <div
                className="h-full rounded-full bg-accent transition-all duration-500"
                style={{ width: `${pct}%` }}
              />
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
    <div className="card lg:col-span-4">
      <div className="text-xs uppercase tracking-wide text-content-muted">{t("holdings")}</div>
      {loading ? (
        <div className="mt-3 flex h-32 items-center">
          <Loader2 className="h-5 w-5 animate-spin text-content-muted" />
        </div>
      ) : holdings.length === 0 ? (
        <p className="mt-3 text-sm text-content-muted">
          {t("noHoldingsDesc")}
        </p>
      ) : (
        <div className="mt-3 overflow-x-auto">
          <table className="num min-w-full text-sm">
            <thead className="text-xs uppercase tracking-wide text-content-muted">
              <tr className="border-b border-line">
                <th className="py-3 pr-4 text-left font-normal">{t("table.ticker")}</th>
                <th className="py-3 pr-4 text-right font-normal">{t("table.qty")}</th>
                <th className="py-3 pr-4 text-right font-normal">{t("table.price")}</th>
                <th className="py-3 pr-4 text-right font-normal">{t("table.value")}</th>
                <th className="py-3 text-right font-normal">{t("table.pnl")}</th>
              </tr>
            </thead>
            <tbody>
              {holdings.map((h) => (
                <tr key={h.ticker} className="border-b border-line last:border-0">
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
