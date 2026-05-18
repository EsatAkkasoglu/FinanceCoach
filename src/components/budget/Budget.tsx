/**
 * Budget — single page. Top: 4 summary KPIs. Action strip with import / receipt / manual.
 * Below: accounts panel + subscriptions panel side-by-side, then transactions table.
 */
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Upload, Plus, Wallet, TrendingUp, TrendingDown, RefreshCcw,
  Pencil, Trash2, CreditCard, Banknote, Building2, Loader2,
  Calendar, AlertCircle, ArrowUpRight, ArrowDownRight, Sparkles,
  Repeat, PiggyBank, Music, Home, Briefcase, Shield, Tv, Dumbbell,
  Wrench, Landmark, type LucideIcon,
} from "lucide-react";
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip as RechartsTooltip } from "recharts";
import { toast } from "sonner";

import {
  listAccounts, listTransactions, listSubscriptions, getBudgetSummary,
  deleteAccount, deleteTransaction, deleteSubscription, updateSubscription,
  type Account, type Transaction, type Subscription, type BudgetSummary,
  type SubDirection, type SubscriptionInput,
} from "@/lib/api";
import { cn } from "@/lib/cn";
import { formatCurrency } from "@/lib/format";
import { useFxRates, type UseFxRates } from "@/lib/fx";
import { Button } from "@/components/ui/Button";
import { AccountFormModal } from "./AccountFormModal";
import { TransactionFormModal, COMMON_CATEGORIES } from "./TransactionFormModal";
import { SubscriptionFormModal } from "./SubscriptionFormModal";
import { BudgetImportModal } from "./BudgetImportModal";
import { Disclaimer } from "@/components/ui/Disclaimer";

const ACCOUNT_ICON: Record<Account["kind"], typeof Wallet> = {
  cash: Wallet,
  checking: Building2,
  savings: PiggyBank,
  credit_card: CreditCard,
};

const ACCOUNT_LABEL: Record<Account["kind"], string> = {
  cash: "Cash",
  checking: "Checking",
  savings: "Savings",
  credit_card: "Credit card",
};

const SUBSCRIPTION_ICON: Record<string, LucideIcon> = {
  briefcase: Briefcase,
  salary: Briefcase,
  freelance: Briefcase,
  home: Home,
  rent: Home,
  rental: Home,
  music: Music,
  entertainment: Music,
  streaming: Tv,
  tv: Tv,
  shield: Shield,
  insurance: Shield,
  subscriptions: CreditCard,
  subscription: CreditCard,
  software: Wrench,
  fitness: Dumbbell,
  gym: Dumbbell,
  bank: Landmark,
};

