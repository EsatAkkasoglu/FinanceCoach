/**
 * Goals — gamified savings quest interface.
 *
 * Gamification layers:
 * - XP / Level system: total completion % → Başlangıç / Birikimci / Kahraman / Efsane
 * - Achievement badges: First Step, Halfway, Completionist, Multi-Goal
 * - Circular SVG progress rings with 25/50/75 % milestone markers
 * - Framer Motion: card entrance, contribution pulse, completion celebration
 * - Three.js ambient coin particles in the hero banner
 * - "+amount" floating label on each contribution
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { AnimatePresence, motion } from "framer-motion";
import {
  Plus, Pencil, Trash2, Target, Calendar, Loader2,
  TrendingUp, Zap, CheckCircle2, Home, Car, Plane,
  GraduationCap, Briefcase, Heart, Shield, BarChart3,
  PiggyBank, Star, Trophy, Flame, Award,
} from "lucide-react";

import {
  listGoals, createGoal, updateGoal, deleteGoal, type Goal,
} from "@/lib/api";
import { cn } from "@/lib/cn";
import { formatCurrency } from "@/lib/format";
import { useFxRates } from "@/lib/fx";
import { useSettingsStore } from "@/store";
import { Modal } from "@/components/ui/Modal";
import { Button } from "@/components/ui/Button";
import { Field, TextInput } from "@/components/ui/Field";
import { GoalsHero } from "./GoalsHero";
import { CircularProgress } from "./CircularProgress";

// ── Icon registry ─────────────────────────────────────────────────────────────
const ICON_MAP: Record<string, React.ReactNode> = {
  shield:    <Shield className="h-5 w-5" />,
  home:      <Home className="h-5 w-5" />,
  plane:     <Plane className="h-5 w-5" />,
  car:       <Car className="h-5 w-5" />,
  school:    <GraduationCap className="h-5 w-5" />,
  briefcase: <Briefcase className="h-5 w-5" />,
  heart:     <Heart className="h-5 w-5" />,
  chart:     <BarChart3 className="h-5 w-5" />,
  piggy:     <PiggyBank className="h-5 w-5" />,
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

const ICON_CHOICES = [
  { key: "shield",    icon: <Shield className="h-5 w-5" />,        label: "Acil" },
  { key: "home",      icon: <Home className="h-5 w-5" />,          label: "Ev" },
  { key: "plane",     icon: <Plane className="h-5 w-5" />,         label: "Tatil" },
  { key: "car",       icon: <Car className="h-5 w-5" />,           label: "Araç" },
  { key: "school",    icon: <GraduationCap className="h-5 w-5" />, label: "Eğitim" },
  { key: "briefcase", icon: <Briefcase className="h-5 w-5" />,     label: "İş" },
  { key: "heart",     icon: <Heart className="h-5 w-5" />,         label: "Sağlık" },
  { key: "piggy",     icon: <PiggyBank className="h-5 w-5" />,     label: "Birikim" },
  { key: "chart",     icon: <BarChart3 className="h-5 w-5" />,     label: "Yatırım" },
];

const CONTRIBUTE_AMOUNTS: Record<string, number[]> = {
  TRY: [500, 1000, 5000],
  USD: [10, 50, 100],
  EUR: [10, 50, 100],
};

// ── Gamification helpers ──────────────────────────────────────────────────────

interface LevelInfo {
  label: string;
  color: string;
  minXp: number;
  maxXp: number;
  icon: React.ReactNode;
}

const LEVELS: LevelInfo[] = [
  { label: "Başlangıç",  color: "text-slate-400",   minXp: 0,    maxXp: 2500,  icon: <Star className="h-4 w-4" /> },
  { label: "Birikimci",  color: "text-emerald-400", minXp: 2500, maxXp: 5000,  icon: <Flame className="h-4 w-4" /> },
  { label: "Kahraman",   color: "text-yellow-400",  minXp: 5000, maxXp: 7500,  icon: <Trophy className="h-4 w-4" /> },
  { label: "Efsane",     color: "text-purple-400",  minXp: 7500, maxXp: 10000, icon: <Award className="h-4 w-4" /> },
];

function getLevelInfo(xp: number): LevelInfo & { progress: number } {
  const lvl = [...LEVELS].reverse().find((l: LevelInfo) => xp >= l.minXp) ?? LEVELS[0];
  const progress = Math.min(100, ((xp - lvl.minXp) / (lvl.maxXp - lvl.minXp)) * 100);
  return { ...lvl, progress };
}

interface Achievement {
  key: string;
  label: string;
  desc: string;
  icon: React.ReactNode;
  unlocked: boolean;
}

function getAchievements(goals: Goal[]): Achievement[] {
  const completed = goals.filter((g) => (g.current_amount ?? 0) >= g.target_amount);
  const halfwayAny = goals.some((g) => g.target_amount > 0 && (g.current_amount ?? 0) / g.target_amount >= 0.5);
  return [
    {
      key: "first",
      label: "İlk Adım",
      desc: "İlk hedefini oluştur",
      icon: <Target className="h-4 w-4" />,
      unlocked: goals.length >= 1,
    },
    {
      key: "halfway",
      label: "Yarı Yolda",
      desc: "Bir hedefte %50'ye ulaş",
      icon: <Zap className="h-4 w-4" />,
      unlocked: halfwayAny,
    },
    {
      key: "complete",
      label: "Tamamcı",
      desc: "Bir hedefi tamamla",
      icon: <Trophy className="h-4 w-4" />,
      unlocked: completed.length >= 1,
    },
    {
      key: "multi",
      label: "Çok Hedefli",
      desc: "3 veya daha fazla hedef oluştur",
      icon: <Flame className="h-4 w-4" />,
      unlocked: goals.length >= 3,
    },
  ];
}

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
    try { setGoals(await listGoals()); }
    catch (e) { toast.error((e as Error).message); }
    finally { setLoading(false); }
  }

  useEffect(() => { void refresh(); }, []);

  async function handleContribute(goal: Goal, deltaInDisplay: number) {
    const goalCcy = (goal.currency || "TRY").toUpperCase();
    const displayCcy = useSettingsStore.getState().displayCurrency;
    let deltaInGoal = deltaInDisplay;
    if (goalCcy !== displayCcy) {
      const oneGoalInDisplay = convert(1, goalCcy);
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

  const displayCcy = useSettingsStore((s) => s.displayCurrency);

  const stats = useMemo(() => {
    if (!goals || goals.length === 0) return null;
    let total = 0, saved = 0;
    for (const g of goals) {
      const gccy = (g.currency || "TRY").toUpperCase();
      const t2 = gccy === displayCcy ? g.target_amount : (convert(g.target_amount, gccy) ?? g.target_amount);
      const c = gccy === displayCcy ? (g.current_amount ?? 0) : (convert(g.current_amount ?? 0, gccy) ?? (g.current_amount ?? 0));
      total += t2; saved += c;
    }
    const pct = total > 0 ? (saved / total) * 100 : 0;
    const completed = goals.filter((g) => (g.current_amount ?? 0) >= g.target_amount).length;
    // XP = total pct * 100, capped at 10000
    const xp = Math.min(10000, Math.round(pct * 100));
    return { total, saved, pct, completed, count: goals.length, xp };
  }, [goals, convert, displayCcy]);

  return (
    <div className="space-y-6">
      {/* ── Hero banner with Three.js particles ── */}
      <div className="relative overflow-hidden rounded-2xl border border-line bg-gradient-to-br from-[#0d1117] via-[#0f1f0f] to-[#0d1117] px-6 py-8">
        <GoalsHero />
        <div className="relative z-10 flex items-start justify-between gap-4">
          <div>
            <p className="text-[10px] uppercase tracking-widest text-emerald-400/70">Savings Quest</p>
            <h1 className="mt-1 text-3xl font-bold tracking-tight text-white">
              {t("title")}
            </h1>
            <p className="mt-1 text-sm text-white/50">{t("subtitle")}</p>
          </div>
          <Button onClick={() => setCreating(true)} className="shrink-0">
            <Plus className="h-4 w-4" /> {t("addGoal")}
          </Button>
        </div>

        {/* XP bar inside hero */}
        {stats && (() => {
          const lvl = getLevelInfo(stats.xp);
          return (
            <div className="relative z-10 mt-6">
              <div className="flex items-center justify-between text-xs">
                <span className={cn("flex items-center gap-1.5 font-semibold", lvl.color)}>
                  {lvl.icon} {lvl.label}
                </span>
                <span className="text-white/40">{stats.xp.toLocaleString()} / 10 000 XP</span>
              </div>
              <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-white/10">
                <motion.div
                  className={cn(
                    "h-full rounded-full",
                    stats.xp >= 7500 ? "bg-purple-400"
                    : stats.xp >= 5000 ? "bg-yellow-400"
                    : stats.xp >= 2500 ? "bg-emerald-400"
                    : "bg-slate-400",
                  )}
                  initial={{ width: 0 }}
                  animate={{ width: `${(stats.xp / 10000) * 100}%` }}
                  transition={{ duration: 1.2, ease: "easeOut" }}
                />
              </div>
            </div>
          );
        })()}
      </div>

      {loading ? (
        <div className="card flex h-32 items-center justify-center text-content-muted">
          <Loader2 className="h-5 w-5 animate-spin" />
        </div>
      ) : goals && goals.length > 0 ? (
        <>
          {/* ── Achievement badges ── */}
          {goals.length > 0 && <AchievementsRow goals={goals} />}

          {/* ── Summary stats ── */}
          {stats && <SummaryBanner stats={stats} />}

          {/* ── Goal cards ── */}
          <motion.div
            className="grid grid-cols-1 gap-4 lg:grid-cols-2"
            initial="hidden"
            animate="visible"
            variants={{ visible: { transition: { staggerChildren: 0.1 } } }}
          >
            {goals.map((g) => (
              <GoalCard
                key={g.id}
                goal={g}
                onEdit={() => setEditing(g)}
                onContribute={(amt) => handleContribute(g, amt)}
                onDelete={() => handleDelete(g)}
              />
            ))}
          </motion.div>
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

// ── Achievement badges row ────────────────────────────────────────────────────

function AchievementsRow({ goals }: { goals: Goal[] }) {
  const achievements = getAchievements(goals);
  return (
    <div className="flex flex-wrap gap-2">
      {achievements.map((a) => (
        <motion.div
          key={a.key}
          initial={{ scale: 0.8, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          title={a.desc}
          className={cn(
            "flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition-all",
            a.unlocked
              ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300 shadow-[0_0_12px_#22c55e22]"
              : "border-line bg-surface-raised text-content-muted opacity-40",
          )}
        >
          <span className={a.unlocked ? "text-emerald-400" : "text-content-muted"}>
            {a.icon}
          </span>
          {a.label}
          {a.unlocked && (
            <CheckCircle2 className="h-3 w-3 text-emerald-400" />
          )}
        </motion.div>
      ))}
    </div>
  );
}

// ── Summary banner ────────────────────────────────────────────────────────────

function SummaryBanner({
  stats,
}: {
  stats: { total: number; saved: number; pct: number; completed: number; count: number; xp: number };
}) {
  const ccy = useSettingsStore((s) => s.displayCurrency);
  return (
    <div className="grid grid-cols-3 gap-3">
      {[
        { label: "Toplam Hedef",  value: formatCurrency(stats.total, ccy),   sub: null,                    color: "" },
        { label: "Biriktirilen",  value: formatCurrency(stats.saved, ccy),   sub: `%${stats.pct.toFixed(0)} tamamlandı`, color: "text-gain" },
        { label: "Tamamlanan",    value: `${stats.completed} / ${stats.count}`, sub: "hedef",              color: stats.completed > 0 ? "text-yellow-400" : "" },
      ].map(({ label, value, sub, color }) => (
        <div key={label} className="card text-center">
          <p className="text-[10px] uppercase tracking-wide text-content-muted">{label}</p>
          <p className={cn("mt-1 text-lg font-bold tabular-nums", color)}>{value}</p>
          {sub && <p className="text-[10px] text-content-muted">{sub}</p>}
        </div>
      ))}
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
  const [floatingLabels, setFloatingLabels] = useState<{ id: number; amount: number }[]>([]);
  const [pulse, setPulse] = useState(false);
  const labelId = useRef(0);

  const goalCcy = (goal.currency || "TRY").toUpperCase();
  const currentRaw = goal.current_amount ?? 0;
  const targetRaw = goal.target_amount;
  const current = goalCcy === ccy ? currentRaw : (convert(currentRaw, goalCcy) ?? currentRaw);
  const target  = goalCcy === ccy ? targetRaw  : (convert(targetRaw, goalCcy) ?? targetRaw);
  const pct = target > 0 ? Math.min(100, (current / target) * 100) : 0;
  const remaining = Math.max(0, target - current);
  const completed = currentRaw >= targetRaw;

  const daysLeft = useMemo(() => {
    if (!goal.target_date) return null;
    const d = new Date(goal.target_date + "T00:00:00");
    const today = new Date(); today.setHours(0, 0, 0, 0);
    return Math.round((d.getTime() - today.getTime()) / 86_400_000);
  }, [goal.target_date]);

  const monthlyNeeded = useMemo(() => {
    if (!goal.target_date || remaining <= 0) return null;
    const months = (daysLeft ?? 0) / 30.44;
    if (months <= 0) return null;
    return remaining / months;
  }, [goal.target_date, remaining, daysLeft]);

  const quickAmounts = CONTRIBUTE_AMOUNTS[ccy] ?? CONTRIBUTE_AMOUNTS.USD;

  function fireContribute(amt: number) {
    onContribute(amt);
    // Floating label
    const id = ++labelId.current;
    setFloatingLabels((prev) => [...prev, { id, amount: amt }]);
    setTimeout(() => setFloatingLabels((prev) => prev.filter((l) => l.id !== id)), 1200);
    // Ring pulse
    setPulse(true);
    setTimeout(() => setPulse(false), 600);
  }

  function handleCustomSubmit(e: React.FormEvent) {
    e.preventDefault();
    const n = parseFloat(customVal.replace(",", "."));
    if (!isNaN(n) && n !== 0) {
      fireContribute(n);
      setCustomVal(""); setCustomMode(false);
    }
  }

  const goalIcon = ICON_MAP[goal.icon] ?? <Target className="h-5 w-5" />;

  return (
    <motion.section
      variants={{ hidden: { opacity: 0, y: 20 }, visible: { opacity: 1, y: 0 } }}
      transition={{ type: "spring", stiffness: 260, damping: 22 }}
      className={cn(
        "card flex flex-col gap-4 transition-shadow",
        completed
          ? "ring-1 ring-gain/40 shadow-[0_0_24px_#22c55e18]"
          : "hover:shadow-lg",
        pulse && "ring-1 ring-accent/50",
      )}
    >
      {/* ── Card header ── */}
      <header className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 flex-1 items-start gap-3">
          {/* Circular progress ring */}
          <div className="relative">
            <CircularProgress
              pct={pct}
              size={72}
              strokeWidth={7}
              completed={completed}
            >
              {/* Center icon */}
              <span className={cn(
                "flex items-center justify-center rounded-full",
                completed ? "text-gain" : "text-accent",
              )}>
                {completed
                  ? <CheckCircle2 className="h-5 w-5" />
                  : goalIcon}
              </span>
            </CircularProgress>

            {/* Floating +amount labels */}
            <AnimatePresence>
              {floatingLabels.map(({ id, amount }) => (
                <motion.div
                  key={id}
                  initial={{ opacity: 1, y: 0, x: "-50%" }}
                  animate={{ opacity: 0, y: -40, x: "-50%" }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 1 }}
                  className="pointer-events-none absolute left-1/2 top-0 text-xs font-bold text-gain"
                >
                  +{formatCurrency(amount, ccy)}
                </motion.div>
              ))}
            </AnimatePresence>
          </div>

          {/* Title + date */}
          <div className="min-w-0 flex-1 pt-1">
            <div className="flex items-center gap-1.5">
              <h2 className="truncate font-semibold">{goal.title}</h2>
              {completed && (
                <motion.span
                  initial={{ scale: 0 }} animate={{ scale: 1 }}
                  className="shrink-0 rounded-full bg-gain/15 px-2 py-0.5 text-[10px] font-medium text-gain"
                >
                  ✓ Tamamlandı
                </motion.span>
              )}
            </div>

            {/* Progress text */}
            <p className="mt-0.5 text-xs text-content-muted">
              <span className={cn("font-semibold", completed ? "text-gain" : "text-content")}>
                {formatCurrency(current, ccy)}
              </span>
              {" / "}{formatCurrency(target, ccy)}
              <span className={cn("ml-2 font-medium", pct >= 75 ? "text-gain" : pct >= 50 ? "text-accent" : "text-content-muted")}>
                %{pct.toFixed(0)}
              </span>
            </p>

            {/* Days remaining */}
            {goal.target_date && daysLeft != null && (
              <p className="mt-0.5 flex items-center gap-1 text-[11px] text-content-muted">
                <Calendar className="h-3 w-3" />
                {daysLeft < 0
                  ? tCommon("time.daysPastTarget", { days: Math.abs(daysLeft) })
                  : daysLeft === 0
                    ? tCommon("time.dueToday")
                    : tCommon("time.daysToGo", { days: daysLeft })}
              </p>
            )}
          </div>
        </div>

        {/* Edit / delete */}
        <div className="flex shrink-0 gap-0.5">
          <button onClick={onEdit} className="rounded p-1.5 text-content-muted hover:bg-surface-raised hover:text-content transition" aria-label="Düzenle">
            <Pencil className="h-3.5 w-3.5" />
          </button>
          <button onClick={onDelete} className="rounded p-1.5 text-content-muted hover:bg-surface-raised hover:text-loss transition" aria-label="Sil">
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      </header>

      {/* ── Milestone track ── */}
      <MilestoneTrack pct={pct} />

      {/* ── Monthly savings hint ── */}
      {monthlyNeeded != null && !completed && (
        <div className="flex items-center gap-2 rounded-lg bg-surface-raised px-3 py-2 text-[11px]">
          <TrendingUp className="h-3.5 w-3.5 shrink-0 text-accent" />
          <span className="text-content-muted">
            Hedefe ulaşmak için aylık{" "}
            <span className="font-semibold text-content">{formatCurrency(monthlyNeeded, ccy)}</span>
            {" "}biriktirmeniz gerekiyor
          </span>
        </div>
      )}

      {/* ── Contribute buttons ── */}
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
                className="flex-1 rounded-lg border border-line bg-surface-raised px-3 py-1.5 text-sm outline-none focus:border-accent"
              />
              <button type="submit" className="rounded-lg bg-accent px-3 py-1.5 text-xs font-medium text-white hover:opacity-90 transition">
                Ekle
              </button>
              <button type="button" onClick={() => { setCustomMode(false); setCustomVal(""); }}
                className="rounded-lg border border-line px-3 py-1.5 text-xs text-content-muted hover:bg-surface-raised transition">
                İptal
              </button>
            </form>
          ) : (
            <div className="flex flex-wrap gap-2">
              {quickAmounts.map((amt) => (
                <motion.button
                  key={amt}
                  whileTap={{ scale: 0.93 }}
                  onClick={() => fireContribute(amt)}
                  className="rounded-full border border-line bg-surface-raised px-3 py-1 text-xs font-medium text-content-muted transition hover:border-gain hover:bg-gain/10 hover:text-gain"
                >
                  +{formatCurrency(amt, ccy)}
                </motion.button>
              ))}
              <motion.button
                whileTap={{ scale: 0.93 }}
                onClick={() => fireContribute(-(quickAmounts[0]))}
                className="rounded-full border border-line bg-surface-raised px-3 py-1 text-xs font-medium text-content-muted transition hover:border-loss hover:bg-loss/10 hover:text-loss"
              >
                -{formatCurrency(quickAmounts[0], ccy)}
              </motion.button>
              <button
                onClick={() => setCustomMode(true)}
                className="rounded-full border border-dashed border-line px-3 py-1 text-xs text-content-muted transition hover:border-accent hover:text-accent"
              >
                <Zap className="mr-1 inline h-3 w-3" />Özel
              </button>
            </div>
          )}
        </div>
      )}

      {/* ── Completion banner ── */}
      {completed && (
        <motion.div
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          className="flex items-center gap-2 rounded-lg bg-gain/10 px-3 py-2 text-xs font-medium text-gain ring-1 ring-gain/20"
        >
          <Trophy className="h-4 w-4 text-yellow-400" />
          Tebrikler! Bu hedefe ulaştınız. 🎉
        </motion.div>
      )}
    </motion.section>
  );
}

// ── Milestone track ───────────────────────────────────────────────────────────

function MilestoneTrack({ pct }: { pct: number }) {
  const milestones = [25, 50, 75, 100];

  return (
    <div className="select-none">
      {/* Bar + dots layer — fixed height so dots don't overflow */}
      <div className="relative h-5 w-full">
        {/* Background bar — vertically centered */}
        <div className="absolute inset-x-0 top-1/2 h-1.5 -translate-y-1/2 overflow-hidden rounded-full bg-surface-raised">
          <motion.div
            className={cn(
              "h-full rounded-full",
              pct >= 100 ? "bg-gain"
              : pct >= 66  ? "bg-emerald-400"
              : pct >= 33  ? "bg-accent"
              : "bg-accent/60",
            )}
            initial={{ width: 0 }}
            animate={{ width: `${Math.min(pct, 100)}%` }}
            transition={{ duration: 0.8, ease: "easeOut" }}
          />
        </div>

        {/* Milestone dots — positioned absolutely, centered on the bar */}
        {milestones.map((m) => {
          const passed = pct >= m;
          // Keep 100% dot inside the container (shift left by half dot width)
          const leftStyle = m === 100 ? "calc(100% - 6px)" : `${m}%`;
          return (
            <div
              key={m}
              className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2"
              style={{ left: leftStyle }}
            >
              <div className={cn(
                "h-2.5 w-2.5 rounded-full border-[1.5px] transition-all duration-500",
                passed
                  ? "border-gain bg-gain shadow-[0_0_6px_rgba(34,197,94,0.5)]"
                  : "border-line bg-bg",
              )} />
            </div>
          );
        })}
      </div>

      {/* Labels row — sits below bar, doesn't overlap dots */}
      <div className="relative mt-0.5 h-3.5">
        {milestones.map((m) => {
          // %100 label: align right so it doesn't overflow
          const isLast = m === 100;
          return (
            <span
              key={m}
              className={cn(
                "absolute text-[9px] transition-colors duration-500",
                isLast ? "right-0 translate-x-0" : "-translate-x-1/2",
                pct >= m ? "text-gain" : "text-content-muted/40",
              )}
              style={isLast ? {} : { left: `${m}%` }}
            >
              %{m}
            </span>
          );
        })}
      </div>
    </div>
  );
}

// ── Empty state ───────────────────────────────────────────────────────────────

function EmptyState({ onCreate }: { onCreate: () => void }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      className="card flex flex-col items-center py-16 text-center"
    >
      <motion.div
        animate={{ y: [0, -8, 0] }}
        transition={{ duration: 2.5, repeat: Infinity, ease: "easeInOut" }}
        className="mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-accent/15 text-accent"
      >
        <Target className="h-8 w-8" />
      </motion.div>
      <h2 className="text-base font-semibold">Henüz hedef yok</h2>
      <p className="mt-1 max-w-sm text-sm text-content-muted">
        Birikim hedefinizi belirleyin — ev peşinatı, acil fon, tatil veya istediğiniz herhangi bir şey.
      </p>
      <Button className="mt-5" onClick={onCreate}>
        <Plus className="h-4 w-4" /> İlk hedefi oluştur
      </Button>
    </motion.div>
  );
}

