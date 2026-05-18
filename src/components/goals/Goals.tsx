import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import {
  Plus, Pencil, Trash2, Target, Calendar, Loader2,
  TrendingUp, Zap, CheckCircle2, Home, Car, Plane,
  GraduationCap, Briefcase, Heart, Shield, BarChart3,
  PiggyBank,
} from "lucide-react";

import {
  listGoals,
  createGoal,
  updateGoal,
  deleteGoal,
  type Goal,
} from "@/lib/api";
import { cn } from "@/lib/cn";
import { formatCurrency } from "@/lib/format";
import { useFxRates } from "@/lib/fx";
import { useSettingsStore } from "@/store";
import { Modal } from "@/components/ui/Modal";
import { Button } from "@/components/ui/Button";
import { Field, TextInput } from "@/components/ui/Field";

// ── Icon registry ────────────────────────────────────────────────────────────
// Maps legacy text keys (seeded from onboarding) AND emoji to a Lucide icon.
const ICON_MAP: Record<string, React.ReactNode> = {
  shield:  <Shield className="h-5 w-5" />,
  home:    <Home className="h-5 w-5" />,
  plane:   <Plane className="h-5 w-5" />,
  car:     <Car className="h-5 w-5" />,
  school:  <GraduationCap className="h-5 w-5" />,
  briefcase: <Briefcase className="h-5 w-5" />,
  heart:   <Heart className="h-5 w-5" />,
  chart:   <BarChart3 className="h-5 w-5" />,
  piggy:   <PiggyBank className="h-5 w-5" />,
  // legacy emoji keys from old ICON_CHOICES
  "🎯": <Target className="h-5 w-5" />,
  "🏠": <Home className="h-5 w-5" />,
  "🚗": <Car className="h-5 w-5" />,
  "✈️": <Plane className="h-5 w-5" />,
  "🎓": <GraduationCap className="h-5 w-5" />,
  "💍": <Heart className="h-5 w-5" />,
  "💼": <Briefcase className="h-5 w-5" />,
  "🛟": <Shield className="h-5 w-5" />,
  "📈": <BarChart3 className="h-5 w-5" />,
};

// Icon choices shown in the form (key → display icon + label)
const ICON_CHOICES: { key: string; icon: React.ReactNode; label: string }[] = [
  { key: "shield",    icon: <Shield className="h-5 w-5" />,         label: "Acil" },
  { key: "home",      icon: <Home className="h-5 w-5" />,           label: "Ev" },
  { key: "plane",     icon: <Plane className="h-5 w-5" />,          label: "Tatil" },
  { key: "car",       icon: <Car className="h-5 w-5" />,            label: "Araç" },
  { key: "school",    icon: <GraduationCap className="h-5 w-5" />,  label: "Eğitim" },
  { key: "briefcase", icon: <Briefcase className="h-5 w-5" />,      label: "İş" },
  { key: "heart",     icon: <Heart className="h-5 w-5" />,          label: "Sağlık" },
  { key: "piggy",     icon: <PiggyBank className="h-5 w-5" />,      label: "Birikim" },
  { key: "chart",     icon: <BarChart3 className="h-5 w-5" />,      label: "Yatırım" },
];

function GoalIcon({ icon }: { icon: string }) {
  return (
    <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-accent/15 text-accent">
      {ICON_MAP[icon] ?? <Target className="h-5 w-5" />}
    </span>
  );
}

// ── Quick-contribute amounts (scale to currency) ─────────────────────────────
const CONTRIBUTE_AMOUNTS: Record<string, number[]> = {
  TRY: [500, 1000, 5000],
  USD: [10, 50, 100],
  EUR: [10, 50, 100],
};