export function Budget() {
  const { t } = useTranslation("budget");
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [txs, setTxs] = useState<Transaction[]>([]);
  const [subs, setSubs] = useState<Subscription[]>([]);
  const [summary, setSummary] = useState<BudgetSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Modals
  const [importOpen, setImportOpen] = useState(false);
  const [accountModal, setAccountModal] = useState<{ open: boolean; editing: Account | null }>({ open: false, editing: null });
  const [txModal, setTxModal] = useState<{ open: boolean; editing: Transaction | null }>({ open: false, editing: null });
  const [subModal, setSubModal] = useState<{
    open: boolean;
    editing: Subscription | null;
    defaultDirection: SubDirection;
    prefill: Partial<SubscriptionInput> | null;
  }>({ open: false, editing: null, defaultDirection: "expense", prefill: null });

  // Filter state
  const [filterType, setFilterType] = useState<"all" | "income" | "expense">("all");
  const [filterCategory, setFilterCategory] = useState<string>("all");

  const fx = useFxRates();

  function openAddSub(direction: SubDirection) {
    setSubModal({ open: true, editing: null, defaultDirection: direction, prefill: null });
  }

  function markTxAsRecurring(t: Transaction) {
    const direction: SubDirection = t.type === "income" ? "income" : "expense";
    setSubModal({
      open: true,
      editing: null,
      defaultDirection: direction,
      prefill: {
        name: t.description || (direction === "income" ? "Recurring income" : "Recurring expense"),
        amount: t.amount,
        currency: t.currency,
        category: t.category !== "uncategorized" ? t.category : undefined,
        direction,
      },
    });
  }

  async function refresh(silent = false) {
    if (!silent) setLoading(true);
    setError(null);
    try {
      const [a, t, s, sum] = await Promise.all([
        listAccounts(),
        listTransactions(),
        listSubscriptions(true),
        getBudgetSummary(),
      ]);
      setAccounts(a);
      setTxs(t);
      setSubs(s);
      setSummary(sum);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => { void refresh(); }, []);

  const filteredTxs = useMemo(() => {
    return txs.filter((t) => {
      if (filterType !== "all" && t.type !== filterType) return false;
      if (filterCategory !== "all" && t.category !== filterCategory) return false;
      return true;
    });
  }, [txs, filterType, filterCategory]);

  async function handleDeleteAccount(a: Account) {
    if (!window.confirm(`Archive ${a.name}? Past transactions remain visible.`)) return;
    try { await deleteAccount(a.id); toast.success("Account archived"); refresh(true); }
    catch (err) { toast.error((err as Error).message); }
  }
  async function handleDeleteTx(t: Transaction) {
    if (!window.confirm("Remove this transaction?")) return;
    setTxs((prev) => prev.filter((x) => x.id !== t.id)); // optimistic
    try { await deleteTransaction(t.id); refresh(true); }
    catch (err) { toast.error((err as Error).message); refresh(true); }
  }
  async function handleDeleteSub(s: Subscription) {
    if (!window.confirm(`Cancel ${s.name}? It will move to "Cancelled".`)) return;
    try { await updateSubscription(s.id, { active: false }); toast.success(`${s.name} cancelled`); refresh(true); }
    catch (err) { toast.error((err as Error).message); }
  }
  async function handleHardDeleteSub(s: Subscription) {
    try { await deleteSubscription(s.id); refresh(true); }
    catch (err) { toast.error((err as Error).message); }
  }

  const isEmpty = !loading && accounts.length === 0 && txs.length === 0 && subs.length === 0;

  return (
    <div>
      <header className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">{t("title")}</h1>
          <p className="text-sm text-[hsl(var(--text-muted))]">
            {t("subtitle")}
          </p>
        </div>
      </header>

      {error && (
        <div className="mb-4 rounded-xl border border-loss/40 bg-loss/10 px-4 py-3 text-sm text-loss">
          {error}
        </div>
      )}

      {loading ? (
        <BudgetSkeleton />
      ) : isEmpty ? (
        <BudgetEmpty
          onImport={() => setImportOpen(true)}
          onAddAccount={() => setAccountModal({ open: true, editing: null })}
          onAddManual={() => setTxModal({ open: true, editing: null })}
        />
      ) : (
        <>
          <SummaryRow summary={summary} fx={fx} />
          <ActionStrip
            onImport={() => setImportOpen(true)}
            onAddManual={() => setTxModal({ open: true, editing: null })}
          />

          {summary && (
            <div className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-3">
              <CategoriesDonut summary={summary} fx={fx} />
              <UpcomingCharges summary={summary} fx={fx} />
            </div>
          )}

          <div className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-2">
            <AccountsPanel
              accounts={accounts}
              fx={fx}
              onAdd={() => setAccountModal({ open: true, editing: null })}
              onEdit={(a) => setAccountModal({ open: true, editing: a })}
              onDelete={handleDeleteAccount}
            />
            <RecurringPanel
              title={t("incomeSources")}
              subtitle={t("recurringIncome")}
              emptyHint={t("kpi.recurringHint")}
              tone="income"
              subscriptions={subs.filter((s) => s.direction === "income")}
              monthlyTotals={summary?.recurring.income_monthly_by_currency ?? {}}
              fx={fx}
              onAdd={() => openAddSub("income")}
              onEdit={(s) => setSubModal({ open: true, editing: s, defaultDirection: s.direction, prefill: null })}
              onCancel={handleDeleteSub}
              onHardDelete={handleHardDeleteSub}
            />
          </div>

          <div className="mt-4">
            <RecurringPanel
              title={t("subscriptions")}
              subtitle={t("subscriptionsHint")}
              emptyHint={t("subscriptionsHint")}
              tone="expense"
              subscriptions={subs.filter((s) => s.direction !== "income")}
              monthlyTotals={summary?.recurring.expense_monthly_by_currency ?? {}}
              fx={fx}
              onAdd={() => openAddSub("expense")}
              onEdit={(s) => setSubModal({ open: true, editing: s, defaultDirection: s.direction, prefill: null })}
              onCancel={handleDeleteSub}
              onHardDelete={handleHardDeleteSub}
            />
          </div>

          <TransactionsPanel
            transactions={filteredTxs}
            allCount={txs.length}
            accounts={accounts}
            fx={fx}
            filterType={filterType}
            setFilterType={setFilterType}
            filterCategory={filterCategory}
            setFilterCategory={setFilterCategory}
            onAdd={() => setTxModal({ open: true, editing: null })}
            onEdit={(t) => setTxModal({ open: true, editing: t })}
            onDelete={handleDeleteTx}
            onMarkRecurring={markTxAsRecurring}
          />
        </>
      )}

      <AccountFormModal
        open={accountModal.open}
        onClose={() => setAccountModal({ open: false, editing: null })}
        onSaved={() => refresh(true)}
        editing={accountModal.editing}
      />
      <TransactionFormModal
        open={txModal.open}
        onClose={() => setTxModal({ open: false, editing: null })}
        onSaved={() => refresh(true)}
        editing={txModal.editing}
        accounts={accounts}
      />
      <SubscriptionFormModal
        open={subModal.open}
        onClose={() => setSubModal({ open: false, editing: null, defaultDirection: "expense", prefill: null })}
        onSaved={() => refresh(true)}
        editing={subModal.editing}
        defaultDirection={subModal.defaultDirection}
        prefill={subModal.prefill}
      />
      <BudgetImportModal
        open={importOpen}
        onClose={() => setImportOpen(false)}
        onImported={() => refresh(true)}
        accounts={accounts}
      />
      <Disclaimer className="mt-8 text-center" />
    </div>
  );
}

// ── Summary KPIs ────────────────────────────────────────────────────────────

function SummaryRow({ summary, fx }: { summary: BudgetSummary | null; fx: UseFxRates }) {
  const { t } = useTranslation("budget");
  if (!summary) return null;
  const cashByCcy = summary.cash_on_hand;
  const incomeByCcy = summary.income_mtd;
  const expenseByCcy = summary.expense_mtd;
  const recurringIncome = summary.recurring.income_monthly_by_currency;

  const incomeMoM = computeMoM(incomeByCcy, summary.income_prev_month, fx);
  const expenseMoM = computeMoM(expenseByCcy, summary.expense_prev_month, fx);

  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <KPICard
        title={t("kpi.cashOnHand")}
        icon={<Wallet className="h-4 w-4" />}
        bag={cashByCcy}
        fx={fx}
        subtitle={Object.keys(cashByCcy).length === 0 ? t("kpi.noAccounts") : undefined}
      />
      <KPICard
        title={t("kpi.incomeThisMonth")}
        icon={<TrendingUp className="h-4 w-4 text-gain" />}
        bag={incomeByCcy}
        fx={fx}
        subtitle={Object.keys(incomeByCcy).length === 0 ? t("kpi.noIncome") : undefined}
        delta={incomeMoM}
        deltaPositiveIsGood
      />
      <KPICard
        title={t("kpi.spendingThisMonth")}
        icon={<TrendingDown className="h-4 w-4 text-loss" />}
        bag={expenseByCcy}
        fx={fx}
        subtitle={Object.keys(expenseByCcy).length === 0 ? t("kpi.nothingSpent") : undefined}
        delta={expenseMoM}
        deltaPositiveIsGood={false}
      />
      <KPICard
        title={t("kpi.recurringIncome")}
        icon={<Repeat className="h-4 w-4 text-accent" />}
        bag={recurringIncome}
        fx={fx}
        subtitle={Object.keys(recurringIncome).length === 0 ? t("kpi.recurringHint") : undefined}
      />
    </div>
  );
}