// ── Goal form modal ───────────────────────────────────────────────────────────

interface GoalForm {
  title: string; target_amount: number; current_amount: number;
  target_date: string; icon: string; currency: string;
}
const EMPTY_FORM: GoalForm = {
  title: "", target_amount: 0, current_amount: 0,
  target_date: "", icon: "shield", currency: "TRY",
};

function GoalFormModal({
  open, editing, onClose, onSaved,
}: {
  open: boolean; editing: Goal | null; onClose: () => void; onSaved: () => void;
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

  const monthlyPreview = useMemo(() => {
    if (!form.target_date || form.target_amount <= 0) return null;
    const d = new Date(form.target_date + "T00:00:00");
    const today = new Date(); today.setHours(0, 0, 0, 0);
    const days = Math.round((d.getTime() - today.getTime()) / 86_400_000);
    const months = days / 30.44;
    if (months <= 0) return null;
    return Math.max(0, form.target_amount - form.current_amount) / months;
  }, [form.target_date, form.target_amount, form.current_amount]);

  const previewPct = form.target_amount > 0
    ? Math.min(100, (form.current_amount / form.target_amount) * 100)
    : 0;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.title.trim() || !(form.target_amount > 0)) {
      toast.error(t("validationError")); return;
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
      if (editing) { await updateGoal(editing.id, payload); toast.success("Hedef güncellendi"); }
      else { await createGoal(payload); toast.success("Hedef oluşturuldu 🎯"); }
      onSaved();
    } catch (e) {
      toast.error((e as Error).message);
    } finally { setSubmitting(false); }
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
        {/* Live ring preview */}
        <div className="flex justify-center py-2">
          <CircularProgress pct={previewPct} size={80} strokeWidth={8}>
            <span className="text-xs font-bold text-content">
              {previewPct.toFixed(0)}%
            </span>
          </CircularProgress>
        </div>

        <Field label={t("form.title")}>
          <TextInput
            autoFocus value={form.title}
            onChange={(e) => setForm({ ...form, title: e.target.value })}
            placeholder={t("form.titlePlaceholder")}
          />
        </Field>

        <Field label={t("form.icon")}>
          <div className="grid grid-cols-9 gap-1.5">
            {ICON_CHOICES.map(({ key, icon }) => (
              <button
                key={key} type="button"
                onClick={() => setForm({ ...form, icon: key })}
                className={cn(
                  "flex h-9 w-full items-center justify-center rounded-lg border transition",
                  form.icon === key
                    ? "border-accent bg-accent/15 text-accent"
                    : "border-line bg-surface-raised text-content-muted hover:border-content-muted hover:text-content",
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
              <button key={c} type="button"
                onClick={() => setForm({ ...form, currency: c })}
                className={cn(
                  "flex-1 rounded-lg border py-1.5 text-xs font-medium transition",
                  form.currency === c
                    ? "border-accent bg-accent/15 text-accent"
                    : "border-line bg-surface-raised text-content-muted hover:border-content-muted",
                )}
              >
                {c}
              </button>
            ))}
          </div>
        </Field>

        <div className="grid grid-cols-2 gap-3">
          <Field label={`${t("form.targetAmount")} (${form.currency})`}>
            <TextInput inputMode="decimal" value={form.target_amount || ""}
              onChange={(e) => setForm({ ...form, target_amount: Number(e.target.value) || 0 })}
              placeholder={t("form.targetPlaceholder")}
            />
          </Field>
          <Field label={`${t("form.currentAmount")} (${form.currency})`} hint={t("form.currentHint")}>
            <TextInput inputMode="decimal" value={form.current_amount || ""}
              onChange={(e) => setForm({ ...form, current_amount: Number(e.target.value) || 0 })}
              placeholder="0"
            />
          </Field>
        </div>

        <Field label={t("form.targetDate")} hint={t("form.targetDateHint")}>
          <TextInput type="date" value={form.target_date}
            onChange={(e) => setForm({ ...form, target_date: e.target.value })}
          />
        </Field>

        {monthlyPreview != null && (
          <div className="flex items-start gap-2 rounded-lg bg-accent/10 px-3 py-2.5 text-xs">
            <TrendingUp className="mt-0.5 h-3.5 w-3.5 shrink-0 text-accent" />
            <span className="text-content-muted">
              Bu hedefe ulaşmak için aylık yaklaşık{" "}
              <span className="font-semibold text-content">
                {formatCurrency(monthlyPreview, form.currency)}
              </span>{" "}biriktirmeniz gerekecek.
            </span>
          </div>
        )}

        <button type="submit" hidden />
      </form>
    </Modal>
  );
}