// ── Goals page ────────────────────────────────────────────────────────────────
export function Goals() {
  const { t } = useTranslation("goals");
  const { convert } = useFxRates();
  const [goals, setGoals] = useState<Goal[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<Goal | null>(null);
  const [creating, setCreating] = useState(false);

  async function refresh() {
    setLoading(true);
    try {
      setGoals(await listGoals());
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void refresh(); }, []);

  // deltaInDisplay is in the current displayCurrency; we convert it to the
  // goal's own currency before persisting.
  async function handleContribute(goal: Goal, deltaInDisplay: number, fxConvert: (amount: number, fromCcy: string) => number | null) {
    const goalCcy = (goal.currency || "TRY").toUpperCase();
    const displayCcy = useSettingsStore.getState().displayCurrency;
    let deltaInGoal = deltaInDisplay;
    if (goalCcy !== displayCcy) {
      // fxConvert(x, fromCcy) → x expressed in displayCcy
      // To go displayCcy → goalCcy: divide by rate(1 goalCcy → displayCcy)
      const oneGoalInDisplay = fxConvert(1, goalCcy);
      if (oneGoalInDisplay != null && oneGoalInDisplay > 0) {
        deltaInGoal = deltaInDisplay / oneGoalInDisplay;
      }
    }
    const next = Math.max(0, (goal.current_amount ?? 0) + deltaInGoal);
    try {
      const updated = await updateGoal(goal.id, { current_amount: next });
      setGoals((prev) => prev?.map((g) => (g.id === goal.id ? updated : g)) ?? null);
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  async function handleDelete(goal: Goal) {
    if (!window.confirm(`"${goal.title}" silinsin mi?`)) return;
    try {
      await deleteGoal(goal.id);
      setGoals((prev) => prev?.filter((g) => g.id !== goal.id) ?? null);
      toast.success("Hedef silindi");
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  // Summary stats — convert each goal's amounts to displayCurrency before summing
  const displayCcy = useSettingsStore((s) => s.displayCurrency);
  const stats = useMemo(() => {
    if (!goals || goals.length === 0) return null;
    let total = 0, saved = 0;
    for (const g of goals) {
      const gccy = (g.currency || "TRY").toUpperCase();
      const t = gccy === displayCcy ? g.target_amount : (convert(g.target_amount, gccy) ?? g.target_amount);
      const c = gccy === displayCcy ? (g.current_amount ?? 0) : (convert(g.current_amount ?? 0, gccy) ?? (g.current_amount ?? 0));
      total += t;
      saved += c;
    }
    const pct = total > 0 ? (saved / total) * 100 : 0;
    const completed = goals.filter((g) => (g.current_amount ?? 0) >= g.target_amount).length;
    return { total, saved, pct, completed, count: goals.length };
  }, [goals, convert, displayCcy]);

  return (
    <div className="space-y-6">
      {/* Header */}
      <header className="flex items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">{t("title")}</h1>
          <p className="text-sm text-[hsl(var(--text-muted))]">{t("subtitle")}</p>
        </div>
        <Button onClick={() => setCreating(true)}>
          <Plus className="h-4 w-4" /> {t("addGoal")}
        </Button>
      </header>

      {loading ? (
        <div className="card flex h-32 items-center justify-center text-[hsl(var(--text-muted))]">
          <Loader2 className="h-5 w-5 animate-spin" />
        </div>
      ) : goals && goals.length > 0 ? (
        <>
          {/* Summary banner */}
          {stats && <SummaryBanner stats={stats} />}

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            {goals.map((g) => (
              <GoalCard
                key={g.id}
                goal={g}
                onEdit={() => setEditing(g)}
                onContribute={(amt) => handleContribute(g, amt, convert)}
                onDelete={() => handleDelete(g)}
              />
            ))}
          </div>
        </>
      ) : (
        <EmptyState onCreate={() => setCreating(true)} />
      )}

      <GoalFormModal
        open={creating || editing != null}
        editing={editing}
        onClose={() => { setCreating(false); setEditing(null); }}
        onSaved={() => { setCreating(false); setEditing(null); void refresh(); }}
      />
    </div>
  );
}

// ── Summary banner ────────────────────────────────────────────────────────────
function SummaryBanner({
  stats,
}: {
  stats: { total: number; saved: number; pct: number; completed: number; count: number };
}) {
  const ccy = useSettingsStore((s) => s.displayCurrency);
  return (
    <div className="card grid grid-cols-3 divide-x divide-[hsl(var(--border))]">
      <div className="px-4 py-3 first:pl-0 last:pr-0">
        <p className="text-[11px] uppercase tracking-wide text-[hsl(var(--text-muted))]">Toplam hedef</p>
        <p className="mt-0.5 text-lg font-semibold tabular-nums">{formatCurrency(stats.total, ccy)}</p>
      </div>
      <div className="px-4 py-3">
        <p className="text-[11px] uppercase tracking-wide text-[hsl(var(--text-muted))]">Biriktirilen</p>
        <p className="mt-0.5 text-lg font-semibold tabular-nums text-gain">{formatCurrency(stats.saved, ccy)}</p>
      </div>
      <div className="px-4 py-3">
        <p className="text-[11px] uppercase tracking-wide text-[hsl(var(--text-muted))]">Tamamlanan</p>
        <p className="mt-0.5 text-lg font-semibold tabular-nums">
          {stats.completed} / {stats.count}
          <span className="ml-1.5 text-sm font-normal text-[hsl(var(--text-muted))]">
            (%{stats.pct.toFixed(0)})
          </span>
        </p>
      </div>
    </div>
  );
}

// ── Goal card ─────────────────────────────────────────────────────────────────
function GoalCard({
  goal, onEdit, onContribute, onDelete,
}: {
  goal: Goal;
  onEdit: () => void;
  onContribute: (delta: number) => void;
  onDelete: () => void;
}) {
  const { t: tCommon } = useTranslation("common");
  const ccy = useSettingsStore((s) => s.displayCurrency);
  const { convert } = useFxRates();
  const [customMode, setCustomMode] = useState(false);
  const [customVal, setCustomVal] = useState("");

  const goalCcy = (goal.currency || "TRY").toUpperCase();
  const currentRaw = goal.current_amount ?? 0;
  const targetRaw = goal.target_amount;

  // Convert stored amounts (in goalCcy) to displayCcy for rendering.
  // If rates not loaded yet, fall back to raw values.
  const current = goalCcy === ccy ? currentRaw : (convert(currentRaw, goalCcy) ?? currentRaw);
  const target = goalCcy === ccy ? targetRaw : (convert(targetRaw, goalCcy) ?? targetRaw);
  const pct = target > 0 ? Math.min(100, (current / target) * 100) : 0;
  const remaining = Math.max(0, target - current);
  const completed = currentRaw >= targetRaw;

  const daysLeft = useMemo(() => {
    if (!goal.target_date) return null;
    const d = new Date(goal.target_date + "T00:00:00");
    const today = new Date(); today.setHours(0, 0, 0, 0);
    return Math.round((d.getTime() - today.getTime()) / 86_400_000);
  }, [goal.target_date]);

  // Monthly savings needed to hit goal in time
  const monthlyNeeded = useMemo(() => {
    if (!goal.target_date || remaining <= 0) return null;
    const months = (daysLeft ?? 0) / 30.44;
    if (months <= 0) return null;
    return remaining / months;
  }, [goal.target_date, remaining, daysLeft]);

  const quickAmounts = CONTRIBUTE_AMOUNTS[ccy] ?? CONTRIBUTE_AMOUNTS.USD;

  function handleCustomSubmit(e: React.FormEvent) {
    e.preventDefault();
    const n = parseFloat(customVal.replace(",", "."));
    if (!isNaN(n) && n !== 0) {
      onContribute(n);
      setCustomVal("");
      setCustomMode(false);
    }
  }

  return (
    <section className={cn("card flex flex-col gap-4", completed && "ring-1 ring-gain/40")}>
      {/* Card header */}
      <header className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3 min-w-0">
          <GoalIcon icon={goal.icon} />
          <div className="min-w-0">
            <div className="flex items-center gap-1.5">
              <h2 className="truncate text-sm font-semibold">{goal.title}</h2>
              {completed && <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-gain" />}
            </div>
            {goal.target_date && daysLeft != null && (
              <p className="mt-0.5 text-[11px] text-[hsl(var(--text-muted))]">
                <span className="inline-flex items-center gap-1">
                  <Calendar className="h-3 w-3" />
                  {daysLeft < 0
                    ? tCommon("time.daysPastTarget", { days: Math.abs(daysLeft) })
                    : daysLeft === 0
                      ? tCommon("time.dueToday")
                      : tCommon("time.daysToGo", { days: daysLeft })}
                </span>
              </p>
            )}
          </div>
        </div>
        <div className="flex shrink-0 gap-0.5">
          <button
            onClick={onEdit}
            className="rounded p-1.5 text-[hsl(var(--text-muted))] hover:bg-[hsl(var(--surface-2))] hover:text-[hsl(var(--text))] transition"
            aria-label="Düzenle"
          >
            <Pencil className="h-3.5 w-3.5" />
          </button>
          <button
            onClick={onDelete}
            className="rounded p-1.5 text-[hsl(var(--text-muted))] hover:bg-[hsl(var(--surface-2))] hover:text-loss transition"
            aria-label="Sil"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      </header>

      {/* Amounts + progress */}
      <div>
        <div className="flex items-baseline justify-between">
          <span className="text-xl font-bold tabular-nums">
            {formatCurrency(current, ccy)}
          </span>
          <span className="text-sm text-[hsl(var(--text-muted))] tabular-nums">
            / {formatCurrency(target, ccy)}
          </span>
        </div>

        {/* Progress bar */}
        <div className="mt-2 h-2.5 overflow-hidden rounded-full bg-[hsl(var(--surface-2))]">
          <div
            className={cn(
              "h-full rounded-full transition-all duration-500",
              completed ? "bg-gain" : pct > 66 ? "bg-accent" : pct > 33 ? "bg-accent" : "bg-accent/70",
            )}
            style={{ width: `${pct}%` }}
          />
        </div>

        {/* Stats row */}
        <div className="mt-2 flex items-center justify-between text-[11px] text-[hsl(var(--text-muted))]">
          <span className={cn("font-medium", completed ? "text-gain" : "")}>
            %{pct.toFixed(0)} tamamlandı
          </span>
          {!completed && (
            <span>{formatCurrency(remaining, ccy)} kaldı</span>
          )}
        </div>
      </div>

      {/* Monthly savings hint */}
      {monthlyNeeded != null && !completed && (
        <div className="flex items-center gap-2 rounded-lg bg-[hsl(var(--surface-2))] px-3 py-2 text-[11px]">
          <TrendingUp className="h-3.5 w-3.5 shrink-0 text-accent" />
          <span className="text-[hsl(var(--text-muted))]">
            Hedefe ulaşmak için aylık{" "}
            <span className="font-semibold text-[hsl(var(--text))]">
              {formatCurrency(monthlyNeeded, ccy)}
            </span>{" "}
            biriktirmeniz gerekiyor
          </span>
        </div>
      )}

      {/* Contribute / custom section */}
      {!completed && (
        <div>
          {customMode ? (
            <form onSubmit={handleCustomSubmit} className="flex gap-2">
              <input
                autoFocus
                type="number"
                value={customVal}
                onChange={(e) => setCustomVal(e.target.value)}
                placeholder={`Tutar (${ccy})`}
                className="flex-1 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--surface-2))] px-3 py-1.5 text-sm outline-none focus:border-accent"
              />
              <button
                type="submit"
                className="rounded-lg bg-accent px-3 py-1.5 text-xs font-medium text-white hover:opacity-90 transition"
              >
                Ekle
              </button>
              <button
                type="button"
                onClick={() => { setCustomMode(false); setCustomVal(""); }}
                className="rounded-lg border border-[hsl(var(--border))] px-3 py-1.5 text-xs text-[hsl(var(--text-muted))] hover:bg-[hsl(var(--surface-2))] transition"
              >
                İptal
              </button>
            </form>
          ) : (
            <div className="flex flex-wrap gap-2">
              {quickAmounts.map((amt) => (
                <button
                  key={amt}
                  onClick={() => onContribute(amt)}
                  className="rounded-full border border-[hsl(var(--border))] bg-[hsl(var(--surface-2))] px-3 py-1 text-xs font-medium text-[hsl(var(--text-muted))] transition hover:border-gain hover:bg-gain/10 hover:text-gain"
                >
                  +{formatCurrency(amt, ccy)}
                </button>
              ))}
              <button
                onClick={() => onContribute(-(quickAmounts[0]))}
                className="rounded-full border border-[hsl(var(--border))] bg-[hsl(var(--surface-2))] px-3 py-1 text-xs font-medium text-[hsl(var(--text-muted))] transition hover:border-loss hover:bg-loss/10 hover:text-loss"
              >
                -{formatCurrency(quickAmounts[0], ccy)}
              </button>
              <button
                onClick={() => setCustomMode(true)}
                className="rounded-full border border-dashed border-[hsl(var(--border))] px-3 py-1 text-xs text-[hsl(var(--text-muted))] transition hover:border-accent hover:text-accent"
              >
                <Zap className="mr-1 inline h-3 w-3" />Özel tutar
              </button>
            </div>
          )}
        </div>
      )}

      {completed && (
        <div className="flex items-center gap-2 rounded-lg bg-gain/10 px-3 py-2 text-xs font-medium text-gain">
          <CheckCircle2 className="h-4 w-4" />
          Tebrikler! Bu hedefe ulaştınız.
        </div>
      )}
    </section>
  );
}

// ── Empty state ───────────────────────────────────────────────────────────────
function EmptyState({ onCreate }: { onCreate: () => void }) {
  return (
    <div className="card flex flex-col items-center py-16 text-center">
      <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-accent/15 text-accent">
        <Target className="h-7 w-7" />
      </div>
      <h2 className="text-base font-semibold">Henüz hedef yok</h2>
      <p className="mt-1 max-w-sm text-sm text-[hsl(var(--text-muted))]">
        Birikim hedefinizi belirleyin — ev peşinatı, acil fon, tatil veya istediğiniz herhangi bir şey.
      </p>
      <Button className="mt-5" onClick={onCreate}>
        <Plus className="h-4 w-4" /> İlk hedefi oluştur
      </Button>
    </div>
  );
}

// ── Goal form modal ───────────────────────────────────────────────────────────
interface GoalForm {
  title: string;
  target_amount: number;
  current_amount: number;
  target_date: string;
  icon: string;
  currency: string;
}

const EMPTY_FORM: GoalForm = {
  title: "",
  target_amount: 0,
  current_amount: 0,
  target_date: "",
  icon: "shield",
  currency: "TRY",
};

function GoalFormModal({
  open, editing, onClose, onSaved,
}: {
  open: boolean;
  editing: Goal | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = useTranslation("goals");
  const { t: tCommon } = useTranslation("common");
  const ccy = useSettingsStore((s) => s.displayCurrency);
  const [form, setForm] = useState<GoalForm>({ ...EMPTY_FORM, currency: ccy });
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!open) return;
    setForm(
      editing
        ? {
            title: editing.title,
            target_amount: editing.target_amount,
            current_amount: editing.current_amount ?? 0,
            target_date: editing.target_date ?? "",
            icon: editing.icon || "shield",
            currency: editing.currency || ccy,
          }
        : { ...EMPTY_FORM, currency: ccy },
    );
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, editing]);

  // Live preview: monthly savings needed
  const monthlyPreview = useMemo(() => {
    if (!form.target_date || form.target_amount <= 0) return null;
    const d = new Date(form.target_date + "T00:00:00");
    const today = new Date(); today.setHours(0, 0, 0, 0);
    const days = Math.round((d.getTime() - today.getTime()) / 86_400_000);
    const months = days / 30.44;
    if (months <= 0) return null;
    const remaining = Math.max(0, form.target_amount - form.current_amount);
    return remaining / months;
  }, [form.target_date, form.target_amount, form.current_amount]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.title.trim() || !(form.target_amount > 0)) {
      toast.error(t("validationError"));
      return;
    }
    setSubmitting(true);
    try {
      const payload = {
        title: form.title.trim(),
        target_amount: form.target_amount,
        current_amount: form.current_amount,
        target_date: form.target_date || null,
        icon: form.icon,
        currency: form.currency,
      };
      if (editing) {
        await updateGoal(editing.id, payload);
        toast.success("Hedef güncellendi");
      } else {
        await createGoal(payload);
        toast.success("Hedef oluşturuldu");
      }
      onSaved();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={editing ? t("form.editTitle") : t("form.newTitle")}
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={onClose} type="button">{tCommon("cancel")}</Button>
          <Button onClick={handleSubmit} loading={submitting} type="submit">
            {editing ? t("form.saveChanges") : t("form.create")}
          </Button>
        </>
      }
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        <Field label={t("form.title")}>
          <TextInput
            autoFocus
            value={form.title}
            onChange={(e) => setForm({ ...form, title: e.target.value })}
            placeholder={t("form.titlePlaceholder")}
          />
        </Field>

        <Field label={t("form.icon")}>
          <div className="grid grid-cols-9 gap-1.5">
            {ICON_CHOICES.map(({ key, icon }) => (
              <button
                key={key}
                type="button"
                onClick={() => setForm({ ...form, icon: key })}
                title={key}
                className={cn(
                  "flex h-9 w-full items-center justify-center rounded-lg border transition",
                  form.icon === key
                    ? "border-accent bg-accent/15 text-accent"
                    : "border-[hsl(var(--border))] bg-[hsl(var(--surface-2))] text-[hsl(var(--text-muted))] hover:border-[hsl(var(--text-muted))] hover:text-[hsl(var(--text))]",
                )}
              >
                {icon}
              </button>
            ))}
          </div>
        </Field>

        <Field label="Para birimi">
          <div className="flex gap-2">
            {(["TRY", "USD", "EUR"] as const).map((c) => (
              <button
                key={c}
                type="button"
                onClick={() => setForm({ ...form, currency: c })}
                className={cn(
                  "flex-1 rounded-lg border py-1.5 text-xs font-medium transition",
                  form.currency === c
                    ? "border-accent bg-accent/15 text-accent"
                    : "border-[hsl(var(--border))] bg-[hsl(var(--surface-2))] text-[hsl(var(--text-muted))] hover:border-[hsl(var(--text-muted))]",
                )}
              >
                {c}
              </button>
            ))}
          </div>
        </Field>

        <div className="grid grid-cols-2 gap-3">
          <Field label={`${t("form.targetAmount")} (${form.currency})`}>
            <TextInput
              inputMode="decimal"
              value={form.target_amount || ""}
              onChange={(e) => setForm({ ...form, target_amount: Number(e.target.value) || 0 })}
              placeholder={t("form.targetPlaceholder")}
            />
          </Field>
          <Field label={`${t("form.currentAmount")} (${form.currency})`} hint={t("form.currentHint")}>
            <TextInput
              inputMode="decimal"
              value={form.current_amount || ""}
              onChange={(e) => setForm({ ...form, current_amount: Number(e.target.value) || 0 })}
              placeholder="0"
            />
          </Field>
        </div>

        <Field label={t("form.targetDate")} hint={t("form.targetDateHint")}>
          <TextInput
            type="date"
            value={form.target_date}
            onChange={(e) => setForm({ ...form, target_date: e.target.value })}
          />
        </Field>

        {/* Live monthly savings preview */}
        {monthlyPreview != null && (
          <div className="flex items-start gap-2 rounded-lg bg-accent/10 px-3 py-2.5 text-xs">
            <TrendingUp className="mt-0.5 h-3.5 w-3.5 shrink-0 text-accent" />
            <span className="text-[hsl(var(--text-muted))]">
              Bu hedefe ulaşmak için aylık yaklaşık{" "}
              <span className="font-semibold text-[hsl(var(--text))]">
                {formatCurrency(monthlyPreview, form.currency)}
              </span>{" "}
              biriktirmeniz gerekecek.
            </span>
          </div>
        )}

        <button type="submit" hidden />
      </form>
    </Modal>
  );
}