function computeMoM(
  thisMonth: Record<string, number>,
  prevMonth: Record<string, number>,
  fx: UseFxRates,
): number | null {
  const cur = fx.rates ? fx.convertBag(thisMonth) : sumValues(thisMonth);
  const prev = fx.rates ? fx.convertBag(prevMonth) : sumValues(prevMonth);
  if (cur == null || prev == null || prev === 0) return null;
  return ((cur - prev) / prev) * 100;
}

function sumValues(bag: Record<string, number>): number {
  return Object.values(bag).reduce((a, b) => a + b, 0);
}

function KPICard({
  title, icon, bag, fx, subtitle, delta, deltaPositiveIsGood = true,
}: {
  title: string;
  icon: React.ReactNode;
  bag: Record<string, number>;
  fx: UseFxRates;
  subtitle?: string;
  /** Month-over-month percent change, or null if unavailable. */
  delta?: number | null;
  /** When true, a positive delta is "good" (green); flip for spending. */
  deltaPositiveIsGood?: boolean;
}) {
  const entries = Object.entries(bag);
  const converted = entries.length ? fx.convertBag(bag) : null;
  const fallback = !fx.rates;  // FX hasn't loaded — show native amounts

  return (
    <div className="card">
      <div className="flex items-center justify-between text-xs uppercase tracking-wide text-[hsl(var(--text-muted))]">
        <span>{title}</span>
        <span>{icon}</span>
      </div>
      <div className="mt-2">
        {entries.length === 0 ? (
          <div className="text-2xl font-semibold tabular-nums">—</div>
        ) : fallback ? (
          <div className="space-y-0.5">
            {entries.map(([ccy, n]) => (
              <div key={ccy} className="flex items-baseline gap-2">
                <span className="num text-2xl font-semibold tabular-nums">
                  {n.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                </span>
                <span className="text-xs text-[hsl(var(--text-muted))]">{ccy}</span>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-2xl font-semibold tabular-nums">
            {converted == null ? "—" : formatCurrency(converted, fx.target)}
          </div>
        )}
      </div>
      {delta != null && Number.isFinite(delta) && (
        <p className="mt-1 text-[11px]">
          <span
            className={cn(
              "font-semibold",
              (deltaPositiveIsGood ? delta >= 0 : delta <= 0) ? "text-gain" : "text-loss",
            )}
          >
            {delta >= 0 ? "+" : ""}{delta.toFixed(1)}%
          </span>
          <span className="text-[hsl(var(--text-muted))]"> vs last month</span>
        </p>
      )}
      {subtitle && <p className="mt-1 text-[11px] text-[hsl(var(--text-muted))]">{subtitle}</p>}
    </div>
  );
}

// ── Top categories donut ────────────────────────────────────────────────────

const CATEGORY_COLORS = [
  "#14B8A6", "#8B5CF6", "#F59E0B", "#3B82F6", "#EC4899", "#10B981", "#EF4444",
];

const CATEGORY_LABELS_TR: Record<string, string> = {
  rent: "Kira", housing: "Konut", dining: "Yemek", groceries: "Market",
  food: "Yiyecek", entertainment: "Eğlence", shopping: "Alışveriş",
  transport: "Ulaşım", health: "Sağlık", education: "Eğitim",
  utilities: "Faturalar", subscriptions: "Abonelikler", salary: "Maaş",
  freelance: "Serbest", investment: "Yatırım", savings: "Birikim",
  travel: "Seyahat", clothing: "Giyim", software: "Yazılım",
  insurance: "Sigorta", gym: "Spor salonu", fitness: "Spor",
  transfer: "Transfer", other: "Diğer", uncategorized: "Kategorisiz",
};

function localizeCategory(name: string, lang: string): string {
  const key = name.toLowerCase().trim();
  if (lang === "tr") return CATEGORY_LABELS_TR[key] ?? name;
  return name.charAt(0).toUpperCase() + name.slice(1).toLowerCase();
}

function CategoriesDonut({ summary, fx }: { summary: BudgetSummary; fx: UseFxRates }) {
  const { t, i18n } = useTranslation("budget");
  const items = useMemo(() => {
    const list = (summary.top_categories ?? []).map((c) => {
      const value = fx.rates
        ? (fx.convert(c.amount, c.currency) ?? c.amount)
        : c.amount;
      return { name: c.category, value, currency: c.currency, raw: c.amount };
    });
    return list.sort((a, b) => b.value - a.value).slice(0, 5);
  }, [summary, fx]);

  const total = items.reduce((a, b) => a + b.value, 0);

  if (items.length === 0) {
    return (
      <section className="card">
        <h2 className="text-sm font-semibold">{t("topCategories")}</h2>
        <p className="mt-3 rounded-lg border border-dashed border-[hsl(var(--border))] p-4 text-center text-xs text-[hsl(var(--text-muted))]">
          {t("whereMoneyWent")}
        </p>
      </section>
    );
  }

  return (
    <section className="card">
      <h2 className="text-sm font-semibold">{t("topCategories")}</h2>
      <p className="text-[11px] text-[hsl(var(--text-muted))]">{t("whereMoneyWent")}</p>

      <div className="mt-4 flex gap-5">
        {/* Donut */}
        <div className="relative h-36 w-36 shrink-0">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie data={items} dataKey="value" nameKey="name" innerRadius={42} outerRadius={64} paddingAngle={2}>
                {items.map((_, i) => (
                  <Cell key={i} fill={CATEGORY_COLORS[i % CATEGORY_COLORS.length]} stroke="none" />
                ))}
              </Pie>
              <RechartsTooltip
                contentStyle={{ background: "hsl(var(--surface))", border: "1px solid hsl(var(--border))", fontSize: 12, borderRadius: 8 }}
                formatter={(v: number, _: unknown, entry) => {
                  const name = typeof entry.payload?.name === "string" ? entry.payload.name : "";
                  return [
                    fx.rates ? formatCurrency(v, fx.target) : v.toFixed(2),
                    localizeCategory(name, i18n.language),
                  ];
                }}
              />
            </PieChart>
          </ResponsiveContainer>
        </div>

        {/* Legend list */}
        <ul className="flex-1 self-center space-y-2">
          {items.map((it, i) => {
            const pct = total ? (it.value / total) * 100 : 0;
            const color = CATEGORY_COLORS[i % CATEGORY_COLORS.length];
            return (
              <li key={it.name} className="grid items-center gap-x-2 text-xs" style={{ gridTemplateColumns: "8px 1fr auto auto" }}>
                <span className="h-2 w-2 rounded-full shrink-0" style={{ background: color }} />
                <span className="truncate text-[hsl(var(--text))] capitalize">
                  {localizeCategory(it.name, i18n.language)}
                </span>
                <span className="num font-semibold tabular-nums">
                  {fx.rates ? formatCurrency(it.value, fx.target) : `${it.raw.toFixed(0)} ${it.currency}`}
                </span>
                <span
                  className="rounded-full px-1.5 py-0.5 text-[10px] font-medium tabular-nums text-right min-w-[2.5rem]"
                  style={{ background: `${color}22`, color }}
                >
                  {pct.toFixed(0)}%
                </span>
              </li>
            );
          })}
        </ul>
      </div>
    </section>
  );
}

// ── Upcoming charges (next 30 days) ─────────────────────────────────────────

function UpcomingCharges({ summary, fx }: { summary: BudgetSummary; fx: UseFxRates }) {
  const { t } = useTranslation("budget");
  const upcoming = useMemo(() => {
    const list = (summary.recurring.upcoming ?? []).slice();
    list.sort((a, b) => {
      if (!a.next_charge_on) return 1;
      if (!b.next_charge_on) return -1;
      return a.next_charge_on.localeCompare(b.next_charge_on);
    });
    return list.slice(0, 6);
  }, [summary]);

  return (
    <section className="card lg:col-span-2">
      <header className="mb-2 flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold">{t("upcomingTitle")}</h2>
          <p className="text-[11px] text-[hsl(var(--text-muted))]">
            {t("upcomingDesc")}
          </p>
        </div>
      </header>
      {upcoming.length === 0 ? (
        <p className="rounded-lg border border-dashed border-[hsl(var(--border))] p-4 text-center text-xs text-[hsl(var(--text-muted))]">
          {t("upcomingEmpty")}
        </p>
      ) : (
        <ul className="divide-y divide-[hsl(var(--border))]">
          {upcoming.map((s) => {
            const days = s.next_charge_on ? daysUntil(s.next_charge_on) : null;
            const isIncome = s.direction === "income";
            const label =
              days == null ? "—"
              : days < 0 ? `${Math.abs(days)}d ${isIncome ? "late" : "overdue"}`
              : days === 0 ? "today"
              : days === 1 ? "tomorrow"
              : `in ${days}d`;
            const urgency =
              days == null ? "later"
              : days <= 2 ? "imminent"
              : days <= 7 ? "soon"
              : "later";
            return (
              <li key={s.id} className="flex items-center gap-3 py-2">
                <SubscriptionAvatar icon={s.icon} name={s.name} category={s.category} size="sm" />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">{s.name}</p>
                  <p className="text-[11px] text-[hsl(var(--text-muted))]">{s.cycle} · {s.category}</p>
                </div>
                <span
                  className={cn(
                    "rounded-full px-2 py-0.5 text-[10px]",
                    urgency === "imminent" && (isIncome ? "bg-gain/15 text-gain" : "bg-loss/15 text-loss"),
                    urgency === "soon" && (isIncome ? "bg-gain/10 text-gain" : "bg-warning/15 text-warning"),
                    urgency === "later" && "bg-[hsl(var(--surface-2))] text-[hsl(var(--text-muted))]",
                  )}
                >
                  {label}
                </span>
                <AmountCell
                  amount={s.amount}
                  currency={s.currency}
                  fx={fx}
                  sign={isIncome ? "pos" : "neg"}
                  className={cn("text-sm font-semibold w-24 text-right", isIncome ? "text-gain" : "text-loss")}
                />
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

// ── Action strip ────────────────────────────────────────────────────────────

function ActionStrip({ onImport, onAddManual }: { onImport: () => void; onAddManual: () => void }) {
  const { t } = useTranslation("budget");
  return (
    <div className="mt-6 grid grid-cols-1 gap-3 sm:grid-cols-2">
      <button
        onClick={onImport}
        className="group flex items-center gap-3 rounded-xl border border-accent/40 bg-accent-muted/30 p-4 text-left transition hover:bg-accent-muted/60"
      >
        <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-accent text-white">
          <Upload className="h-5 w-5" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold">{t("uploadDoc")}</p>
          <p className="text-xs text-[hsl(var(--text-muted))]">
            {t("uploadDocDesc")}
          </p>
        </div>
        <Sparkles className="h-4 w-4 text-accent opacity-60" />
      </button>
      <button
        onClick={onAddManual}
        className="group flex items-center gap-3 rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--surface-2))] p-4 text-left transition hover:border-[hsl(var(--text-muted))]"
      >
        <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-[hsl(var(--surface))]">
          <Plus className="h-5 w-5" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold">{t("addManually")}</p>
          <p className="text-xs text-[hsl(var(--text-muted))]">
            {t("addManuallyDesc")}
          </p>
        </div>
      </button>
    </div>
  );
}

// ── Accounts panel ──────────────────────────────────────────────────────────

function AccountsPanel({
  accounts, fx, onAdd, onEdit, onDelete,
}: {
  accounts: Account[];
  fx: UseFxRates;
  onAdd: () => void;
  onEdit: (a: Account) => void;
  onDelete: (a: Account) => void;
}) {
  const { t } = useTranslation("budget");
  return (
    <section className="card">
      <header className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold">{t("accounts")}</h2>
        <Button variant="ghost" size="sm" onClick={onAdd}>
          <Plus className="h-3.5 w-3.5" /> {t("common:add", "Add")}
        </Button>
      </header>
      {accounts.length === 0 ? (
        <p className="rounded-lg border border-dashed border-[hsl(var(--border))] p-4 text-center text-xs text-[hsl(var(--text-muted))]">
          {t("noAccountsYet")}
        </p>
      ) : (
        <ul className="space-y-1.5">
          {accounts.map((a) => {
            const Icon = ACCOUNT_ICON[a.kind];
            const isCard = a.kind === "credit_card";
            return (
              <li
                key={a.id}
                className="group flex items-center gap-3 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--surface-2))] px-3 py-2.5 transition hover:border-[hsl(var(--text-muted))]"
              >
                <span className={cn(
                  "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg",
                  isCard ? "bg-loss/10 text-loss" : "bg-accent-muted text-accent",
                )}>
                  <Icon className="h-4 w-4" />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">{a.name}</p>
                  <p className="text-[11px] text-[hsl(var(--text-muted))]">
                    {ACCOUNT_LABEL[a.kind]}{a.institution ? ` · ${a.institution}` : ""}
                  </p>
                </div>
                <div className="text-right shrink-0">
                  <AmountCell
                    amount={a.balance}
                    currency={a.currency}
                    fx={fx}
                    sign={isCard ? "neg" : "neutral"}
                    className={cn("text-sm font-semibold", isCard && "text-loss")}
                  />
                </div>
                <div className="ml-1 hidden shrink-0 gap-0.5 group-hover:flex">
                  <IconButton onClick={() => onEdit(a)} aria-label="Edit account"><Pencil className="h-3.5 w-3.5" /></IconButton>
                  <IconButton onClick={() => onDelete(a)} aria-label="Archive account"><Trash2 className="h-3.5 w-3.5" /></IconButton>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

// ── Subscriptions panel ─────────────────────────────────────────────────────

function RecurringPanel({
  title, subtitle, emptyHint, tone,
  subscriptions, monthlyTotals, fx,
  onAdd, onEdit, onCancel, onHardDelete,
}: {
  title: string;
  subtitle: string;
  emptyHint: string;
  tone: "income" | "expense";
  subscriptions: Subscription[];
  monthlyTotals: Record<string, number>;
  fx: UseFxRates;
  onAdd: () => void;
  onEdit: (s: Subscription) => void;
  onCancel: (s: Subscription) => void;
  onHardDelete: (s: Subscription) => void;
}) {
  const totalEntries = Object.entries(monthlyTotals);
  const convertedMonthly = totalEntries.length ? fx.convertBag(monthlyTotals) : null;
  const hasFx = fx.rates != null;

  return (
    <section className="card">
      <header className="mb-3 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h2 className="text-sm font-semibold">{title}</h2>
            <span className={cn(
              "rounded-full px-1.5 py-0.5 text-[10px] uppercase",
              tone === "income" ? "bg-gain/15 text-gain" : "bg-loss/10 text-loss",
            )}>
              {tone === "income" ? "incoming" : "outgoing"}
            </span>
          </div>
          {totalEntries.length > 0 ? (
            hasFx && convertedMonthly != null ? (
              <p className="mt-1 text-[11px] text-[hsl(var(--text-muted))]">
                <span className={cn("font-semibold", tone === "income" ? "text-gain" : "")}>
                  {formatCurrency(convertedMonthly, fx.target)}
                </span>
                /mo · <span>{formatCurrency(convertedMonthly * 12, fx.target)}</span>/yr
              </p>
            ) : (
              <p className="mt-1 flex flex-wrap gap-x-2 text-[11px] text-[hsl(var(--text-muted))]">
                {totalEntries.map(([ccy, total]) => (
                  <span key={ccy}>
                    <span className={cn("font-mono font-semibold", tone === "income" ? "text-gain" : "")}>
                      {total.toLocaleString(undefined, { maximumFractionDigits: 2 })} {ccy}
                    </span>
                    /mo
                  </span>
                ))}
              </p>
            )
          ) : (
            <p className="mt-1 text-[11px] text-[hsl(var(--text-muted))]">{subtitle}</p>
          )}
        </div>
        <Button variant="ghost" size="sm" onClick={onAdd}>
          <Plus className="h-3.5 w-3.5" /> Add
        </Button>
      </header>

      {subscriptions.length === 0 ? (
        <p className="rounded-lg border border-dashed border-[hsl(var(--border))] p-4 text-center text-xs text-[hsl(var(--text-muted))]">
          {emptyHint}
        </p>
      ) : (
        <div className="grid grid-cols-1 gap-2 min-[480px]:grid-cols-2">
          {subscriptions.map((s) => (
            <SubscriptionCard
              key={s.id}
              sub={s}
              fx={fx}
              onEdit={() => onEdit(s)}
              onCancel={() => onCancel(s)}
              onHardDelete={() => onHardDelete(s)}
            />
          ))}
        </div>
      )}
    </section>
  );
}

function SubscriptionCard({
  sub, fx, onEdit, onCancel, onHardDelete,
}: {
  sub: Subscription;
  fx: UseFxRates;
  onEdit: () => void;
  onCancel: () => void;
  onHardDelete: () => void;
}) {
  const days = sub.next_charge_on ? daysUntil(sub.next_charge_on) : null;
  const isIncome = sub.direction === "income";
  const urgency =
    days == null ? null
    : days < 0 ? "overdue"
    : days <= 2 ? "imminent"
    : days <= 7 ? "soon"
    : "later";

  return (
    <div className={cn(
      "group relative rounded-xl border bg-[hsl(var(--surface-2))] p-3 transition hover:border-[hsl(var(--text-muted))]",
      isIncome ? "border-gain/30" : "border-[hsl(var(--border))]",
    )}>
      {/* Top row: icon + name/subtitle only — no amount competing for width */}
      <div className="flex items-center gap-2.5">
        <SubscriptionAvatar icon={sub.icon} name={sub.name} category={sub.category} />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium">{sub.name}</p>
          <p className="truncate text-[11px] text-[hsl(var(--text-muted))]">
            {sub.cycle} · {sub.category}
          </p>
        </div>
      </div>

      {/* Bottom row: date badge left, amount right — both always have room */}
      <div className="mt-2 flex items-center justify-between gap-2 text-[11px]">
        <div className="flex items-center gap-0.5">
          {urgency ? (
            <span className={cn(
              "inline-flex items-center gap-1 rounded-full px-1.5 py-0.5",
              urgency === "overdue" && (isIncome ? "bg-warning/15 text-warning" : "bg-loss/15 text-loss"),
              urgency === "imminent" && (isIncome ? "bg-gain/15 text-gain" : "bg-loss/10 text-loss"),
              urgency === "soon" && (isIncome ? "bg-gain/10 text-gain" : "bg-warning/15 text-warning"),
              urgency === "later" && "bg-[hsl(var(--surface))] text-[hsl(var(--text-muted))]",
            )}>
              <Calendar className="h-3 w-3" />
              {urgency === "overdue"
                ? (isIncome ? `${Math.abs(days!)}d late` : `${Math.abs(days!)}d overdue`)
                : days === 0 ? "today"
                : days === 1 ? "tomorrow"
                : `in ${days}d`}
            </span>
          ) : (
            <span className="text-[hsl(var(--text-muted))]">no date</span>
          )}
          <div className="hidden gap-0.5 group-hover:flex">
            <IconButton onClick={onEdit} aria-label="Edit"><Pencil className="h-3 w-3" /></IconButton>
            <IconButton onClick={onCancel} aria-label="Cancel" title="Mark as cancelled">
              <AlertCircle className="h-3 w-3" />
            </IconButton>
            <IconButton onClick={onHardDelete} aria-label="Delete forever"><Trash2 className="h-3 w-3" /></IconButton>
          </div>
        </div>
        <AmountCell
          amount={sub.amount}
          currency={sub.currency}
          fx={fx}
          sign={isIncome ? "pos" : "neutral"}
          className={cn("text-sm font-semibold text-right", isIncome && "text-gain")}
        />
      </div>
    </div>
  );
}

function SubscriptionAvatar({
  icon, name, category, size = "md",
}: {
  icon: string | null;
  name: string;
  category?: string | null;
  size?: "sm" | "md";
}) {
  const key = (icon || category || "").trim().toLowerCase();
  const Icon = SUBSCRIPTION_ICON[key] ?? SUBSCRIPTION_ICON[(category || "").trim().toLowerCase()];
  const boxClass = size === "sm" ? "h-8 w-8" : "h-9 w-9";
  const iconClass = size === "sm" ? "h-4 w-4" : "h-[18px] w-[18px]";

  if (Icon) {
    return (
      <span
        className={cn(
          "flex shrink-0 items-center justify-center overflow-hidden rounded-lg bg-[hsl(var(--surface))] text-[hsl(var(--text-muted))]",
          boxClass,
        )}
      >
        <Icon className={iconClass} />
      </span>
    );
  }

  const raw = (icon || "").trim();
  const isNamedKey = /^[a-z0-9_-]{3,}$/i.test(raw);
  const label = raw && !isNamedKey ? raw : name.slice(0, 1).toUpperCase();

  return (
    <span
      className={cn(
        "flex shrink-0 items-center justify-center overflow-hidden rounded-lg bg-[hsl(var(--surface))] text-center text-sm leading-none",
        boxClass,
      )}
      title={isNamedKey ? raw : undefined}
    >
      <span className="max-w-full truncate px-0.5">{label}</span>
    </span>
  );
}

function daysUntil(iso: string): number {
  const target = new Date(iso + "T00:00:00");
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return Math.round((target.getTime() - today.getTime()) / (1000 * 60 * 60 * 24));
}

// ── Transactions panel ──────────────────────────────────────────────────────

function TransactionsPanel({
  transactions, allCount, accounts, fx,
  filterType, setFilterType,
  filterCategory, setFilterCategory,
  onAdd, onEdit, onDelete, onMarkRecurring,
}: {
  transactions: Transaction[];
  allCount: number;
  accounts: Account[];
  fx: UseFxRates;
  filterType: "all" | "income" | "expense";
  setFilterType: (v: "all" | "income" | "expense") => void;
  filterCategory: string;
  setFilterCategory: (v: string) => void;
  onAdd: () => void;
  onEdit: (t: Transaction) => void;
  onDelete: (t: Transaction) => void;
  onMarkRecurring: (t: Transaction) => void;
}) {
  const { t: tBudget } = useTranslation("budget");
  const accountsById = useMemo(
    () => Object.fromEntries(accounts.map((a) => [a.id, a])),
    [accounts],
  );

  const allCategories = useMemo(() => {
    const set = new Set(COMMON_CATEGORIES);
    for (const t of transactions) if (t.category) set.add(t.category);
    return Array.from(set).sort();
  }, [transactions]);

  const VISIBLE_STEP = 10;
  const [visibleCount, setVisibleCount] = useState(VISIBLE_STEP);
  useEffect(() => { setVisibleCount(VISIBLE_STEP); }, [filterType, filterCategory, transactions.length]);
  const visibleTxs = transactions.slice(0, visibleCount);
  const hasMore = transactions.length > visibleCount;

  return (
    <section className="card mt-6">
      <header className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold">{tBudget("transactions.title")}</h2>
          <p className="text-[11px] text-[hsl(var(--text-muted))]">
            {transactions.length !== allCount
              ? tBudget("transactions.showingFiltered", { visible: visibleTxs.length, total: transactions.length, all: allCount })
              : tBudget("transactions.showing", { visible: visibleTxs.length, total: transactions.length })}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <FilterChip active={filterType === "all"} onClick={() => setFilterType("all")}>{tBudget("transactions.all")}</FilterChip>
          <FilterChip active={filterType === "income"} onClick={() => setFilterType("income")}>
            <ArrowDownRight className="h-3 w-3" /> {tBudget("transactions.income")}
          </FilterChip>
          <FilterChip active={filterType === "expense"} onClick={() => setFilterType("expense")}>
            <ArrowUpRight className="h-3 w-3" /> {tBudget("transactions.expense")}
          </FilterChip>
          <select
            value={filterCategory}
            onChange={(e) => setFilterCategory(e.target.value)}
            className="rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--surface-2))] px-2 py-1 text-xs"
          >
            <option value="all">{tBudget("transactions.allCategories")}</option>
            {allCategories.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
          <Button size="sm" onClick={onAdd}>
            <Plus className="h-3 w-3" /> {tBudget("common:add", "Add")}
          </Button>
        </div>
      </header>

      {transactions.length === 0 ? (
        <p className="rounded-lg border border-dashed border-[hsl(var(--border))] py-8 text-center text-xs text-[hsl(var(--text-muted))]">
          {tBudget("transactions.noMatch")}
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="num min-w-full text-sm">
            <thead className="text-xs text-[hsl(var(--text-muted))]">
              <tr className="border-b border-[hsl(var(--border))]">
                <th className="px-2 py-2 text-left font-normal">{tBudget("transactions.headers.date")}</th>
                <th className="px-2 py-2 text-left font-normal">{tBudget("transactions.headers.description")}</th>
                <th className="px-2 py-2 text-left font-normal">{tBudget("transactions.headers.category")}</th>
                <th className="px-2 py-2 text-left font-normal">{tBudget("transactions.headers.account")}</th>
                <th className="px-2 py-2 text-right font-normal">{tBudget("transactions.headers.amount")}</th>
                <th className="w-16 px-2 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {visibleTxs.map((t) => {
                const isIncome = t.type === "income";
                const acc = t.account_id != null ? accountsById[t.account_id] : null;
                return (
                  <tr key={t.id} className="group border-b border-[hsl(var(--border))] last:border-0 hover:bg-[hsl(var(--surface-2))]/50">
                    <td className="px-2 py-2.5 text-xs text-[hsl(var(--text-muted))]">{t.occurred_on}</td>
                    <td className="px-2 py-2.5">
                      <div className="flex items-center gap-1.5">
                        <SourceBadge source={t.source} />
                        <span className="truncate">{t.description || <span className="text-[hsl(var(--text-muted))]">{tBudget("transactions.noDescription")}</span>}</span>
                      </div>
                    </td>
                    <td className="px-2 py-2.5">
                      <span className="rounded bg-[hsl(var(--surface-2))] px-1.5 py-0.5 text-[11px] uppercase text-[hsl(var(--text-muted))]">
                        {t.category}
                      </span>
                    </td>
                    <td className="px-2 py-2.5 text-xs text-[hsl(var(--text-muted))]">
                      {acc ? acc.name : "—"}
                    </td>
                    <td className={cn(
                      "px-2 py-2.5 text-right font-semibold",
                      isIncome ? "text-gain" : "text-[hsl(var(--text))]",
                    )}>
                      <AmountCell
                        amount={t.amount}
                        currency={t.currency}
                        fx={fx}
                        sign={isIncome ? "pos" : "neg"}
                        className="text-sm"
                      />
                    </td>
                    <td className="px-2 py-2.5 text-right">
                      <div className="hidden justify-end gap-0.5 group-hover:flex">
                        <IconButton
                          onClick={() => onMarkRecurring(t)}
                          aria-label="Mark as recurring"
                          title="Mark as recurring income / expense"
                        >
                          <RefreshCcw className="h-3.5 w-3.5" />
                        </IconButton>
                        <IconButton onClick={() => onEdit(t)} aria-label="Edit"><Pencil className="h-3.5 w-3.5" /></IconButton>
                        <IconButton onClick={() => onDelete(t)} aria-label="Delete"><Trash2 className="h-3.5 w-3.5" /></IconButton>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {(hasMore || visibleCount > VISIBLE_STEP) && (
            <div className="mt-3 flex items-center justify-center gap-2">
              {hasMore && (
                <button
                  type="button"
                  onClick={() => setVisibleCount((n) => n + VISIBLE_STEP)}
                  className="rounded-full border border-[hsl(var(--border))] bg-[hsl(var(--surface-2))] px-3 py-1 text-xs text-[hsl(var(--text-muted))] hover:text-[hsl(var(--text))]"
                >
                  {tBudget("transactions.showMore")}
                </button>
              )}
              {hasMore && (
                <button
                  type="button"
                  onClick={() => setVisibleCount(transactions.length)}
                  className="rounded-full border border-[hsl(var(--border))] bg-[hsl(var(--surface-2))] px-3 py-1 text-xs text-[hsl(var(--text-muted))] hover:text-[hsl(var(--text))]"
                >
                  {tBudget("transactions.showAll")}
                </button>
              )}
              {visibleCount > VISIBLE_STEP && (
                <button
                  type="button"
                  onClick={() => setVisibleCount(VISIBLE_STEP)}
                  className="rounded-full border border-[hsl(var(--border))] bg-[hsl(var(--surface-2))] px-3 py-1 text-xs text-[hsl(var(--text-muted))] hover:text-[hsl(var(--text))]"
                >
                  {tBudget("transactions.showLess")}
                </button>
              )}
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function SourceBadge({ source }: { source: Transaction["source"] }) {
  const { t } = useTranslation("budget");
  const map = {
    manual: { icon: Pencil, title: t("transactions.sources.manual") },
    upload: { icon: Upload, title: t("transactions.sources.upload") },
    chat: { icon: Sparkles, title: t("transactions.sources.chat") },
    subscription: { icon: Calendar, title: t("transactions.sources.subscription") },
  };
  const { icon: Icon, title } = map[source] ?? map.manual;
  return (
    <span title={title} className="text-[hsl(var(--text-muted))]">
      <Icon className="h-3 w-3" />
    </span>
  );
}

function FilterChip({
  active, onClick, children,
}: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs transition",
        active
          ? "bg-accent text-white"
          : "border border-[hsl(var(--border))] bg-[hsl(var(--surface-2))] text-[hsl(var(--text-muted))] hover:text-[hsl(var(--text))]",
      )}
    >
      {children}
    </button>
  );
}

function AmountCell({
  amount, currency, fx, sign = "neutral", className,
}: {
  amount: number;
  currency: string;
  fx: UseFxRates;
  /** "pos" prepends "+", "neg" prepends "−". Both apply only to the converted figure. */
  sign?: "pos" | "neg" | "neutral";
  className?: string;
}) {
  const converted = fx.rates ? fx.convert(amount, currency) : null;
  const showOriginal = currency.toUpperCase() !== fx.target;
  const prefix = sign === "pos" ? "+" : sign === "neg" ? "−" : "";

  if (converted == null) {
    // Fallback: no FX yet — show native amount.
    return (
      <div className={cn("num tabular-nums", className)}>
        <span>{prefix}{amount.toLocaleString(undefined, { maximumFractionDigits: 2 })}</span>
        <span className="ml-1 text-[10px] text-[hsl(var(--text-muted))]">{currency}</span>
      </div>
    );
  }
  return (
    <div className={cn("num tabular-nums", className)}>
      <div>{prefix}{formatCurrency(converted, fx.target)}</div>
      {showOriginal && (
        <div className="text-[10px] font-normal text-[hsl(var(--text-muted))]">
          {amount.toLocaleString(undefined, { maximumFractionDigits: 2 })} {currency}
        </div>
      )}
    </div>
  );
}

function IconButton({
  onClick, children, ...rest
}: { onClick: () => void; children: React.ReactNode } & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      onClick={onClick}
      className="rounded p-1 text-[hsl(var(--text-muted))] transition hover:bg-[hsl(var(--surface))] hover:text-[hsl(var(--text))]"
      {...rest}
    >
      {children}
    </button>
  );
}

// ── Empty + skeleton ────────────────────────────────────────────────────────

function BudgetEmpty({
  onImport, onAddAccount, onAddManual,
}: {
  onImport: () => void;
  onAddAccount: () => void;
  onAddManual: () => void;
}) {
  const { t } = useTranslation("budget");
  return (
    <div className="card flex flex-col items-center text-center py-12">
      <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-accent-muted">
        <Banknote className="h-6 w-6 text-accent" />
      </div>
      <h2 className="text-lg font-semibold tracking-tight">{t("onboarding.title")}</h2>
      <p className="mt-1 max-w-md text-sm text-[hsl(var(--text-muted))]">
        {t("onboarding.subtitle")}
      </p>

      <div className="mt-6 grid w-full max-w-2xl grid-cols-1 gap-3 md:grid-cols-3">
        <CTACard
          icon={<Upload className="h-5 w-5" />}
          title={t("onboarding.uploadStatement")}
          description={t("onboarding.uploadStatementDesc")}
          accent
          onClick={onImport}
        />
        <CTACard
          icon={<Building2 className="h-5 w-5" />}
          title={t("onboarding.addAccount")}
          description={t("onboarding.addAccountDesc")}
          onClick={onAddAccount}
        />
        <CTACard
          icon={<Plus className="h-5 w-5" />}
          title={t("onboarding.logTransaction")}
          description={t("onboarding.logTransactionDesc")}
          onClick={onAddManual}
        />
      </div>
    </div>
  );
}

function CTACard({
  icon, title, description, onClick, accent = false,
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
  onClick: () => void;
  accent?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "flex flex-col items-start gap-2 rounded-xl border p-4 text-left transition",
        accent
          ? "border-accent bg-accent-muted/30 hover:bg-accent-muted/50"
          : "border-[hsl(var(--border))] bg-[hsl(var(--surface-2))] hover:border-[hsl(var(--text-muted))]",
      )}
    >
      <span className={cn(
        "flex h-9 w-9 items-center justify-center rounded-lg",
        accent ? "bg-accent text-white" : "bg-[hsl(var(--surface))] text-[hsl(var(--text-muted))]",
      )}>
        {icon}
      </span>
      <span className="text-sm font-semibold">{title}</span>
      <span className="text-xs text-[hsl(var(--text-muted))]">{description}</span>
    </button>
  );
}

function BudgetSkeleton() {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="card h-24 animate-pulse">
            <div className="h-3 w-24 rounded bg-[hsl(var(--surface-2))]" />
            <div className="mt-3 h-7 w-32 rounded bg-[hsl(var(--surface-2))]" />
          </div>
        ))}
      </div>
      <div className="card flex h-24 items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-[hsl(var(--text-muted))]" />
      </div>
    </div>
  );
}
